"""
lending/services.py — Centralised financial ledger service.

All financial operations (create/edit/void payments, edit loans, calculate
balances) MUST go through this module so that:

  - Database transactions are always atomic.
  - select_for_update() prevents race conditions on concurrent payments.
  - Overpayment validation is always applied.
  - Audit events are always recorded.
  - Voided payments are never counted in any balance.

Views should call service functions; they must NOT duplicate these calculations.
"""
import json
import logging
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AuditEvent, Borrower, Loan, Payment

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Lock helper
# ---------------------------------------------------------------------------

def lock_loan(loan_id):
    """
    Lock the Loan row for update within the current transaction.
    Must be called inside a transaction.atomic() block.
    Returns the locked Loan instance.
    Raises Loan.DoesNotExist if not found.
    """
    return Loan.objects.select_for_update().get(pk=loan_id)


# ---------------------------------------------------------------------------
# Balance helpers
# ---------------------------------------------------------------------------

def get_principal_repaid(loan):
    """Sum of principal components from active (non-voided) payments."""
    from django.db.models import Sum
    return loan.payments.active().aggregate(
        total=Sum("principal_component")
    )["total"] or Decimal("0.00")


def get_outstanding_principal(loan):
    return loan.principal - get_principal_repaid(loan)


def validate_payment_date(loan, payment_date):
    """
    Raise ValidationError if payment_date is in the future or earlier than the loan's lending date.
    """
    if not payment_date:
        raise ValidationError("Payment date is required.")
    today = timezone.localtime(timezone.now()).date() if timezone.is_aware(timezone.now()) else timezone.now().date()
    if payment_date > today:
        raise ValidationError("Payment date cannot be in the future.")
    if loan and loan.lending_date and payment_date < loan.lending_date:
        raise ValidationError("Payment date cannot be earlier than the loan's lending date.")


def validate_payment_amount(loan, principal_component, exclude_payment_pk=None):
    """
    Raise ValidationError if recording a principal payment of `principal_component`
    would exceed the loan's outstanding principal.

    Pass exclude_payment_pk when editing an existing payment so that payment's
    own principal is not counted twice.
    """
    from django.db.models import Sum
    qs = loan.payments.active().filter(loan=loan)
    if exclude_payment_pk is not None:
        qs = qs.exclude(pk=exclude_payment_pk)
    already_paid = qs.aggregate(total=Sum("principal_component"))["total"] or Decimal("0.00")
    if already_paid + principal_component > loan.principal:
        raise ValidationError(
            f"Principal payment of ₹{principal_component:,.2f} would exceed outstanding "
            f"principal of ₹{(loan.principal - already_paid):,.2f}."
        )


def accrued_interest_through(loan, last_day):
    """
    Total interest the loan has accrued on its schedule up to and including
    `last_day`, summed over every due date in that span.
    """
    from .schedule import due_dates_through, period_start  # noqa: PLC0415

    return sum(
        (loan.expected_interest_as_of(period_start(loan, due))
         for due in due_dates_through(loan, last_day)),
        Decimal("0.00"),
    )


def validate_interest_against_terms(loan, payment_date, interest_component, exclude_payment_pk=None):
    """
    Reject interest that exceeds what the loan has accrued and not yet been paid.

    Accrual is counted up to the end of the payment's month, so interest for a
    due date later in that month can be paid early.  Partial payments are still
    allowed: the rule only caps the amount.  Interest already recorded on other
    active payments is subtracted.
    """
    import calendar  # noqa: PLC0415
    from django.db.models import Sum  # noqa: PLC0415

    last_day = payment_date.replace(
        day=calendar.monthrange(payment_date.year, payment_date.month)[1]
    )
    accrued = accrued_interest_through(loan, last_day)

    recorded_qs = loan.payments.active()
    if exclude_payment_pk is not None:
        recorded_qs = recorded_qs.exclude(pk=exclude_payment_pk)
    recorded = recorded_qs.aggregate(total=Sum("interest_component"))["total"] or Decimal("0.00")

    due = max(accrued - recorded, Decimal("0.00"))
    if Decimal(interest_component) > due:
        raise ValidationError(
            f"Interest of ₹{Decimal(interest_component):,.2f} is more than the ₹{due:,.2f} "
            f"accrued and unpaid up to {last_day:%d %B %Y}."
        )


