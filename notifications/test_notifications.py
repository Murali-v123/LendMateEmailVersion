"""
Email notification records: creation, suppression rules, duplicate protection,
transaction-safe scheduling, and lender isolation in the history and retry views.
"""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import UserPreferences
from lending.models import Borrower, Loan, Payment
from lending.services import create_payment

from .models import EmailNotification
from .service import (
    _check_suppression,
    enqueue_due_today_reminder,
    enqueue_loan_closed,
    enqueue_loan_created,
    enqueue_overdue_reminder,
    enqueue_payment_received,
    enqueue_upcoming_reminder,
)
from .support import LendMateTestMixin

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CreationTests(LendMateTestMixin, TestCase):
    def test_loan_created_creates_a_pending_email_with_subject_and_recipient(self):
        record, created = enqueue_loan_created(self.loan)
        self.assertTrue(created)
        self.assertEqual(record.status, EmailNotification.PENDING)
        self.assertEqual(record.notification_type, EmailNotification.LOAN_CREATED)
        self.assertEqual(record.recipient_email, "ravi@example.com")
        self.assertIn("loan", record.subject.lower())
        self.assertIn("Ravi Kumar", record.message)

    def test_same_event_twice_creates_one_record(self):
        enqueue_loan_created(self.loan)
        _record, created = enqueue_loan_created(self.loan)
        self.assertFalse(created)
        self.assertEqual(EmailNotification.objects.filter(loan=self.loan).count(), 1)

    def test_payment_received_and_loan_closed_create_records(self):
        payment = create_payment(
            loan_pk=self.loan.pk,
            payment_date=datetime.date(2026, 2, 10),
            amount=Decimal("2000.00"),
            principal_component=Decimal("0.00"),
            interest_component=Decimal("2000.00"),
        )
        record, _ = enqueue_payment_received(payment)
        self.assertEqual(record.notification_type, EmailNotification.PAYMENT_RECEIVED)
        self.assertEqual(record.payment, payment)

        closed, _ = enqueue_loan_closed(self.loan)
        self.assertEqual(closed.notification_type, EmailNotification.LOAN_CLOSED)
        self.assertIn("closed", closed.subject.lower())

    def test_scheduling_happens_only_after_commit(self):
        with patch("notifications.service._schedule_task") as schedule:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                record, _ = enqueue_loan_created(self.loan)
            schedule.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            for callback in callbacks:
                callback()
        schedule.assert_called_once_with(record.pk)


class SuppressionTests(LendMateTestMixin, TestCase):
    def _reason(self, notification_type=EmailNotification.LOAN_CREATED):
        suppressed, reason = _check_suppression(self.borrower, self.lender, notification_type)
        return suppressed, reason

    def test_everything_on_and_consenting_is_not_suppressed(self):
        self.assertEqual(self._reason(), (False, ""))

    def test_master_switch_off_suppresses_everything(self):
        self.prefs.email_notifications_enabled = False
        self.prefs.save()
        suppressed, reason = self._reason()
        self.assertTrue(suppressed)
        self.assertIn("disabled", reason)

    def test_individual_switch_off_suppresses_only_that_type(self):
        self.prefs.email_loan_created = False
        self.prefs.save()
        self.assertTrue(self._reason(EmailNotification.LOAN_CREATED)[0])
        self.assertFalse(self._reason(EmailNotification.PAYMENT_RECEIVED)[0])

    def test_reminder_types_follow_their_own_switches(self):
        self.prefs.email_upcoming_reminders = False
        self.prefs.save()
        self.assertTrue(self._reason(EmailNotification.UPCOMING_DUE)[0])
        self.assertTrue(self._reason(EmailNotification.DUE_TODAY)[0])
        self.assertFalse(self._reason(EmailNotification.OVERDUE)[0])

    def test_no_consent_suppresses(self):
        self.borrower.email_consent = False
        self.borrower.save()
        suppressed, reason = self._reason()
        self.assertTrue(suppressed)
        self.assertIn("consent", reason)

    def test_no_email_address_suppresses(self):
        self.borrower.email = None
        self.borrower.save()
        suppressed, reason = self._reason()
        self.assertTrue(suppressed)
        self.assertIn("no email", reason)

    def test_invalid_email_address_suppresses(self):
        Borrower.objects.filter(pk=self.borrower.pk).update(email="broken@")
        self.borrower.refresh_from_db()
        suppressed, reason = self._reason()
        self.assertTrue(suppressed)
        self.assertIn("not valid", reason)

    def test_suppressed_loan_event_is_recorded_with_reason(self):
        self.prefs.email_notifications_enabled = False
        self.prefs.save()
        record, created = enqueue_loan_created(self.loan)
        self.assertTrue(created)
        self.assertEqual(record.status, EmailNotification.SUPPRESSED)
        self.assertEqual(record.recipient_email, "")
        self.assertIn("disabled", record.last_error)

    def test_borrower_without_lender_creates_nothing(self):
        orphan = Borrower.objects.create(
            lender=None, full_name="No Lender", email="x@example.com", email_consent=True,
        )
        loan = Loan.objects.create(
            borrower=orphan, principal=Decimal("500.00"), interest_rate=Decimal("1.00"),
            interest_period="annually", interest_basis="original",
            lending_date=datetime.date(2026, 1, 1), status="open",
        )
        self.assertEqual(enqueue_loan_created(loan), (None, False))


