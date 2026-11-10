"""
Celery tasks for LendMate email notifications.

Delivery is at-least-once with duplicate protection:
  - A record is claimed (PROCESSING) inside a row lock before the provider is called.
  - Only failures that cannot have delivered the email are retried automatically.
  - Stuck PROCESSING records are never re-sent automatically; an operator decides.
"""
import calendar
import datetime
import logging
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from lending.schedule import (  # noqa: E402
    anniversary as _anniversary,
    next_month_start as _next_month_start,
    one_year_before as _one_year_before,
    period_start as _period_start,
)

from django.conf import settings

from .email_backend import send_email
from .models import EmailNotification

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = [60, 300, 900, 3600, 7200]  # 1m, 5m, 15m, 1h, 2h
STUCK_THRESHOLD_MINUTES = 10
SWEEP_GRACE_MINUTES = 2  # leave freshly queued records to their own task
# Grace period for annual loans: a payment up to this many days after an anniversary
# still counts toward that year's interest.  Separate from the configurable reminder
# settings, which control when emails are sent.
ANNUAL_GRACE_DAYS = 30


def _backoff_for(attempts):
    """Seconds to wait before the next retry, given how many attempts have been made."""
    index = min(max(attempts, 1) - 1, len(RETRY_BACKOFF_SECONDS) - 1)
    return RETRY_BACKOFF_SECONDS[index]


@shared_task(
    bind=True,
    ignore_result=True,
    name="notifications.tasks.send_email_notification",
    autoretry_for=(),
    acks_late=True,
)
def send_email_notification(self, notification_id):
    """Deliver one EmailNotification, updating its status and retry schedule."""
    now = timezone.now()

    try:
        with transaction.atomic():
            try:
                notification = (
                    EmailNotification.objects.select_for_update(skip_locked=True).get(pk=notification_id)
                )
            except EmailNotification.DoesNotExist:
                logger.warning("Notification %s not found or locked elsewhere, skipping.", notification_id)
                return

            if notification.status in (EmailNotification.SENT, EmailNotification.SUPPRESSED):
                logger.info("Notification %s already %s, skipping.", notification_id, notification.status)
                return

            # Another worker is already sending this record.  Stuck records are handled
            # by recover_stuck_notifications, never by a second send.
            if notification.status == EmailNotification.PROCESSING:
                logger.info("Notification %s is already being processed, skipping.", notification_id)
                return

            # A borrower in the recycle bin must not receive mail, including mail queued earlier.
            if notification.borrower is not None and notification.borrower.deleted_at is not None:
                notification.status = EmailNotification.SUPPRESSED
                notification.last_error = "Borrower is in the recycle bin."
                notification.save(update_fields=["status", "last_error", "updated_at"])
                logger.info("Notification %s suppressed: borrower is in the recycle bin.", notification_id)
                return

            if notification.attempts >= MAX_ATTEMPTS:
                notification.status = EmailNotification.FAILED
                notification.last_error = "Maximum send attempts reached."
                notification.save(update_fields=["status", "last_error", "updated_at"])
                logger.error("Notification %s exceeded max attempts.", notification_id)
                return

            notification.status = EmailNotification.PROCESSING
            notification.attempts += 1
            notification.save(update_fields=["status", "attempts", "updated_at"])

        result = send_email(
            notification.recipient_email,
            notification.subject,
            notification.message,
            html_body=notification.html_message or None,
        )

        if result.was_sent:
            notification.status = EmailNotification.SENT
            notification.sent_at = now
            notification.next_retry_at = None
            notification.last_error = ""
            logger.info("Notification %s accepted by the email backend.", notification_id)

        elif not result.retryable:
            # Rejected or invalid: retrying cannot succeed.  Stays FAILED until an operator retries.
            notification.status = EmailNotification.FAILED
            notification.next_retry_at = None
            notification.last_error = (result.error or "")[:500]
            logger.error("Notification %s failed without retry. Error: %s", notification_id, result.error)

        elif notification.attempts >= MAX_ATTEMPTS:
            notification.status = EmailNotification.FAILED
            notification.next_retry_at = None
            notification.last_error = (result.error or "")[:500]
            logger.error("Notification %s permanently failed after %d attempts.", notification_id, notification.attempts)

        else:
            backoff = _backoff_for(notification.attempts)
            notification.status = EmailNotification.PENDING
            notification.next_retry_at = timezone.now() + datetime.timedelta(seconds=backoff)
            notification.last_error = (result.error or "")[:500]
            logger.warning(
                "Notification %s failed (attempt %d/%d). Retry in %ds. Error: %s",
                notification_id, notification.attempts, MAX_ATTEMPTS, backoff, result.error,
            )
            notification.save(update_fields=["status", "next_retry_at", "last_error", "updated_at"])
            send_email_notification.apply_async(args=[notification_id], countdown=backoff)
            return

        notification.save(update_fields=["status", "sent_at", "next_retry_at", "last_error", "updated_at"])

    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error processing notification %s", notification_id)
        current = EmailNotification.objects.filter(pk=notification_id).values("attempts").first()
        attempts = current["attempts"] if current else MAX_ATTEMPTS
        if attempts >= MAX_ATTEMPTS:
            EmailNotification.objects.filter(pk=notification_id).update(
                status=EmailNotification.FAILED, next_retry_at=None, last_error=str(exc)[:500],
            )
        else:
            EmailNotification.objects.filter(pk=notification_id).update(
                status=EmailNotification.PENDING,
                next_retry_at=timezone.now() + datetime.timedelta(seconds=_backoff_for(attempts)),
                last_error=str(exc)[:500],
            )


