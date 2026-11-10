"""
Lender alert emails, configurable reminder timing, overdue repeats, and the
parsing of the reminder time settings.
"""
import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.utils import timezone

from config.settings import _parse_hhmm
from lending.models import Loan

from .models import EmailNotification
from .service import enqueue_lender_alert, enqueue_loan_created
from .support import LendMateTestMixin
from .tasks import _one_year_before, send_overdue_reminders, send_upcoming_reminders

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


def _today():
    return timezone.localtime(timezone.now()).date()


class LenderMixin(LendMateTestMixin):
    def setUp(self):
        super().setUp()
        self.lender.email = "lender@example.com"
        self.lender.save()


@override_settings(EMAIL_BACKEND=LOCMEM)
class LenderAlertTests(LenderMixin, TestCase):
    def _lender_records(self, notification_type=None):
        qs = EmailNotification.objects.filter(
            loan=self.loan, recipient_role=EmailNotification.RECIPIENT_LENDER,
        )
        return qs.filter(notification_type=notification_type) if notification_type else qs

    def test_loan_created_lender_copy_goes_to_the_lender(self):
        record, created = enqueue_lender_alert(EmailNotification.LOAN_CREATED, self.loan)
        self.assertTrue(created)
        self.assertEqual(record.recipient_email, "lender@example.com")
        self.assertEqual(record.recipient_role, EmailNotification.RECIPIENT_LENDER)
        self.assertIn("New loan", record.subject)
        self.assertIn("Ravi Kumar", record.message)

    def test_lender_copy_is_sent_even_when_the_borrower_has_not_consented(self):
        self.borrower.email_consent = False
        self.borrower.save()
        record, created = enqueue_lender_alert(EmailNotification.LOAN_CREATED, self.loan)
        self.assertTrue(created)
        self.assertEqual(record.status, EmailNotification.PENDING)

    def test_lender_and_borrower_copies_are_separate_records(self):
        enqueue_loan_created(self.loan)
        enqueue_lender_alert(EmailNotification.LOAN_CREATED, self.loan)
        roles = sorted(EmailNotification.objects.filter(loan=self.loan).values_list("recipient_role", flat=True))
        self.assertEqual(roles, ["borrower", "lender"])

    def test_turning_lender_alerts_off_creates_nothing(self):
        self.prefs.email_lender_alerts = False
        self.prefs.save()
        self.assertEqual(enqueue_lender_alert(EmailNotification.LOAN_CREATED, self.loan), (None, False))
        self.assertEqual(self._lender_records().count(), 0)

    def test_lender_without_an_email_address_creates_nothing(self):
        self.lender.email = ""
        self.lender.save()
        self.assertEqual(enqueue_lender_alert(EmailNotification.LOAN_CREATED, self.loan), (None, False))

    def test_upcoming_reminder_also_produces_a_lender_copy_once(self):
        target = _today() + datetime.timedelta(days=2)
        self.loan.monthly_due_day = target.day
        self.loan.lending_date = _today() - datetime.timedelta(days=120)
        self.loan.save()

        send_upcoming_reminders()
        send_upcoming_reminders()  # a second run on the same day must not duplicate

        self.assertEqual(self._lender_records(EmailNotification.UPCOMING_DUE).count(), 1)
        self.assertEqual(
            EmailNotification.objects.filter(
                loan=self.loan, notification_type=EmailNotification.UPCOMING_DUE,
                recipient_role=EmailNotification.RECIPIENT_BORROWER,
            ).count(),
            1,
        )

    def test_overdue_reminder_produces_a_lender_copy(self):
        yesterday = _today() - datetime.timedelta(days=1)
        self.loan.monthly_due_day = yesterday.day
        self.loan.lending_date = _today() - datetime.timedelta(days=120)
        self.loan.save()
        send_overdue_reminders()
        self.assertEqual(self._lender_records(EmailNotification.OVERDUE).count(), 1)