def interest_schedule(loan, today=None):
    """
    Expected versus received interest, one row per due date.

    Each row compares the interest expected through that due date with the
    interest received to date, so payments never have to be assigned to a period.
    Rows run up to the end of the current month.  Status is:
      - "paid"     – received to date covers everything expected through this due date
      - "overdue"  – not covered, and the due date has passed
      - "upcoming" – not covered yet, and the due date is still ahead
    Zero-interest periods are left out.
    """
    import calendar  # noqa: PLC0415
    from .schedule import due_dates_through, period_start  # noqa: PLC0415

    today = today or timezone.localdate()
    horizon = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    received_to_date = sum(
        (p.interest_component for p in loan.payments.all() if not p.is_voided),
        Decimal("0.00"),
    )

    rows = []
    expected_through = Decimal("0.00")
    for due in due_dates_through(loan, horizon):
        expected = loan.expected_interest_as_of(period_start(loan, due))
        expected_through += expected
        if expected <= Decimal("0.00"):
            continue
        outstanding = max(expected_through - received_to_date, Decimal("0.00"))
        if outstanding <= Decimal("0.01"):
            status = "paid"
        elif due < today:
            status = "overdue"
        else:
            status = "upcoming"
        rows.append({
            "due_date": due,
            "expected": expected,
            "expected_through": expected_through,
            "received_to_date": received_to_date,
            "outstanding": outstanding,
            "status": status,
        })
    return rows


# ---------------------------------------------------------------------------
# Payment operations
# ---------------------------------------------------------------------------

def create_payment(loan_pk, payment_date, amount, principal_component,
                   interest_component, notes="", user=None):
    """
    Create a payment atomically with overpayment protection and audit log.

    Returns the created Payment instance.
    Raises ValidationError for invalid data.
    """
    with transaction.atomic():
        loan = lock_loan(loan_pk)

        if loan.status != "open":
            raise ValidationError("Payments can only be recorded on open loans.")

        validate_payment_date(loan, payment_date)
        validate_payment_amount(loan, principal_component)
        validate_interest_against_terms(loan, payment_date, interest_component)

        payment = Payment(
            loan=loan,
            payment_date=payment_date,
            amount=amount,
            principal_component=principal_component,
            interest_component=interest_component,
            notes=notes,
        )
        payment.full_clean()
        payment.save()

        AuditEvent.objects.create(
            user=user,
            event_type=AuditEvent.PAYMENT_CREATED,
            loan=loan,
            payment=payment,
            details=json.dumps({
                "payment_date": str(payment_date),
                "amount": str(amount),
                "principal_component": str(principal_component),
                "interest_component": str(interest_component),
            }),
        )

        logger.info(
            "Payment %d created on loan %s by user %s — ₹%s",
            payment.pk, loan.loan_id, user, amount,
        )
        return payment


def edit_payment(payment_pk, payment_date, amount, principal_component,
                 interest_component, notes="", user=None):
    """
    Edit an existing payment atomically.

    Re-validates the overpayment constraint excluding this payment's own
    contribution.  Records an audit entry with before/after values.

    Returns the updated Payment instance.
    Raises ValidationError for invalid data or if the payment is voided.
    """
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_pk)

        if payment.is_voided:
            raise ValidationError("Cannot edit a voided payment.")

        loan = lock_loan(payment.loan_id)

        if loan.status != "open":
            raise ValidationError("Cannot edit payments on a closed loan.")

        validate_payment_date(loan, payment_date)
        validate_payment_amount(loan, principal_component, exclude_payment_pk=payment_pk)
        validate_interest_against_terms(
            loan, payment_date, interest_component, exclude_payment_pk=payment_pk,
        )

        before = {
            "payment_date": str(payment.payment_date),
            "amount": str(payment.amount),
            "principal_component": str(payment.principal_component),
            "interest_component": str(payment.interest_component),
            "notes": payment.notes,
        }

        payment.payment_date = payment_date
        payment.amount = amount
        payment.principal_component = principal_component
        payment.interest_component = interest_component
        payment.notes = notes
        payment.full_clean()
        payment.save()

        AuditEvent.objects.create(
            user=user,
            event_type=AuditEvent.PAYMENT_EDITED,
            loan=loan,
            payment=payment,
            details=json.dumps({
                "before": before,
                "after": {
                    "payment_date": str(payment_date),
                    "amount": str(amount),
                    "principal_component": str(principal_component),
                    "interest_component": str(interest_component),
                    "notes": notes,
                },
            }),
        )

        logger.info(
            "Payment %d edited on loan %s by user %s",
            payment.pk, loan.loan_id, user,
        )
        return payment


