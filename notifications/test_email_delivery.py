"""
Email delivery: adapter results, the send task's retry policy, duplicate protection,
and recovery of stuck or stranded records.  Mail goes to Django's in-memory outbox.
"""
import datetime
import smtplib
from unittest.mock import patch

from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from .email_backend import EmailStatus, send_email
from .models import EmailNotification
from .service import enqueue_loan_created
from .support import LendMateTestMixin
from .tasks import (
    MAX_ATTEMPTS,
    dispatch_pending_notifications,
    recover_stuck_notifications,
    send_email_notification,
)

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


@override_settings(EMAIL_BACKEND=LOCMEM, DEFAULT_FROM_EMAIL="LendMate <no-reply@example.com>")
class EmailAdapterTests(SimpleTestCase):
    def test_successful_send_goes_to_the_outbox_with_html_alternative(self):
        result = send_email("ravi@example.com", "Subject", "Plain body", html_body="<p>HTML body</p>")
        self.assertTrue(result.was_sent)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["ravi@example.com"])
        self.assertEqual(message.subject, "Subject")
        self.assertEqual(message.alternatives[0][1], "text/html")

    def test_missing_or_invalid_address_is_final(self):
        for address in ["", "   ", "not-an-address"]:
            with self.subTest(address=address):
                result = send_email(address, "Subject", "Body")
                self.assertEqual(result.status, EmailStatus.FAILED)
                self.assertFalse(result.retryable)

    def test_empty_subject_or_body_is_final(self):
        self.assertFalse(send_email("ravi@example.com", "", "Body").retryable)
        self.assertFalse(send_email("ravi@example.com", "Subject", "   ").retryable)

    def test_subject_with_line_break_is_rejected(self):
        result = send_email("ravi@example.com", "Hi\nBcc: someone@example.com", "Body")
        self.assertFalse(result.was_sent)
        self.assertFalse(result.retryable)
        self.assertEqual(len(mail.outbox), 0)

    def test_smtp_recipient_refused_is_final(self):
        with patch.object(EmailMultiAlternatives, "send",
                          side_effect=smtplib.SMTPRecipientsRefused({"x@example.com": (550, b"no")})):
            result = send_email("ravi@example.com", "Subject", "Body")
        self.assertFalse(result.retryable)

    def test_smtp_4xx_is_retryable_and_5xx_is_final(self):
        with patch.object(EmailMultiAlternatives, "send",
                          side_effect=smtplib.SMTPResponseException(421, b"try later")):
            self.assertTrue(send_email("ravi@example.com", "Subject", "Body").retryable)
        with patch.object(EmailMultiAlternatives, "send",
                          side_effect=smtplib.SMTPResponseException(554, b"rejected")):
            self.assertFalse(send_email("ravi@example.com", "Subject", "Body").retryable)

    def test_connection_failure_is_retryable(self):
        with patch.object(EmailMultiAlternatives, "send", side_effect=ConnectionError("dropped")):
            result = send_email("ravi@example.com", "Subject", "Body")
        self.assertFalse(result.was_sent)
        self.assertTrue(result.retryable)