# ---------------------------------------------------------------------------
# Scheduled reminders: upcoming, due today and overdue
# ---------------------------------------------------------------------------
#
# Monthly loans fall due on monthly_due_day; annual loans on the anniversary of
# the lending date.  Each due date gets an upcoming email settings.REMINDER_UPCOMING_DAYS
# ahead, a due-today email on the day, and overdue emails for the
# settings.REMINDER_OVERDUE_LOOKBACK_DAYS after it.  The amount is the interest expected for that
# period.  Zero-interest loans and periods already paid get no email.


@shared_task(ignore_result=True, name="notifications.tasks.send_upcoming_reminders")
def send_upcoming_reminders():
    """
    Queue upcoming reminders for due dates within settings.REMINDER_UPCOMING_DAYS,
    and due-today reminders on the due date itself.  Each one also produces a
    lender copy, sent regardless of borrower consent.
    """
    from .models import EmailNotification  # noqa: PLC0415
    from .service import (  # noqa: PLC0415
        enqueue_due_today_reminder,
        enqueue_lender_alert,
        enqueue_upcoming_reminder,
    )

    today = timezone.localtime(timezone.now()).date()
    horizon = today + datetime.timedelta(days=settings.REMINDER_UPCOMING_DAYS)

    queued = 0
    for loan in _scheduled_loans():
        try:
            for due_date in _due_dates_in_range(loan, today, horizon):
                if _reminder_not_needed(loan, due_date):
                    continue
                amount = loan.expected_interest_as_of(_period_start(loan, due_date))
                if amount <= Decimal("0.00"):
                    continue

                period_key = _period_key(loan, due_date)
                if due_date == today:
                    enqueue, lender_type = enqueue_due_today_reminder, EmailNotification.DUE_TODAY
                else:
                    enqueue, lender_type = enqueue_upcoming_reminder, EmailNotification.UPCOMING_DUE

                _record, created = enqueue(loan, due_date, amount, period_key)
                if created:
                    queued += 1
                enqueue_lender_alert(
                    lender_type, loan, due_date=due_date, amount=amount, period_key=period_key,
                )
        except Exception:  # noqa: BLE001
            logger.exception("Error generating upcoming reminder for loan %s", loan.pk)

    logger.info("send_upcoming_reminders: %d new borrower reminder(s) queued.", queued)


