"""Recycle bin: delete moves a borrower aside, restore brings them back, purge is guarded."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Borrower, Loan


class RecycleBinTests(TestCase):
    def setUp(self):
        self.lender = User.objects.create_user(username="bin_lender", password="Pass123!Secure")
        self.other = User.objects.create_user(username="bin_other", password="Pass123!Secure")
        self.borrower = Borrower.objects.create(
            lender=self.lender, full_name="Bin Borrower", email="bin@example.com", email_consent=True,
        )

    def _loan(self, borrower, status="closed"):
        return Loan.objects.create(
            borrower=borrower,
            principal=Decimal("1000.00"),
            interest_rate=Decimal("0.00"),
            interest_period="monthly",
            interest_basis="original",
            lending_date=datetime.date(2026, 1, 1),
            monthly_due_day=5,
            status=status,
        )

    def _delete(self, borrower):
        return self.client.post(reverse("lending:delete_borrower", kwargs={"pk": borrower.pk}))

    def test_delete_hides_borrower_from_list_and_detail(self):
        self.client.force_login(self.lender)
        self._delete(self.borrower)

        self.assertFalse(Borrower.objects.filter(pk=self.borrower.pk).exists())
        self.assertTrue(
            Borrower.all_objects.filter(pk=self.borrower.pk, deleted_at__isnull=False).exists()
        )
        # Check for the row's detail link, not the name: the success flash message also contains the name.
        listing = self.client.get(reverse("lending:borrower_list"))
        self.assertNotContains(listing, f'href="/lending/borrowers/{self.borrower.pk}/"')
        detail = self.client.get(reverse("lending:borrower_detail", kwargs={"pk": self.borrower.pk}))
        self.assertEqual(detail.status_code, 404)

    def test_closed_loans_of_binned_borrower_are_hidden_but_kept(self):
        loan = self._loan(self.borrower, status="closed")
        self.client.force_login(self.lender)
        self._delete(self.borrower)

        self.assertFalse(Loan.objects.filter(pk=loan.pk).exists())
        self.assertTrue(Loan.all_objects.filter(pk=loan.pk).exists())

    def test_borrower_with_open_loan_cannot_be_deleted(self):
        self._loan(self.borrower, status="open")
        self.client.force_login(self.lender)
        self._delete(self.borrower)

        self.assertTrue(Borrower.objects.filter(pk=self.borrower.pk).exists())

    def test_restore_brings_borrower_back(self):
        self.client.force_login(self.lender)
        self._delete(self.borrower)
        self.client.post(reverse("lending:restore_borrower", kwargs={"pk": self.borrower.pk}))

        self.assertTrue(Borrower.objects.filter(pk=self.borrower.pk, deleted_at__isnull=True).exists())

    def test_purge_is_blocked_when_loan_records_exist(self):
        self._loan(self.borrower, status="closed")
        self.client.force_login(self.lender)
        self._delete(self.borrower)
        self.client.post(reverse("lending:purge_borrower", kwargs={"pk": self.borrower.pk}))

        self.assertTrue(Borrower.all_objects.filter(pk=self.borrower.pk).exists())

    def test_purge_removes_borrower_without_loans(self):
        self.client.force_login(self.lender)
        self._delete(self.borrower)
        self.client.post(reverse("lending:purge_borrower", kwargs={"pk": self.borrower.pk}))

        self.assertFalse(Borrower.all_objects.filter(pk=self.borrower.pk).exists())

    def test_other_lender_cannot_delete_restore_or_purge(self):
        self.client.force_login(self.other)
        self.assertEqual(self._delete(self.borrower).status_code, 404)

        self.client.force_login(self.lender)
        self._delete(self.borrower)

        self.client.force_login(self.other)
        restore = self.client.post(reverse("lending:restore_borrower", kwargs={"pk": self.borrower.pk}))
        purge = self.client.post(reverse("lending:purge_borrower", kwargs={"pk": self.borrower.pk}))
        self.assertEqual(restore.status_code, 404)
        self.assertEqual(purge.status_code, 404)
        self.assertTrue(Borrower.all_objects.filter(pk=self.borrower.pk, deleted_at__isnull=False).exists())

    def test_recycle_bin_lists_only_own_deleted_borrowers(self):
        self.client.force_login(self.lender)
        self._delete(self.borrower)
        response = self.client.get(reverse("lending:recycle_bin"))

        self.assertContains(response, "Bin Borrower")
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse("lending:recycle_bin")), "Bin Borrower")