def void_payment(payment_pk, void_reason, user=None):
    """
    Void a payment.

    Sets voided_at, void_reason, voided_by.  Does NOT delete the record.
    After voiding, the payment is excluded from all balance calculations.

    Raises ValidationError if already voided or reason is empty.
    Returns the voided Payment.
    """
    if not void_reason or not void_reason.strip():
        raise ValidationError("A void reason is required.")

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_pk)

        if payment.is_voided:
            raise ValidationError("This payment has already been voided.")

        loan = lock_loan(payment.loan_id)

        if loan.status != "open":
            raise ValidationError("Cannot void payments on a closed loan.")

        payment.voided_at = timezone.now()
        payment.void_reason = void_reason.strip()
        payment.voided_by = user
        payment.save(update_fields=["voided_at", "void_reason", "voided_by", "updated_at"])

        AuditEvent.objects.create(
            user=user,
            event_type=AuditEvent.PAYMENT_VOIDED,
            loan=loan,
            payment=payment,
            reason=void_reason.strip(),
            details=json.dumps({
                "payment_date": str(payment.payment_date),
                "amount": str(payment.amount),
                "principal_component": str(payment.principal_component),
                "interest_component": str(payment.interest_component),
            }),
        )

        logger.info(
            "Payment %d VOIDED on loan %s by user %s — reason: %s",
            payment.pk, loan.loan_id, user, void_reason,
        )
        return payment


# ---------------------------------------------------------------------------
# Loan operations
# ---------------------------------------------------------------------------

def edit_loan(loan_pk, principal, interest_rate, interest_period, interest_basis,
              lending_date, due_date, monthly_due_day, notes, user=None):
    """
    Edit a loan's terms.

    Safety rules:
      - If the loan has active payments, the principal cannot be reduced below
        the amount already repaid (would make balance negative).
      - Lending date cannot be moved after the earliest active payment date.

    Returns the updated Loan.
    Raises ValidationError for invalid changes.
    """
    with transaction.atomic():
        loan = lock_loan(loan_pk)

        if loan.status != "open":
            raise ValidationError("Cannot edit a closed loan.")

        # Guard: principal cannot be reduced below what's already been repaid.
        already_repaid = get_principal_repaid(loan)
        if principal < already_repaid:
            raise ValidationError(
                f"Cannot reduce principal to ₹{principal:,.2f} — "
                f"₹{already_repaid:,.2f} has already been repaid."
            )

        # Guard: lending date cannot move after earliest payment.
        earliest_payment = (
            loan.payments.active()
            .order_by("payment_date")
            .values_list("payment_date", flat=True)
            .first()
        )
        if earliest_payment and lending_date > earliest_payment:
            raise ValidationError(
                f"Cannot move lending date to {lending_date} — "
                f"a payment exists on {earliest_payment}."
            )

        before = {
            "principal": str(loan.principal),
            "interest_rate": str(loan.interest_rate),
            "interest_period": loan.interest_period,
            "interest_basis": loan.interest_basis,
            "lending_date": str(loan.lending_date),
            "due_date": str(loan.due_date),
            "monthly_due_day": loan.monthly_due_day,
            "notes": loan.notes,
        }

        loan.principal = principal
        loan.interest_rate = interest_rate
        loan.interest_period = interest_period
        loan.interest_basis = interest_basis
        loan.lending_date = lending_date
        loan.due_date = due_date
        loan.monthly_due_day = monthly_due_day
        loan.notes = notes
        loan.full_clean()
        loan.save()

        AuditEvent.objects.create(
            user=user,
            event_type=AuditEvent.LOAN_EDITED,
            loan=loan,
            details=json.dumps({
                "before": before,
                "after": {
                    "principal": str(principal),
                    "interest_rate": str(interest_rate),
                    "interest_period": interest_period,
                    "interest_basis": interest_basis,
                    "lending_date": str(lending_date),
                    "due_date": str(due_date),
                    "monthly_due_day": monthly_due_day,
                    "notes": notes,
                },
            }),
        )

        logger.info("Loan %s edited by user %s", loan.loan_id, user)
        return loan


