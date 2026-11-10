import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Sum


# ---------------------------------------------------------------------------
# Managers
# ---------------------------------------------------------------------------

class ActivePaymentManager(models.Manager):
    """Returns only non-voided payments. Use Payment.objects.active()."""

    def active(self):
        return self.filter(voided_at__isnull=True)

    def get_queryset(self):
        return super().get_queryset()


# ---------------------------------------------------------------------------
# Borrower
# ---------------------------------------------------------------------------

class ActiveBorrowerManager(models.Manager):
    """Hides borrowers in the recycle bin.  Use Borrower.all_objects to reach them."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class ActiveLoanManager(models.Manager):
    """Hides loans whose borrower is in the recycle bin.  Use Loan.all_objects for all loans."""

    def get_queryset(self):
        return super().get_queryset().filter(borrower__deleted_at__isnull=True)


class Borrower(models.Model):
    lender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="borrowers",
        null=True,
        blank=True,
    )

    full_name = models.CharField(max_length=150)
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, default="")
    notes = models.TextField(blank=True)
    email_consent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = ActiveBorrowerManager()
    all_objects = models.Manager()

    @property
    def total_borrowed(self):
        if hasattr(self, "_prefetched_objects_cache") and "loans" in self._prefetched_objects_cache:
            return sum((loan.principal for loan in self.loans.all()), Decimal("0.00"))
        return self.loans.aggregate(
            total=Sum("principal")
        )["total"] or Decimal("0.00")

    @property
    def outstanding_principal(self):
        if hasattr(self, "_prefetched_objects_cache") and "loans" in self._prefetched_objects_cache:
            total = Decimal("0.00")
            for loan in self.loans.all():
                total += loan.outstanding_principal
            return total
        total = Decimal("0.00")
        for loan in self.loans.all():
            total += loan.outstanding_principal
        return total

    @property
    def active_loans_count(self):
        if hasattr(self, "_prefetched_objects_cache") and "loans" in self._prefetched_objects_cache:
            return sum(1 for loan in self.loans.all() if loan.status == "open")
        return self.loans.filter(status="open").count()

    @property
    def closed_loans_count(self):
        if hasattr(self, "_prefetched_objects_cache") and "loans" in self._prefetched_objects_cache:
            return sum(1 for loan in self.loans.all() if loan.status == "closed")
        return self.loans.filter(status="closed").count()

    @property
    def total_loans_count(self):
        if hasattr(self, "_prefetched_objects_cache") and "loans" in self._prefetched_objects_cache:
            return len(self.loans.all())
        return self.loans.count()

    @property
    def is_active_status(self):
        return self.active_loans_count > 0

    def __str__(self):
        return self.full_name


# ---------------------------------------------------------------------------
# Loan
# ---------------------------------------------------------------------------

class Loan(models.Model):
    INTEREST_PERIOD_CHOICES = [
        ("monthly", "Monthly"),
        ("annually", "Annually"),
    ]

    INTEREST_BASIS_CHOICES = [
        ("original", "Original Principal"),
        ("reducing", "Reducing Balance"),
    ]

    STATUS_CHOICES = [
        ("open", "Open"),
        ("closed", "Closed"),
    ]

    objects = ActiveLoanManager()
    all_objects = models.Manager()

    loan_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    borrower = models.ForeignKey(
        Borrower, on_delete=models.PROTECT, related_name="loans"
    )

    principal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
    )

    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    interest_period = models.CharField(
        max_length=10,
        choices=INTEREST_PERIOD_CHOICES,
    )

    interest_basis = models.CharField(
        max_length=10,
        choices=INTEREST_BASIS_CHOICES,
    )

    lending_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)

    monthly_due_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(31),
        ],
    )

    notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="open",
    )

    closed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def principal_repaid(self):
        """Sum of principal components from active (non-voided) payments only."""
        if hasattr(self, "_prefetched_objects_cache") and "payments" in self._prefetched_objects_cache:
            return sum(
                (p.principal_component for p in self.payments.all() if not p.is_voided),
                Decimal("0.00"),
            )
        return self.payments.active().aggregate(
            total=Sum("principal_component")
        )["total"] or Decimal("0.00")

    @property
    def outstanding_principal(self):
        return self.principal - self.principal_repaid

    def principal_outstanding_as_of(self, as_of):
        """Principal still owed before `as_of` (active payments dated earlier only)."""
        if "payments" in getattr(self, "_prefetched_objects_cache", {}):
            repaid = sum(
                (p.principal_component for p in self.payments.all()
                 if not p.is_voided and p.payment_date < as_of),
                Decimal("0.00"),
            )
        else:
            repaid = self.payments.active().filter(
                payment_date__lt=as_of
            ).aggregate(total=Sum("principal_component"))["total"] or Decimal("0.00")
        return self.principal - repaid

    def expected_interest_as_of(self, as_of):
        """
        Interest expected for one interest period that starts on `as_of`.

        Original basis: rate x original principal.
        Reducing basis: rate x principal still owed on `as_of`.
        Rounded to paise.  Zero-rate loans expect zero.
        """
        if self.interest_basis == "reducing":
            base = self.principal_outstanding_as_of(as_of)
        else:
            base = self.principal
        base = max(base, Decimal("0.00"))
        rate = Decimal(self.interest_rate or 0) / Decimal("100")
        return (base * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def __str__(self):
        return f"Loan - {self.borrower.full_name}"


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------

class Payment(models.Model):
    loan = models.ForeignKey(
        Loan,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    payment_date = models.DateField()

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
    )

    principal_component = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )

    interest_component = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )

    notes = models.TextField(blank=True)

    # --- Voiding fields ---
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="voided_payments",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ActivePaymentManager()

    @property
    def is_voided(self):
        return self.voided_at is not None

    def clean(self):
        super().clean()

        if self.payment_date:
            from django.utils import timezone
            today = timezone.localtime(timezone.now()).date() if timezone.is_aware(timezone.now()) else timezone.now().date()
            if self.payment_date > today:
                raise ValidationError("Payment date cannot be in the future.")

            if self.loan_id:
                try:
                    loan = getattr(self, "loan", None) or Loan.objects.get(pk=self.loan_id)
                    if loan and loan.lending_date and self.payment_date < loan.lending_date:
                        raise ValidationError("Payment date cannot be earlier than the loan's lending date.")
                except Loan.DoesNotExist:
                    pass

        if self.amount is None:
            return

        if self.principal_component is None or self.interest_component is None:
            return

        if self.principal_component + self.interest_component != self.amount:
            raise ValidationError(
                "Principal and interest components must equal the total payment."
            )

        if self.loan_id:
            # Exclude self and voided payments from the overpayment check.
            previous_paid = Payment.objects.active().filter(
                loan_id=self.loan_id
            ).exclude(pk=self.pk).aggregate(
                total=Sum("principal_component")
            )["total"] or Decimal("0.00")

            if previous_paid + self.principal_component > self.loan.principal:
                raise ValidationError(
                    "Principal payment cannot exceed the outstanding principal."
                )

    def save(self, *args, **kwargs):
        # Validation is not repeated here: the ledger services call full_clean()
        # once before saving, and ModelForms validate on the web path.
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Payment - {self.loan.loan_id} - ₹{self.amount}"


# ---------------------------------------------------------------------------
# Audit Event
# ---------------------------------------------------------------------------

class AuditEvent(models.Model):
    LOAN_CREATED = "loan_created"
    LOAN_EDITED = "loan_edited"
    LOAN_CLOSED = "loan_closed"
    LOAN_REOPENED = "loan_reopened"
    PAYMENT_CREATED = "payment_created"
    PAYMENT_EDITED = "payment_edited"
    PAYMENT_VOIDED = "payment_voided"

    EVENT_CHOICES = [
        (LOAN_CREATED, "Loan Created"),
        (LOAN_EDITED, "Loan Edited"),
        (LOAN_CLOSED, "Loan Closed"),
        (LOAN_REOPENED, "Loan Reopened"),
        (PAYMENT_CREATED, "Payment Created"),
        (PAYMENT_EDITED, "Payment Edited"),
        (PAYMENT_VOIDED, "Payment Voided"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    loan = models.ForeignKey(
        Loan,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    payment = models.ForeignKey(
        Payment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    # JSON-encoded before/after snapshot — never store passwords or API keys.
    details = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} by {self.user} at {self.created_at}"


# ---------------------------------------------------------------------------
# BorrowerTracker
# ---------------------------------------------------------------------------

class BorrowerTracker(models.Model):
    TRACKER_TYPE_CHOICES = [
        ("custom", "Custom Tracker"),
        ("automatic", "Automatic Monthly Tracker"),
    ]

    borrower = models.ForeignKey(
        Borrower,
        on_delete=models.CASCADE,
        related_name="trackers",
    )
    tracker_type = models.CharField(
        max_length=20,
        choices=TRACKER_TYPE_CHOICES,
        default="custom",
    )
    loan = models.ForeignKey(
        Loan,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="trackers",
    )
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.borrower.full_name}"

    @property
    def is_automatic(self):
        return self.tracker_type == "automatic"

    @property
    def is_custom(self):
        return self.tracker_type == "custom"

    @property
    def total_items_count(self):
        return self.items.count()

    @property
    def completed_items_count(self):
        return self.items.filter(is_completed=True).count()

    @property
    def pending_items_count(self):
        return self.items.filter(is_completed=False).count()

    @property
    def progress_percentage(self):
        total = self.total_items_count
        if total == 0:
            return 0
        return int(round((self.completed_items_count / total) * 100))


# ---------------------------------------------------------------------------
# TrackerItem
# ---------------------------------------------------------------------------

class TrackerItem(models.Model):
    tracker = models.ForeignKey(
        BorrowerTracker,
        on_delete=models.CASCADE,
        related_name="items",
    )
    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    tracking_date = models.DateField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.title

    @property
    def expected_interest(self):
        """
        Interest expected for the month this item covers.  Only meaningful for
        monthly loans on automatic trackers; returns None otherwise.
        """
        loan = self.tracker.loan
        if loan is None or self.tracking_date is None or loan.interest_period != "monthly":
            return None
        return loan.expected_interest_as_of(self.tracking_date.replace(day=1))

    @property
    def expected_interest_display(self):
        value = self.expected_interest
        if value is None or value <= 0:
            return ""
        return f"Due ₹{value:,.2f}"
