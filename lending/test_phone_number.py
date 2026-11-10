"""Borrower phone number: optional, validated, shown on the profile, never used to send messages."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .forms import BorrowerForm
from .models import Borrower


class BorrowerPhoneNumberTests(TestCase):
    def setUp(self):
        self.lender = User.objects.create_user(username="ph_lender", password="Pass123!Secure")

    def _form(self, **overrides):
        data = {"full_name": "Phone Person", "email": "", "email_consent": "", "notes": "", "phone_number": ""}
        data.update(overrides)
        return BorrowerForm(data=data)

    def test_phone_is_optional(self):
        self.assertTrue(self._form().is_valid())

    def test_valid_phone_is_accepted_and_saved(self):
        form = self._form(phone_number="+91 98765 43210")
        self.assertTrue(form.is_valid(), form.errors)
        borrower = form.save(commit=False)
        borrower.lender = self.lender
        borrower.save()
        self.assertEqual(Borrower.objects.get(pk=borrower.pk).phone_number, "+91 98765 43210")

    def test_invalid_phone_is_rejected(self):
        for bad in ["abc", "12", "98765-abc", "1" * 16, "+" + "9" * 25]:
            with self.subTest(phone=bad):
                form = self._form(phone_number=bad)
                self.assertFalse(form.is_valid())
                self.assertIn("phone_number", form.errors)

    def test_profile_shows_phone(self):
        borrower = Borrower.objects.create(
            lender=self.lender, full_name="Shown Borrower", phone_number="+91 98765 43210",
        )
        self.client.force_login(self.lender)
        response = self.client.get(reverse("lending:borrower_detail", kwargs={"pk": borrower.pk}))
        self.assertContains(response, "+91 98765 43210")
