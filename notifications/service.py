"""
Creates email notification records for LendMate events.

Each public enqueue function:
  1. Checks the lender's preferences, the borrower's consent and address.
  2. Creates one EmailNotification record (or a SUPPRESSED record with the reason).
  3. Schedules delivery after the surrounding transaction commits.

Reminders that are suppressed by settings are NOT stored, so the same reminder can
still go out once the lender turns emails on or the borrower gives consent.
"""
import logging

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import validate_email
from django.db import transaction

from .models import EmailNotification
from .templates_email import (
    build_borrower_due_email,
    build_lender_alert_email,
    build_loan_closed_email,
    build_loan_created_email,
    build_payment_received_email,
)

logger = logging.getLogger(__name__)


def _get_preferences(lender):
    """
    Return the lender's UserPreferences, or None if they have never saved any.

    Only the missing-row case is handled here.  Any other error (for example a
    schema mismatch) must propagate: swallowing it silently disables email for
    every lender.
    """
    try:
        return lender.preferences
    except ObjectDoesNotExist:
        return None


# Which preference switch controls each email type.
_CATEGORY_FIELDS = {
    EmailNotification.LOAN_CREATED: "email_loan_created",
    EmailNotification.PAYMENT_RECEIVED: "email_payment_received",
    EmailNotification.LOAN_CLOSED: "email_loan_closed",
    EmailNotification.UPCOMING_DUE: "email_upcoming_reminders",
    EmailNotification.DUE_TODAY: "email_upcoming_reminders",
    EmailNotification.OVERDUE: "email_overdue_reminders",
}


def _check_suppression(borrower, lender, notification_type):
    """Return (suppressed: bool, reason: str) for one email."""
    if lender is None:
        return True, "Borrower has no lender on record."

    preferences = _get_preferences(lender)

    if not getattr(preferences, "email_notifications_enabled", False):
        return True, "Email notifications are disabled in lender settings."

    if not getattr(preferences, _CATEGORY_FIELDS[notification_type], False):
        return True, "This email type is turned off in lender settings."

    if not borrower.email_consent:
        return True, "Borrower has not consented to email notifications."

    address = (borrower.email or "").strip()
    if not address:
        return True, "Borrower has no email address on file."

    try:
        validate_email(address)
    except ValidationError:
        return True, "Borrower email address is not valid."

    return False, ""


def _schedule_task(notification_id):
    """Dispatch delivery.  A broker outage must not break the request that created the record."""
    from .tasks import send_email_notification  # noqa: PLC0415

    try:
        send_email_notification.delay(notification_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Could not dispatch email task for notification %s (Celery may be unavailable).",
            notification_id,
        )


def _create_notification(*, notification_type, event_key, borrower, lender,
                         loan=None, payment=None, content=None, suppress=False, reason="",
                         recipient_email=None, recipient_role=EmailNotification.RECIPIENT_BORROWER):
    """Persist one EmailNotification.  Returns (record, created)."""
    if lender is None:
        # The table requires a lender.  A borrower without one cannot receive email.
        logger.warning("Skipping %s email: borrower %s has no lender.", notification_type, borrower.pk)
        return None, False

    values = {
        "borrower": borrower,
        "loan": loan,
        "payment": payment,
        "lender": lender,
        "notification_type": notification_type,
        "recipient_email": "" if suppress else (recipient_email or borrower.email or "").strip(),
        "recipient_role": recipient_role,
        "subject": content["subject"] if content else "",
        "message": content["text"] if content else "",
        "html_message": content["html"] if content else "",
        "status": EmailNotification.SUPPRESSED if suppress else EmailNotification.PENDING,
        "last_error": reason,
    }

    record, created = EmailNotification.objects.get_or_create(event_key=event_key, defaults=values)

    if created and not suppress:
        transaction.on_commit(lambda: _schedule_task(record.pk))

    return record, created


def _event_key(notification_type, borrower, loan_id=None, payment_id=None, period_key=""):
    return EmailNotification.make_event_key(
        notification_type,
        loan_id=loan_id,
        payment_id=payment_id,
        period_key=period_key,
        recipient_email=borrower.email or "",
        recipient_role=EmailNotification.RECIPIENT_BORROWER,
    )


def enqueue_loan_created(loan):
    borrower = loan.borrower
    suppress, reason = _check_suppression(borrower, borrower.lender, EmailNotification.LOAN_CREATED)
    return _create_notification(
        notification_type=EmailNotification.LOAN_CREATED,
        event_key=_event_key(EmailNotification.LOAN_CREATED, borrower, loan_id=loan.pk),
        borrower=borrower,
        lender=borrower.lender,
        loan=loan,
        content=None if suppress else build_loan_created_email(loan),
        suppress=suppress,
        reason=reason,
    )