@override_settings(EMAIL_BACKEND=LOCMEM)
class ConfigurableScheduleTests(LenderMixin, TestCase):
    def _annual_loan_due_on(self, due_date):
        loan = Loan.objects.create(
            borrower=self.borrower,
            principal=Decimal("100000.00"),
            interest_rate=Decimal("2.00"),
            interest_period="annually",
            interest_basis="original",
            lending_date=_one_year_before(due_date),
            status="open",
        )
        return loan

    def _records(self, loan, notification_type):
        return EmailNotification.objects.filter(
            loan=loan, notification_type=notification_type,
            recipient_role=EmailNotification.RECIPIENT_BORROWER,
        )

    @override_settings(REMINDER_UPCOMING_DAYS=10)
    def test_longer_upcoming_window_sends_earlier(self):
        loan = self._annual_loan_due_on(_today() + datetime.timedelta(days=8))
        send_upcoming_reminders()
        self.assertEqual(self._records(loan, EmailNotification.UPCOMING_DUE).count(), 1)

    @override_settings(REMINDER_UPCOMING_DAYS=5)
    def test_shorter_upcoming_window_does_not_send_yet(self):
        loan = self._annual_loan_due_on(_today() + datetime.timedelta(days=8))
        send_upcoming_reminders()
        self.assertEqual(self._records(loan, EmailNotification.UPCOMING_DUE).count(), 0)

    @override_settings(REMINDER_OVERDUE_REPEAT_DAYS=7, REMINDER_OVERDUE_LOOKBACK_DAYS=30)
    def test_overdue_repeats_on_day_one_then_every_seven_days(self):
        first = self._annual_loan_due_on(_today() - datetime.timedelta(days=1))
        eighth = self._annual_loan_due_on(_today() - datetime.timedelta(days=8))
        between = self._annual_loan_due_on(_today() - datetime.timedelta(days=3))
        send_overdue_reminders()
        self.assertEqual(self._records(first, EmailNotification.OVERDUE).count(), 1)
        self.assertEqual(self._records(eighth, EmailNotification.OVERDUE).count(), 1)
        self.assertEqual(self._records(between, EmailNotification.OVERDUE).count(), 0)

    @override_settings(REMINDER_OVERDUE_REPEAT_DAYS=0, REMINDER_OVERDUE_LOOKBACK_DAYS=30)
    def test_zero_repeat_sends_only_the_first_overdue_reminder(self):
        first = self._annual_loan_due_on(_today() - datetime.timedelta(days=1))
        later = self._annual_loan_due_on(_today() - datetime.timedelta(days=8))
        send_overdue_reminders()
        self.assertEqual(self._records(first, EmailNotification.OVERDUE).count(), 1)
        self.assertEqual(self._records(later, EmailNotification.OVERDUE).count(), 0)

    @override_settings(REMINDER_OVERDUE_REPEAT_DAYS=7, REMINDER_OVERDUE_LOOKBACK_DAYS=3)
    def test_lookback_stops_overdue_reminders(self):
        # Due 5 days ago with a 3-day lookback: outside the window, so no reminder.
        loan = self._annual_loan_due_on(_today() - datetime.timedelta(days=5))
        send_overdue_reminders()
        self.assertEqual(self._records(loan, EmailNotification.OVERDUE).count(), 0)

    def test_default_beat_times_come_from_settings(self):
        upcoming = settings.CELERY_BEAT_SCHEDULE["upcoming-reminders"]["schedule"]
        overdue = settings.CELERY_BEAT_SCHEDULE["overdue-reminders"]["schedule"]
        self.assertEqual(set(upcoming.hour), {9})
        self.assertEqual(set(overdue.hour), {10})


class TimeSettingParsingTests(TestCase):
    def test_valid_times_are_parsed(self):
        self.assertEqual(_parse_hhmm("09:00", "X"), (9, 0))
        self.assertEqual(_parse_hhmm("18:45", "X"), (18, 45))

    def test_invalid_times_are_rejected_with_the_setting_name(self):
        for value in ["25:00", "09:60", "nine", "", "9"]:
            with self.subTest(value=value):
                with self.assertRaises(ImproperlyConfigured) as ctx:
                    _parse_hhmm(value, "REMINDER_UPCOMING_TIME")
                self.assertIn("REMINDER_UPCOMING_TIME", str(ctx.exception))
