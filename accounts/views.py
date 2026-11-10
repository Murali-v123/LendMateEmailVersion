import logging
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core.cache import cache, caches
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView

from .forms import LendMateAuthenticationForm, LendMatePasswordChangeForm, RegistrationForm

logger = logging.getLogger(__name__)

_REDIS_CHECK_INTERVAL = 30.0  # seconds between probe attempts
_redis_available = None
_redis_last_check = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client_ip(request):
    """
    Return the client's IP address.

    When TRUST_PROXY_HEADERS is True we read the *rightmost* hop from
    X-Forwarded-For that our trusted reverse proxy (e.g. Render) appended.
    When TRUST_PROXY_HEADERS is False we use REMOTE_ADDR directly and ignore
    X-Forwarded-For to prevent client spoofing.
    """
    if getattr(settings, "TRUST_PROXY_HEADERS", False):
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if xff:
            hops = [h.strip() for h in xff.split(",") if h.strip()]
            if hops:
                return hops[-1]
    return request.META.get("REMOTE_ADDR", "unknown")


def _get_cache():
    """Return the best available cache backend for throttle state without blocking per request."""
    global _redis_available, _redis_last_check
    now = time.monotonic()
    if _redis_available is not None and (now - _redis_last_check < _REDIS_CHECK_INTERVAL):
        return cache if _redis_available else caches["locmem"]

    _redis_last_check = now
    try:
        cache.get("__probe__")
        if _redis_available is not True:
            logger.info("Redis available for login throttle.")
        _redis_available = True
        return cache
    except Exception:  # noqa: BLE001
        if _redis_available is not False:
            logger.warning("Redis unavailable for login throttle; falling back to in-process cache.")
        _redis_available = False
        return caches["locmem"]


def _lockout_key(ip):
    return f"login_lockout:{ip}"


def _attempts_key(ip):
    return f"login_attempts:{ip}"


def _user_lockout_key(ip, username):
    return f"login_user_lockout:{ip}:{username}"


def _user_attempts_key(ip, username):
    return f"login_user_attempts:{ip}:{username}"


def _atomic_incr(c, key, timeout):
    """Atomically increment a cache counter or initialize it with a TTL."""
    try:
        return c.incr(key)
    except (ValueError, Exception):
        c.set(key, 1, timeout)
        return 1


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class RegisterView(FormView):
    """
    Public self-registration view.

    Disabled by default.  Set ALLOW_SELF_REGISTRATION=true in the environment
    to enable it.  Production deployments should keep this off and create
    lender accounts through the Django admin.
    """

    template_name = "accounts/register.html"
    form_class = RegistrationForm
    success_url = reverse_lazy("core:dashboard")

    def dispatch(self, request, *args, **kwargs):
        if not getattr(settings, "ALLOW_SELF_REGISTRATION", False):
            raise Http404("Self-registration is disabled.")
        if request.user.is_authenticated:
            return redirect(self.success_url)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(self.request, f"Welcome to LendMate, {user.first_name or user.username}.")
        return super().form_valid(form)


class ThrottledLoginView(LoginView):
    """
    Login view with per-IP brute-force protection.

    Tracks failed attempts in the cache (Redis with locmem fallback).
    After LOGIN_MAX_ATTEMPTS failures the IP is locked out for
    LOGIN_LOCKOUT_SECONDS seconds.

    Error messages deliberately avoid confirming whether a username exists.
    """

    template_name = "accounts/login.html"
    authentication_form = LendMateAuthenticationForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        ip = _client_ip(request)
        c = _get_cache()

        if request.method == "POST":
            username = request.POST.get("username", "").strip().lower()
            # Reject locked-out IP or locked-out (IP, username)
            def _locked(store):
                return bool(store.get(_lockout_key(ip))) or bool(
                    username and store.get(_user_lockout_key(ip, username))
                )

            try:
                locked = _locked(c)
            except Exception:  # noqa: BLE001
                # Redis can fail between availability checks; fall back rather than returning a 500.
                logger.warning("Login lockout check failed; using in-process cache.")
                c = caches["locmem"]
                locked = _locked(c)

            if locked:
                messages.error(
                    request,
                    "Too many failed login attempts. Please wait 15 minutes before trying again.",
                )
                return self.render_to_response(self.get_context_data())

        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """Clear throttle state on successful login."""
        ip = _client_ip(self.request)
        c = _get_cache()
        username = form.cleaned_data.get("username", "").strip().lower()
        c.delete(_attempts_key(ip))
        c.delete(_lockout_key(ip))
        if username:
            c.delete(_user_attempts_key(ip, username))
            c.delete(_user_lockout_key(ip, username))
        return super().form_valid(form)

    def form_invalid(self, form):
        """Increment failure counter; lock out when threshold is reached."""
        ip = _client_ip(self.request)
        c = _get_cache()
        username = self.request.POST.get("username", "").strip().lower()

        max_attempts = getattr(settings, "LOGIN_MAX_ATTEMPTS", 5)
        lockout_seconds = getattr(settings, "LOGIN_LOCKOUT_SECONDS", 900)

        ip_max_attempts = getattr(settings, "LOGIN_IP_MAX_ATTEMPTS", max_attempts * 3)
        attempts_key = _attempts_key(ip)
        lockout_key = _lockout_key(ip)
        user_attempts_key = _user_attempts_key(ip, username) if username else None
        user_lockout_key = _user_lockout_key(ip, username) if username else None

        try:
            attempts = _atomic_incr(c, attempts_key, lockout_seconds)
            user_attempts = _atomic_incr(c, user_attempts_key, lockout_seconds) if user_attempts_key else attempts

            is_locked_out = False
            if attempts >= ip_max_attempts:
                c.set(lockout_key, True, lockout_seconds)
                is_locked_out = True

            if user_lockout_key and user_attempts >= max_attempts:
                c.set(user_lockout_key, True, lockout_seconds)
                is_locked_out = True

            if is_locked_out:
                logger.warning(
                    "Login locked out for IP %s (user %s) after %d failed attempts.",
                    ip, username or "unknown", max(attempts, user_attempts),
                )
                from django import forms as django_forms
                form._errors = django_forms.utils.ErrorDict()
                messages.error(
                    self.request,
                    "Too many failed login attempts. Please wait 15 minutes before trying again.",
                )
            else:
                remaining = max(0, max_attempts - max(attempts, user_attempts))
                logger.info(
                    "Failed login attempt %d/%d from IP %s.",
                    max(attempts, user_attempts), max_attempts, ip,
                )
                messages.error(
                    self.request,
                    f"Invalid credentials. {remaining} attempt(s) remaining before lockout.",
                )
        except Exception:  # noqa: BLE001
            logger.exception("Login throttle cache error; proceeding without throttle.")

        return super().form_invalid(form)


class LendMatePasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = LendMatePasswordChangeForm
    success_url = reverse_lazy("core:settings")

    def form_valid(self, form):
        messages.success(self.request, "Your password has been updated.")
        return super().form_valid(form)