def enqueue_payment_received(payment):
    loan = payment.loan
    borrower = loan.borrower
    suppress, reason = _check_suppression(borrower, borrower.lender, EmailNotification.PAYMENT_RECEIVED)
    return _create_notification(
        notification_type=EmailNotification.PAYMENT_RECEIVED,
        event_key=_event_key(
            EmailNotification.PAYMENT_RECEIVED, borrower,
            loan_id=loan.pk, payment_id=payment.pk,
        ),
        borrower=borrower,
        lender=borrower.lender,
        loan=loan,
        payment=payment,
        content=None if suppress else build_payment_received_email(payment),
        suppress=suppress,
        reason=reason,
    )


def enqueue_loan_closed(loan):
    borrower = loan.borrower
    suppress, reason = _check_suppression(borrower, borrower.lender, EmailNotification.LOAN_CLOSED)
    return _create_notification(
        notification_type=EmailNotification.LOAN_CLOSED,
        event_key=_event_key(EmailNotification.LOAN_CLOSED, borrower, loan_id=loan.pk),
        borrower=borrower,
        lender=borrower.lender,
        loan=loan,
        content=None if suppress else build_loan_closed_email(loan),
        suppress=suppress,
        reason=reason,
    )


def _enqueue_due_reminder(loan, due_date, amount, period_key, notification_type, reminder_type):
    """
    Shared path for upcoming, due-today and overdue reminders.

    Returns (None, False) when suppressed.  Suppressed reminders are not stored,
    so they can still be sent once the lender turns emails on.
    """
    borrower = loan.borrower
    suppress, reason = _check_suppression(borrower, borrower.lender, notification_type)
    if suppress:
        logger.info("%s reminder for loan %s not queued: %s", reminder_type, loan.pk, reason)
        return None, False

    return _create_notification(
        notification_type=notification_type,
        event_key=_event_key(notification_type, borrower, loan_id=loan.pk, period_key=period_key),
        borrower=borrower,
        lender=borrower.lender,
        loan=loan,
        content=build_borrower_due_email(loan, due_date, amount, reminder_type=reminder_type),
    )


def enqueue_upcoming_reminder(loan, due_date, amount, period_key):
    return _enqueue_due_reminder(
        loan, due_date, amount, period_key,
        EmailNotification.UPCOMING_DUE, "upcoming",
    )


def enqueue_due_today_reminder(loan, due_date, amount, period_key):
    return _enqueue_due_reminder(
        loan, due_date, amount, period_key,
        EmailNotification.DUE_TODAY, "due_today",
    )


def enqueue_overdue_reminder(loan, due_date, amount, period_key):
    return _enqueue_due_reminder(
        loan, due_date, amount, period_key,
        EmailNotification.OVERDUE, "overdue",
    )


# ---------------------------------------------------------------------------
# Lender alerts
# ---------------------------------------------------------------------------
#
# Lenders receive their own copy of the events they care about.  These emails
# depend only on the lender's own alert switch and address, not on borrower
# consent, so they still go out when the borrower has opted out.

# Maps a notification type to the event name build_lender_alert_email expects.
_LENDER_EVENT_NAMES = {
    EmailNotification.LOAN_CREATED: "loan_created",
    EmailNotification.PAYMENT_RECEIVED: "payment_received",
    EmailNotification.UPCOMING_DUE: "upcoming",
    EmailNotification.DUE_TODAY: "due_today",
    EmailNotification.OVERDUE: "overdue",
}


def _lender_alert_suppression(lender):
    if lender is None:
        return True, "Loan has no lender on record."

    preferences = _get_preferences(lender)
    if not getattr(preferences, "email_lender_alerts", False):
        return True, "Lender alerts are turned off in settings."

    address = (lender.email or "").strip()
    if not address:
        return True, "Lender account has no email address."

    try:
        validate_email(address)
    except ValidationError:
        return True, "Lender email address is not valid."

    return False, ""


def enqueue_lender_alert(notification_type, loan, payment=None, due_date=None, amount=None, period_key=""):
    """Queue one email to the loan's lender.  Returns (record, created), or (None, False) if suppressed."""
    borrower = loan.borrower
    lender = borrower.lender

    suppress, reason = _lender_alert_suppression(lender)
    if suppress:
        logger.info("Lender alert %s for loan %s not queued: %s", notification_type, loan.pk, reason)
        return None, False

    content = build_lender_alert_email(
        lender,
        borrower,
        loan,
        _LENDER_EVENT_NAMES[notification_type],
        payment=payment,
        due_date=due_date,
        amount=amount,
    )

    key = EmailNotification.make_event_key(
        notification_type,
        loan_id=loan.pk,
        payment_id=payment.pk if payment else None,
        period_key=period_key,
        recipient_email=lender.email,
        recipient_role=EmailNotification.RECIPIENT_LENDER,
    )

    return _create_notification(
        notification_type=notification_type,
        event_key=key,
        borrower=borrower,
        lender=lender,
        loan=loan,
        payment=payment,
        content=content,
        recipient_email=lender.email,
        recipient_role=EmailNotification.RECIPIENT_LENDER,
    )
