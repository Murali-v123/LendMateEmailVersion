from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


class AuthenticationTests(TestCase):
    password = "Sup3r-secret-pass"

    def setUp(self):
        super().setUp()
        from accounts.views import _get_cache
        _get_cache().clear()

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('core:dashboard')}",
        )

    @override_settings(ALLOW_SELF_REGISTRATION=True)
    def test_registration_creates_lender_and_signs_in(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "full_name": "Asha Rao",
                "username": "asha",
                "email": "Asha@Example.com",
                "password1": self.password,
                "password2": self.password,
            },
        )
        self.assertRedirects(response, reverse("core:dashboard"))
        user = User.objects.get(username="asha")
        self.assertEqual(user.first_name, "Asha Rao")
        self.assertEqual(user.email, "asha@example.com")
        self.assertTrue(user.check_password(self.password))
        self.assertNotEqual(user.password, self.password)

    @override_settings(ALLOW_SELF_REGISTRATION=True)
    def test_registration_rejects_duplicate_email(self):
        User.objects.create_user("existing", email="taken@example.com", password=self.password)
        response = self.client.post(
            reverse("accounts:register"),
            {
                "full_name": "Other Person",
                "username": "other",
                "email": "TAKEN@example.com",
                "password1": self.password,
                "password2": self.password,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="other").exists())

    def test_registration_disabled_returns_404(self):
        """Registration must return 404 when ALLOW_SELF_REGISTRATION is False (default)."""
        with self.settings(ALLOW_SELF_REGISTRATION=False):
            response = self.client.get(reverse("accounts:register"))
        self.assertEqual(response.status_code, 404)

    def test_login_and_logout_round_trip(self):
        User.objects.create_user("ravi", email="ravi@example.com", password=self.password)
        response = self.client.post(
            reverse("accounts:login"), {"username": "ravi", "password": self.password}
        )
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)

        # Logout must be POST-only.
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))
        self.assertRedirects(
            self.client.get(reverse("core:dashboard")),
            f"{reverse('accounts:login')}?next={reverse('core:dashboard')}",
        )

    def test_password_reset_sends_email_to_registered_address(self):
        User.objects.create_user("meera", email="meera@example.com", password=self.password)
        self.client.post(reverse("accounts:password_reset"), {"email": "meera@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["meera@example.com"])
        self.assertIn("/accounts/password/reset/", mail.outbox[0].body)

    def test_settings_page_renders_for_signed_in_user(self):
        User.objects.create_user("kiran", email="kiran@example.com", password=self.password)
        self.client.login(username="kiran", password=self.password)
        response = self.client.get(reverse("core:settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "kiran@example.com")

    @override_settings(LOGIN_MAX_ATTEMPTS=3, LOGIN_LOCKOUT_SECONDS=60)
    def test_login_lockout_after_max_attempts(self):
        """After LOGIN_MAX_ATTEMPTS bad logins the IP must be locked out."""
        User.objects.create_user("locktest", password="GoodPass1!")
        url = reverse("accounts:login")
        for _ in range(3):
            self.client.post(url, {"username": "locktest", "password": "wrong"})
        # 4th attempt — should be locked out regardless of credentials
        response = self.client.post(url, {"username": "locktest", "password": "GoodPass1!"})
        self.assertContains(response, "Too many failed login attempts")

    @override_settings(LOGIN_MAX_ATTEMPTS=3, LOGIN_LOCKOUT_SECONDS=60)
    def test_login_lockout_clears_on_success(self):
        """Successful login must clear throttle state."""
        from accounts.views import _get_cache, _attempts_key, _lockout_key
        cache = _get_cache()
        User.objects.create_user("cleartest", password="GoodPass1!")
        url = reverse("accounts:login")
        # 2 bad attempts (below threshold)
        for _ in range(2):
            self.client.post(url, {"username": "cleartest", "password": "wrong"})
        # Successful login
        response = self.client.post(url, {"username": "cleartest", "password": "GoodPass1!"})
        self.assertRedirects(response, reverse("core:dashboard"))
        # Cache keys should be cleared
        ip = "127.0.0.1"
        self.assertIsNone(cache.get(_attempts_key(ip)))
        self.assertIsNone(cache.get(_lockout_key(ip)))

    @override_settings(TRUST_PROXY_HEADERS=True, LOGIN_MAX_ATTEMPTS=3, LOGIN_LOCKOUT_SECONDS=60)
    def test_shared_ip_lockout_protection(self):
        """Behind a reverse proxy, user A lockout must not lock out user B on the same shared IP."""
        User.objects.create_user("user_a", password="GoodPasswordA1!")
        User.objects.create_user("user_b", password="GoodPasswordB1!")
        url = reverse("accounts:login")
        proxy_header = {"HTTP_X_FORWARDED_FOR": "203.0.113.10, 198.51.100.5"}

        # 3 failed attempts on user_a
        for _ in range(3):
            self.client.post(url, {"username": "user_a", "password": "wrongpassword"}, **proxy_header)

        # user_a is now locked out
        response_a = self.client.post(url, {"username": "user_a", "password": "GoodPasswordA1!"}, **proxy_header)
        self.assertContains(response_a, "Too many failed login attempts")

        # user_b sharing the same proxy IP can still log in successfully
        response_b = self.client.post(url, {"username": "user_b", "password": "GoodPasswordB1!"}, **proxy_header)
        self.assertRedirects(response_b, reverse("core:dashboard"))

    @override_settings(TRUST_PROXY_HEADERS=False)
    def test_proxy_header_ignored_when_trust_proxy_headers_is_false(self):
        """When TRUST_PROXY_HEADERS is False, X-Forwarded-For is ignored to prevent client spoofing."""
        from accounts.views import _client_ip
        from django.test import RequestFactory
        rf = RequestFactory()
        req = rf.get("/accounts/login/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(_client_ip(req), "127.0.0.1")

    def test_login_works_when_redis_unavailable(self):
        """Login functions normally even if Redis fails/times out."""
        from unittest.mock import patch
        User.objects.create_user("fallback_user", password=self.password)
        with patch("django.core.cache.cache.get", side_effect=Exception("Redis connection refused")):
            response = self.client.post(
                reverse("accounts:login"),
                {"username": "fallback_user", "password": self.password},
            )
            self.assertRedirects(response, reverse("core:dashboard"))