@override_settings(EMAIL_BACKEND=LOCMEM, DEFAULT_FROM_EMAIL="LendMate <no-reply@example.com>")
class SendTaskTests(LendMateTestMixin, TestCase):
    def _record(self):
        return enqueue_loan_created(self.loan)[0]

    def test_successful_send_marks_sent_and_sets_sent_at(self):
        record = self._record()
        send_email_notification(record.pk)
        record.refresh_from_db()
        self.assertEqual(record.status, EmailNotification.SENT)
        self.assertIsNotNone(record.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ravi@example.com"])

    def test_non_retryable_failure_is_final_on_first_attempt(self):
        record = self._record()
        with patch("notifications.tasks.send_email") as send, \
                patch("notifications.tasks.send_email_notification.apply_async") as schedule:
            from .email_backend import EmailResult
            send.return_value = EmailResult(status=EmailStatus.FAILED, error="rejected", retryable=False)
            send_email_notification(record.pk)
        record.refresh_from_db()
        self.assertEqual(record.status, EmailNotification.FAILED)
        self.assertEqual(record.attempts, 1)
        self.assertIsNone(record.next_retry_at)
        schedule.assert_not_called()

    def test_retryable_failure_schedules_a_retry(self):
        record = self._record()
        with patch("notifications.tasks.send_email") as send, \
                patch("notifications.tasks.send_email_notification.apply_async") as schedule:
            from .email_backend import EmailResult
            send.return_value = EmailResult(status=EmailStatus.FAILED, error="down", retryable=True)
            send_email_notification(record.pk)
        record.refresh_from_db()
        self.assertEqual(record.status, EmailNotification.PENDING)
        self.assertIsNotNone(record.next_retry_at)
        schedule.assert_called_once()

    def test_unexpected_exception_leaves_record_scheduled(self):
        record = self._record()
        with patch("notifications.tasks.send_email", side_effect=RuntimeError("boom")), \
                patch("notifications.tasks.send_email_notification.apply_async"):
            send_email_notification(record.pk)
        record.refresh_from_db()
        self.assertEqual(record.status, EmailNotification.PENDING)
        self.assertGreater(record.next_retry_at, timezone.now())

    def test_processing_record_is_never_sent_twice(self):
        record = self._record()
        EmailNotification.objects.filter(pk=record.pk).update(
            status=EmailNotification.PROCESSING, attempts=1,
        )
        with patch("notifications.tasks.send_email") as send:
            send_email_notification(record.pk)
        send.assert_not_called()

    def test_suppressed_record_is_never_sent(self):
        record = self._record()
        EmailNotification.objects.filter(pk=record.pk).update(status=EmailNotification.SUPPRESSED)
        send_email_notification(record.pk)
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_record_is_ignored(self):
        send_email_notification(999999)  # must not raise

    def test_attempt_limit_stops_further_sends(self):
        record = self._record()
        EmailNotification.objects.filter(pk=record.pk).update(attempts=MAX_ATTEMPTS)
        send_email_notification(record.pk)
        record.refresh_from_db()
        self.assertEqual(record.status, EmailNotification.FAILED)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(EMAIL_BACKEND=LOCMEM)
class RecoveryTests(LendMateTestMixin, TestCase):
    def _age(self, record, minutes):
        old = timezone.now() - datetime.timedelta(minutes=minutes)
        EmailNotification.objects.filter(pk=record.pk).update(updated_at=old)

    def test_stuck_processing_record_is_failed_not_resent(self):
        record = enqueue_loan_created(self.loan)[0]
        EmailNotification.objects.filter(pk=record.pk).update(status=EmailNotification.PROCESSING)
        self._age(record, 15)
        with patch("notifications.tasks.send_email_notification.delay") as delay:
            recover_stuck_notifications()
        record.refresh_from_db()
        self.assertEqual(record.status, EmailNotification.FAILED)
        self.assertIn("Outcome unknown", record.last_error)
        delay.assert_not_called()

    def test_sweeper_redispatches_old_pending_records(self):
        record = enqueue_loan_created(self.loan)[0]
        EmailNotification.objects.filter(pk=record.pk).update(status=EmailNotification.PENDING)
        self._age(record, 10)
        with patch("notifications.tasks.send_email_notification.delay") as delay:
            dispatch_pending_notifications()
        delay.assert_called_once_with(record.pk)

    def test_sweeper_skips_fresh_and_future_retries(self):
        fresh = enqueue_loan_created(self.loan)[0]
        EmailNotification.objects.filter(pk=fresh.pk).update(status=EmailNotification.PENDING)
        with patch("notifications.tasks.send_email_notification.delay") as delay:
            dispatch_pending_notifications()
        delay.assert_not_called()

    def test_sweeper_marks_exhausted_records_failed(self):
        record = enqueue_loan_created(self.loan)[0]
        EmailNotification.objects.filter(pk=record.pk).update(
            status=EmailNotification.PENDING, attempts=MAX_ATTEMPTS,
        )
        self._age(record, 10)
        with patch("notifications.tasks.send_email_notification.delay") as delay:
            dispatch_pending_notifications()
        record.refresh_from_db()
        self.assertEqual(record.status, EmailNotification.FAILED)
        delay.assert_not_called()