@shared_task(ignore_result=True, name="notifications.tasks.send_overdue_reminders")
def send_overdue_reminders():
    """
    Queue overdue reminders for due dates that have passed without a payment.

    The first reminder goes out on the day after the due date.  After that, one
    goes out every settings.REMINDER_OVERDUE_REPEAT_DAYS days, until the period is
    paid or settings.REMINDER_OVERDUE_LOOKBACK_DAYS have passed.  A repeat setting
    of 0 sends a single reminder.  Each send day has its own event key, so a rerun
    on the same day never duplicates an email.
    """
    from .models import EmailNotification  # noqa: PLC0415
    from .service import enqueue_lender_alert, enqueue_overdue_reminder  # noqa: PLC0415

    today = timezone.localtime(timezone.now()).date()
    lookback = settings.REMINDER_OVERDUE_LOOKBACK_DAYS
    repeat = settings.REMINDER_OVERDUE_REPEAT_DAYS

    queued = 0
    for loan in _scheduled_loans():
        try:
            for due_date in _due_dates_in_range(loan, today - datetime.timedelta(days=lookback),
                                                today - datetime.timedelta(days=1)):
                if _reminder_not_needed(loan, due_date):
                    continue

                days_overdue = (today - due_date).days
                if repeat == 0:
                    if days_overdue != 1:
                        continue
                elif (days_overdue - 1) % repeat != 0:
                    continue

                amount = loan.expected_interest_as_of(_period_start(loan, due_date))
                if amount <= Decimal("0.00"):
                    continue

                period_key = f"{_overdue_period_key(loan, due_date)}-{today.isoformat()}"
                _record, created = enqueue_overdue_reminder(loan, due_date, amount, period_key)
                if created:
                    queued += 1
                enqueue_lender_alert(
                    EmailNotification.OVERDUE, loan,
                    due_date=due_date, amount=amount, period_key=period_key,
                )
        except Exception:  # noqa: BLE001
            logger.exception("Error generating overdue reminder for loan %s", loan.pk)

    logger.info("send_overdue_reminders: %d new borrower reminder(s) queued.", queued)


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

@shared_task(ignore_result=True, name="notifications.tasks.recover_stuck_notifications")
def recover_stuck_notifications():
    """
    Resolve PROCESSING emails stuck for longer than STUCK_THRESHOLD_MINUTES.

    The worker may have died after the email was handed to the mail server, so a
    re-send could duplicate it.  Records are therefore marked FAILED with an
    explanation, and an operator can retry them from the notification history.
    """
    cutoff = timezone.now() - datetime.timedelta(minutes=STUCK_THRESHOLD_MINUTES)

    resolved = EmailNotification.objects.filter(
        status=EmailNotification.PROCESSING,
        updated_at__lte=cutoff,
    ).update(
        status=EmailNotification.FAILED,
        next_retry_at=None,
        last_error=(
            "Outcome unknown after a worker interruption. "
            "Check the mailbox or mail provider before retrying manually."
        ),
    )

    if resolved:
        logger.warning("recover_stuck_notifications: resolved %d stuck notification(s).", resolved)


@shared_task(ignore_result=True, name="notifications.tasks.dispatch_pending_notifications")
def dispatch_pending_notifications(batch_size=500):
    """
    Re-dispatch PENDING emails that no task is handling.

    A record stays PENDING if the broker was down when it was queued, or after an
    unexpected error.  Records updated within SWEEP_GRACE_MINUTES are left alone so
    their own task runs first.  Records with no attempts left are marked FAILED.
    """
    now = timezone.now()
    stale_before = now - datetime.timedelta(minutes=SWEEP_GRACE_MINUTES)

    exhausted = EmailNotification.objects.filter(
        status=EmailNotification.PENDING,
        attempts__gte=MAX_ATTEMPTS,
    ).update(
        status=EmailNotification.FAILED,
        next_retry_at=None,
        last_error="Maximum send attempts reached.",
    )

    due_ids = list(
        EmailNotification.objects.filter(
            status=EmailNotification.PENDING,
            attempts__lt=MAX_ATTEMPTS,
            updated_at__lte=stale_before,
        )
        .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
        .values_list("pk", flat=True)[:batch_size]
    )

    for pk in due_ids:
        send_email_notification.delay(pk)

    if due_ids or exhausted:
        logger.info(
            "dispatch_pending_notifications: re-dispatched %d, marked %d exhausted.",
            len(due_ids), exhausted,
        )