class ReminderStorageTests(LendMateTestMixin, TestCase):
    def test_suppressed_reminder_is_not_stored_and_is_not_lost(self):
        self.prefs.email_notifications_enabled = False
        self.prefs.save()
        record, created = enqueue_upcoming_reminder(
            self.loan, datetime.date(2026, 3, 15), Decimal("2000.00"), "2026-03",
        )
        self.assertIsNone(record)
        self.assertFalse(created)
        self.assertEqual(EmailNotification.objects.count(), 0)

        self.prefs.email_notifications_enabled = True
        self.prefs.save()
        record, created = enqueue_upcoming_reminder(
            self.loan, datetime.date(2026, 3, 15), Decimal("2000.00"), "2026-03",
        )
        self.assertTrue(created)
        self.assertEqual(record.status, EmailNotification.PENDING)

    def test_each_reminder_type_has_its_own_subject(self):
        upcoming, _ = enqueue_upcoming_reminder(self.loan, datetime.date(2026, 3, 15), Decimal("2000.00"), "2026-03")
        today, _ = enqueue_due_today_reminder(self.loan, datetime.date(2026, 3, 15), Decimal("2000.00"), "2026-03")
        overdue, _ = enqueue_overdue_reminder(self.loan, datetime.date(2026, 3, 15), Decimal("2000.00"), "overdue-2026-03")
        self.assertEqual(
            {upcoming.notification_type, today.notification_type, overdue.notification_type},
            {EmailNotification.UPCOMING_DUE, EmailNotification.DUE_TODAY, EmailNotification.OVERDUE},
        )
        self.assertEqual(len({upcoming.subject, today.subject, overdue.subject}), 3)
        self.assertIn("2,000.00", upcoming.message)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class LenderIsolationTests(LendMateTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.other = User.objects.create_user(username="other", password="pass-1234-xyz")
        UserPreferences.objects.create(user=self.other, email_notifications_enabled=True)
        other_borrower = Borrower.objects.create(
            lender=self.other, full_name="Someone Else", email="else@example.com", email_consent=True,
        )
        other_loan = Loan.objects.create(
            borrower=other_borrower, principal=Decimal("900.00"), interest_rate=Decimal("1.00"),
            interest_period="annually", interest_basis="original",
            lending_date=datetime.date(2026, 1, 1), status="open",
        )
        self.own_record, _ = enqueue_loan_created(self.loan)
        self.foreign_record, _ = enqueue_loan_created(other_loan)
        self.foreign_record.status = EmailNotification.FAILED
        self.foreign_record.save()

    def test_history_lists_only_the_lenders_own_notifications(self):
        self.client.force_login(self.lender)
        response = self.client.get(reverse("notifications:history"))
        ids = [n.pk for n in response.context["page_obj"]]
        self.assertIn(self.own_record.pk, ids)
        self.assertNotIn(self.foreign_record.pk, ids)

    def test_retry_is_refused_for_another_lenders_record(self):
        self.client.force_login(self.lender)
        response = self.client.post(reverse("notifications:retry", args=[self.foreign_record.pk]))
        self.assertEqual(response.status_code, 404)

    def test_retry_requeues_a_failed_record(self):
        self.own_record.status = EmailNotification.FAILED
        self.own_record.save()
        self.client.force_login(self.lender)
        with patch("notifications.tasks.send_email_notification.delay") as delay:
            self.client.post(reverse("notifications:retry", args=[self.own_record.pk]), follow=True)
        self.own_record.refresh_from_db()
        self.assertEqual(self.own_record.status, EmailNotification.PENDING)
        delay.assert_called_once_with(self.own_record.pk)