def create_loan(borrower, principal, interest_rate, interest_period, interest_basis,
                lending_date, due_date=None, monthly_due_day=None, notes="", user=None):
    """
    Create a loan atomically with audit logging.
    """
    with transaction.atomic():
        loan = Loan(
            borrower=borrower,
            principal=principal,
            interest_rate=interest_rate,
            interest_period=interest_period,
            interest_basis=interest_basis,
            lending_date=lending_date,
            due_date=due_date,
            monthly_due_day=monthly_due_day,
            notes=notes,
            status="open",
        )
        loan.full_clean()
        loan.save()

        AuditEvent.objects.create(
            user=user,
            event_type=AuditEvent.LOAN_CREATED,
            loan=loan,
            details=json.dumps({
                "principal": str(principal),
                "interest_rate": str(interest_rate),
                "interest_period": interest_period,
                "interest_basis": interest_basis,
                "lending_date": str(lending_date),
                "due_date": str(due_date) if due_date else None,
                "monthly_due_day": monthly_due_day,
            }),
        )

        logger.info("Loan %s created for borrower %s by user %s", loan.loan_id, borrower, user)
        return loan


def close_loan(loan_pk, user=None):
    """
    Mark an open loan as closed atomically.
    Rejects closing if there is any remaining outstanding principal.
    Records LOAN_CLOSED audit event.
    """
    with transaction.atomic():
        loan = lock_loan(loan_pk)

        if loan.status == "closed":
            return loan

        outstanding = get_outstanding_principal(loan)
        if outstanding > Decimal("0.00"):
            raise ValidationError(
                f"Cannot close loan with outstanding principal of ₹{outstanding:,.2f}. "
                "Loans must be fully repaid before closing."
            )

        loan.status = "closed"
        loan.closed_at = timezone.now()
        loan.save(update_fields=["status", "closed_at", "updated_at"])

        AuditEvent.objects.create(
            user=user,
            event_type=AuditEvent.LOAN_CLOSED,
            loan=loan,
            details=json.dumps({
                "closed_at": str(loan.closed_at),
                "principal": str(loan.principal),
                "principal_repaid": str(get_principal_repaid(loan)),
            }),
        )

        logger.info("Loan %s CLOSED by user %s", loan.loan_id, user)
        return loan


def reopen_loan(loan_pk, user=None):
    """
    Reopen a closed loan atomically.
    Records LOAN_REOPENED audit event.
    """
    with transaction.atomic():
        loan = lock_loan(loan_pk)

        if loan.status == "open":
            return loan

        loan.status = "open"
        loan.closed_at = None
        loan.save(update_fields=["status", "closed_at", "updated_at"])

        AuditEvent.objects.create(
            user=user,
            event_type=AuditEvent.LOAN_REOPENED,
            loan=loan,
            details=json.dumps({
                "reopened_at": str(timezone.now()),
            }),
        )

        logger.info("Loan %s REOPENED by user %s", loan.loan_id, user)
        return loan


def update_loan_due_date(loan_pk, new_due_date, user=None):
    """
    Update loan due date (e.g. from tracker extension) atomically.
    Validates loan is open and new due date is not before lending date.
    Records LOAN_EDITED audit event and updates updated_at.
    """
    with transaction.atomic():
        loan = lock_loan(loan_pk)

        if loan.status != "open":
            raise ValidationError("Cannot update due date on a closed loan.")

        if new_due_date and loan.lending_date and new_due_date < loan.lending_date:
            raise ValidationError("Due date cannot be before the lending date.")

        before_due_date = str(loan.due_date) if loan.due_date else None
        loan.due_date = new_due_date
        loan.save(update_fields=["due_date", "updated_at"])

        AuditEvent.objects.create(
            user=user,
            event_type=AuditEvent.LOAN_EDITED,
            loan=loan,
            details=json.dumps({
                "due_date": {
                    "before": before_due_date,
                    "after": str(new_due_date),
                },
                "reason": "Tracker extension",
            }),
        )

        logger.info("Loan %s due date updated to %s by user %s", loan.loan_id, new_due_date, user)
        return loan
