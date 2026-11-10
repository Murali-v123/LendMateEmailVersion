"""
Reminder engine: upcoming, due-today and overdue emails for monthly and annual loans,
zero-interest loans, periods already paid, and amounts from the balance on the due date.
"""
import datetime
from decimal import Decimal

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from lending.models import Loan
from lending.services import create_payment

from .models import EmailNotification
from .support import LendMateTestMixin
from .tasks import (
    _one_year_before,
    send_overdue_reminders,
    send_upcoming_reminders,
)


def _today():
    return timezone.localtime(timezone.now()).date()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ReminderEngineTests(LendMateTestMixin, TestCase):
    def _loan(self, **overrides):
        values = dict(
            borrower=self.borrower,
            principal=Decimal("100000.00"),
            interest_rate=Decimal("2.00"),
            interest_period="monthly",
            interest_basis="original",
            lending_date=_today() - datetime.timedelta(days=120),
            monthly_due_day=(_today() + datetime.timedelta(days=2)).day,
            status="open",
        )
        values.update(overrides)
        return Loan.objects.create(**values)

    def _records(self, loan, kind):
        return EmailNotification.objects.filter(loan=loan, notification_type=kind)

    # --- upcoming and due today ---------------------------------------------

    def test_upcoming_reminder_carries_the_expected_interest(self):
        loan = self._loan()
        send_upcoming_reminders()
        record = self._records(loan, EmailNotification.UPCOMING_DUE).first()
        self.assertIsNotNone(record)
        self.assertIn("2,000.00", record.message)

    def test_due_today_gets_the_due_today_email_not_the_upcoming_one(self):
        loan = self._loan(monthly_due_day=_today().day)
        send_upcoming_reminders()
        self.assertEqual(self._records(loan, EmailNotification.DUE_TODAY).count(), 1)
        self.assertEqual(self._records(loan, EmailNotification.UPCOMING_DUE).count(), 0)

    def test_zero_interest_loan_gets_no_reminder(self):
        loan = self._loan(interest_rate=Decimal("0.00"))
        send_upcoming_reminders()
        self.assertEqual(EmailNotification.objects.filter(loan=loan).count(), 0)

    def test_period_already_paid_gets_no_reminder(self):
        loan = self._loan(monthly_due_day=_today().day)
        create_payment(
            loan_pk=loan.pk,
            payment_date=_today(),
            amount=Decimal("2000.00"),
            principal_component=Decimal("0.00"),
            interest_component=Decimal("2000.00"),
        )
        send_upcoming_reminders()
        self.assertEqual(EmailNotification.objects.filter(loan=loan).count(), 0)

    def test_annual_loan_is_reminded_on_its_anniversary(self):
        target = _today() + datetime.timedelta(days=settings.REMINDER_UPCOMING_DAYS - 1)
        loan = self._loan(
            interest_period="annually", monthly_due_day=None, lending_date=_one_year_before(target),
        )
        send_upcoming_reminders()
        record = self._records(loan, EmailNotification.UPCOMING_DUE).first()
        self.assertIsNotNone(record)
        self.assertIn("2,000.00", record.message)

    # --- overdue --------------------------------------------------------------

    def test_annual_loan_gets_an_overdue_email_on_the_day_after_its_anniversary(self):
        anniversary = _today() - datetime.timedelta(days=1)
        loan = self._loan(
            interest_period="annually", monthly_due_day=None, lending_date=_one_year_before(anniversary),
        )
        send_overdue_reminders()
        self.assertEqual(self._records(loan, EmailNotification.OVERDUE).count(), 1)

    def test_payment_in_the_annual_window_suppresses_the_overdue_email(self):
        anniversary = _today() - datetime.timedelta(days=1)
        loan = self._loan(
            interest_period="annually", monthly_due_day=None, lending_date=_one_year_before(anniversary),
        )
        create_payment(
            loan_pk=loan.pk,
            payment_date=_today(),
            amount=Decimal("2000.00"),
            principal_component=Decimal("0.00"),
            interest_component=Decimal("2000.00"),
        )
        send_overdue_reminders()
        self.assertEqual(self._records(loan, EmailNotification.OVERDUE).count(), 0)

    # --- switches --------------------------------------------------------------

    def test_upcoming_switch_off_stores_nothing_and_sends_once_turned_back_on(self):
        loan = self._loan()
        self.prefs.email_upcoming_reminders = False
        self.prefs.save()
        send_upcoming_reminders()
        self.assertEqual(self._records(loan, EmailNotification.UPCOMING_DUE).count(), 0)

        self.prefs.email_upcoming_reminders = True
        self.prefs.save()
        send_upcoming_reminders()
        self.assertEqual(self._records(loan, EmailNotification.UPCOMING_DUE).count(), 1)

    def test_running_the_reminders_twice_queues_each_email_once(self):
        loan = self._loan()
        send_upcoming_reminders()
        send_upcoming_reminders()
        self.assertEqual(self._records(loan, EmailNotification.UPCOMING_DUE).count(), 1)
