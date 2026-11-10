"""
Tests for the interest schedule: expected interest per period, tracker amounts,
the advisory interest check on payments,and borrower email validation.
"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .forms import BorrowerForm
from .models import Borrower, BorrowerTracker, Loan, TrackerItem
from django.core.exceptions import ValidationError

from .services import create_payment

User = get_user_model()


class ScheduleBase(TestCase):
    def setUp(self):
        self.lender = User.objects.create_user(username="sched_lender", password="pass-1234-xyz")
        self.borrower = Borrower.objects.create(
            lender=self.lender, full_name="Schedule Borrower",
        )

    def _loan(self, **overrides):
        values = dict(
            borrower=self.borrower,
            principal=Decimal("100000.00"),
            interest_rate=Decimal("2.00"),
            interest_period="monthly",
            interest_basis="original",
            lending_date=datetime.date(2026, 1, 15),
            monthly_due_day=15,
            status="open",
        )
        values.update(overrides)
        return Loan.objects.create(**values)


class ExpectedInterestTests(ScheduleBase):
    def test_original_basis_uses_original_principal(self):
        loan = self._loan()
        self.assertEqual(loan.expected_interest_as_of(datetime.date(2026, 3, 1)), Decimal("2000.00"))

    def test_reducing_basis_uses_balance_owed_on_period_start(self):
        loan = self._loan(interest_basis="reducing")
        create_payment(
            loan_pk=loan.pk,
            payment_date=datetime.date(2026, 2, 10),
            amount=Decimal("50000.00"),
            principal_component=Decimal("50000.00"),
            interest_component=Decimal("0.00"),
        )
        # February starts before the repayment, so it still uses 100,000.
        self.assertEqual(loan.expected_interest_as_of(datetime.date(2026, 2, 1)), Decimal("2000.00"))
        # March starts after it, so it uses the 50,000 still owed.
        self.assertEqual(loan.expected_interest_as_of(datetime.date(2026, 3, 1)), Decimal("1000.00"))

    def test_voided_repayments_do_not_reduce_the_base(self):
        from .services import void_payment
        loan = self._loan(interest_basis="reducing")
        payment = create_payment(
            loan_pk=loan.pk,
            payment_date=datetime.date(2026, 2, 10),
            amount=Decimal("50000.00"),
            principal_component=Decimal("50000.00"),
            interest_component=Decimal("0.00"),
        )
        void_payment(payment_pk=payment.pk, void_reason="Entered by mistake")
        self.assertEqual(loan.expected_interest_as_of(datetime.date(2026, 3, 1)), Decimal("2000.00"))

    def test_zero_rate_expects_nothing(self):
        loan = self._loan(interest_rate=Decimal("0.00"))
        self.assertEqual(loan.expected_interest_as_of(datetime.date(2026, 3, 1)), Decimal("0.00"))

    def test_rounds_to_paise(self):
        loan = self._loan(principal=Decimal("1000.00"), interest_rate=Decimal("1.555"))
        self.assertEqual(loan.expected_interest_as_of(datetime.date(2026, 3, 1)), Decimal("15.55"))


class TrackerAmountTests(ScheduleBase):
    def _automatic_tracker(self, loan):
        return BorrowerTracker.objects.create(
            borrower=self.borrower, loan=loan, tracker_type="automatic",
            title="Monthly", start_date=loan.lending_date, end_date=datetime.date(2026, 6, 15),
        )

    def test_monthly_tracker_item_shows_expected_interest(self):
        loan = self._loan()
        item = TrackerItem.objects.create(
            tracker=self._automatic_tracker(loan), title="March 2026",
            tracking_date=datetime.date(2026, 3, 1),
        )
        self.assertEqual(item.expected_interest, Decimal("2000.00"))
        self.assertEqual(item.expected_interest_display, "Due ₹2,000.00")

    def test_annual_loan_items_show_no_monthly_amount(self):
        loan = self._loan(interest_period="annually", monthly_due_day=None)
        item = TrackerItem.objects.create(
            tracker=self._automatic_tracker(loan), title="March 2026",
            tracking_date=datetime.date(2026, 3, 1),
        )
        self.assertIsNone(item.expected_interest)
        self.assertEqual(item.expected_interest_display, "")

    def test_manual_checklist_item_has_no_amount(self):
        tracker = BorrowerTracker.objects.create(
            borrower=self.borrower, tracker_type="custom", title="Manual",
        )
        item = TrackerItem.objects.create(tracker=tracker, title="Call borrower")
        self.assertIsNone(item.expected_interest)


class InterestTermsValidationTests(ScheduleBase):
    """Interest is capped at what the loan has accrued and not yet been paid."""

    def _pay(self, loan, payment_date, interest, principal="0.00"):
        return create_payment(
            loan_pk=loan.pk,
            payment_date=payment_date,
            amount=Decimal(principal) + Decimal(interest),
            principal_component=Decimal(principal),
            interest_component=Decimal(interest),
        )

    def test_interest_equal_to_accrued_is_accepted(self):
        loan = self._loan()
        # Due dates Jan 15, Feb 15 and Mar 15 have all accrued by March: 3 x 2000.
        payment = self._pay(loan, datetime.date(2026, 3, 10), "6000.00")
        self.assertEqual(payment.interest_component, Decimal("6000.00"))

    def test_interest_above_accrued_is_rejected_with_the_amount_due(self):
        loan = self._loan()
        with self.assertRaises(ValidationError) as ctx:
            self._pay(loan, datetime.date(2026, 3, 10), "6000.01")
        self.assertIn("6,000.00", str(ctx.exception.messages[0]))

    def test_partial_interest_is_accepted(self):
        loan = self._loan()
        payment = self._pay(loan, datetime.date(2026, 3, 10), "500.00")
        self.assertEqual(payment.interest_component, Decimal("500.00"))

    def test_interest_already_recorded_is_not_counted_twice(self):
        loan = self._loan()
        self._pay(loan, datetime.date(2026, 2, 10), "4000.00")  # Jan + Feb accrued
        # Only March's 2000 is left to pay.
        self._pay(loan, datetime.date(2026, 3, 10), "2000.00")
        with self.assertRaises(ValidationError):
            self._pay(loan, datetime.date(2026, 3, 11), "1.00")

    def test_interest_for_a_later_due_date_in_the_same_month_can_be_paid_early(self):
        loan = self._loan(lending_date=datetime.date(2026, 2, 1))
        # The Feb 15 due date is later in the month but counts as accrued by Feb 28.
        payment = self._pay(loan, datetime.date(2026, 2, 3), "2000.00")
        self.assertEqual(payment.interest_component, Decimal("2000.00"))

    def test_zero_rate_loan_accepts_no_interest(self):
        loan = self._loan(interest_rate=Decimal("0.00"))
        with self.assertRaises(ValidationError):
            self._pay(loan, datetime.date(2026, 3, 10), "1.00")
        self._pay(loan, datetime.date(2026, 3, 10), "0.00", principal="100.00")

    def test_annual_loan_accrues_once_per_anniversary(self):
        loan = self._loan(interest_period="annually", monthly_due_day=None,
                          lending_date=datetime.date(2025, 1, 10))
        self._pay(loan, datetime.date(2026, 1, 20), "2000.00")  # anniversary Jan 10 has passed
        with self.assertRaises(ValidationError):
            self._pay(loan, datetime.date(2026, 1, 21), "1.00")

    def test_reducing_loan_accrues_on_the_balance_owed(self):
        loan = self._loan(interest_basis="reducing")
        # Jan 15 (2000) and Feb 15 (2000) accrue on 100,000; the repayment on
        # Feb 10 leaves 50,000, so Mar 15 accrues 1000.  Total 5000.
        self._pay(loan, datetime.date(2026, 2, 10), "0.00", principal="50000.00")
        self._pay(loan, datetime.date(2026, 3, 10), "5000.00")
        with self.assertRaises(ValidationError):
            self._pay(loan, datetime.date(2026, 3, 11), "0.01")


class BorrowerEmailFormTests(TestCase):
    def _form(self, **data):
        values = {"full_name": "New Borrower", "email": "", "email_consent": ""}
        values.update(data)
        return BorrowerForm(data=values)

    def test_consent_without_an_email_address_is_rejected(self):
        form = self._form(email_consent="on")
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_consent_with_an_email_address_is_accepted(self):
        form = self._form(email="ravi@example.com", email_consent="on")
        self.assertTrue(form.is_valid(), form.errors)

    def test_blank_email_is_stored_as_none(self):
        form = self._form(email="   ")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["email"])

    def test_mobile_number_is_not_a_form_field(self):
        form = self._form(email="ravi@example.com")
        self.assertNotIn("mobile_number", form.fields)

    def test_invalid_email_address_is_rejected(self):
        form = self._form(email="not-an-address")
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