# ---------------------------------------------------------------------------
# Schedule helpers (shared rules live in lending/schedule.py)
# ---------------------------------------------------------------------------

def _scheduled_loans():
    """Open loans that have a recurring interest schedule."""
    from lending.models import Loan  # noqa: PLC0415

    return (
        Loan.objects
        .filter(status="open")
        .filter(
            Q(interest_period="annually", lending_date__isnull=False)
            | Q(interest_period="monthly", monthly_due_day__isnull=False)
        )
        .select_related("borrower", "borrower__lender", "borrower__lender__preferences")
        # One payments query per run.  The paid checks and expected amounts read this cache.
        .prefetch_related("payments")
    )


def _due_dates_in_range(loan, start, end):
    """Interest due dates for this loan that fall within [start, end]."""
    if loan.interest_period == "monthly":
        return list(_month_due_dates_in_range(loan, start, end))

    dates = []
    for year in range(start.year - 1, end.year + 1):
        anniversary = _anniversary(loan.lending_date, year)
        if anniversary > loan.lending_date and start <= anniversary <= end:
            dates.append(anniversary)
    return dates


def _reminder_not_needed(loan, due_date):
    """True when no reminder should be sent for this due date."""
    if not loan.borrower or not loan.borrower.lender:
        return True
    if loan.lending_date and due_date < loan.lending_date:
        return True
    return _period_paid(loan, due_date)


def _period_paid(loan, due_date):
    """
    True when an active payment already covers the interest for this due date.

    Monthly: any payment dated in the due date's calendar month.
    Annual: any payment in the window that runs from 30 days after the previous
    anniversary to 30 days after this one.  Consecutive windows never overlap,
    so one payment can't satisfy two periods.

    Works from the prefetched payments list, so it costs no extra queries.
    """
    dates = [p.payment_date for p in loan.payments.all() if not p.is_voided]
    if loan.interest_period == "monthly":
        period_start = due_date.replace(day=1)
        period_end = _next_month_start(due_date)
        return any(period_start <= d < period_end for d in dates)

    window_start, window_end = _annual_window(due_date)
    return any(window_start < d <= window_end for d in dates)


def _period_key(loan, due_date):
    if loan.interest_period == "monthly":
        return f"{due_date.year}-{due_date.month:02d}"
    return f"annual-{due_date.isoformat()}"


def _overdue_period_key(loan, due_date):
    if loan.interest_period == "monthly":
        return f"overdue-{due_date.year}-{due_date.month:02d}"
    return f"overdue-annual-{due_date.isoformat()}"


def _annual_window(due_date):
    """(exclusive start, inclusive end) of the payment window for an annual due date."""
    return (
        _one_year_before(due_date) + datetime.timedelta(days=ANNUAL_GRACE_DAYS),
        due_date + datetime.timedelta(days=ANNUAL_GRACE_DAYS),
    )


def _month_due_dates_in_range(loan, start, end):
    """
    Yield the due date for each month in [start, end] for this loan.
    Clamps the due day to the last day of the month.
    """
    due_day = loan.monthly_due_day
    cur = start.replace(day=1)
    while cur <= end:
        max_day = calendar.monthrange(cur.year, cur.month)[1]
        actual_day = min(due_day, max_day)
        due_date = datetime.date(cur.year, cur.month, actual_day)
        if start <= due_date <= end:
            yield due_date
        cur = _next_month_start(cur)
