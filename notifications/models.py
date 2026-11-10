import hashlib

from django.conf import settings
from django.db import models


class EmailNotification(models.Model):
    """Durable queue and audit record for one LendMate email."""

    LOAN_CREATED = "loan_created"
    PAYMENT_RECEIVED = "payment_received"
    LOAN_CLOSED = "loan_closed"
    UPCOMING_DUE = "upcoming_due"
    DUE_TODAY = "due_today"
    OVERDUE = "overdue"

    NOTIFICATION_TYPE_CHOICES = [
        (LOAN_CREATED, "Loan Created"),
        (PAYMENT_RECEIVED, "Payment Received"),
        (LOAN_CLOSED, "Loan Closed"),
        (UPCOMING_DUE, "Upcoming Due Date"),
        (DUE_TODAY, "Due Today"),
        (OVERDUE, "Overdue"),
    ]

    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (PROCESSING, "Processing"),
        (SENT, "Sent"),
        (FAILED, "Failed"),
        (SUPPRESSED, "Suppressed"),
    ]

    borrower = models.ForeignKey(
        "lending.Borrower",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_notifications",
    )
    loan = models.ForeignKey(
        "lending.Loan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_notifications",
    )
    payment = models.ForeignKey(
        "lending.Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_notifications",
    )
    lender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_notifications",
    )

    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPE_CHOICES)

    RECIPIENT_BORROWER = "borrower"
    RECIPIENT_LENDER = "lender"
    RECIPIENT_ROLE_CHOICES = [
        (RECIPIENT_BORROWER, "Borrower"),
        (RECIPIENT_LENDER, "Lender"),
    ]
    recipient_role = models.CharField(
        max_length=10,
        choices=RECIPIENT_ROLE_CHOICES,
        default=RECIPIENT_BORROWER,
    )

    recipient_email = models.EmailField(max_length=254)
    subject = models.CharField(max_length=255)
    message = models.TextField()
    html_message = models.TextField(blank=True)

    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=PENDING, db_index=True)

    provider_message_id = models.CharField(max_length=200, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)

    event_key = models.CharField(
        max_length=64,
        unique=True,
        help_text="Unique key to prevent duplicate email notifications.",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "next_retry_at"], name="email_status_retry_idx"),
            models.Index(fields=["lender", "status"], name="email_lender_status_idx"),
        ]

    def __str__(self):
        return f"{self.get_notification_type_display()} to {self.recipient_email} [{self.status}]"

    @classmethod
    def make_event_key(cls, notification_type, loan_id=None, payment_id=None, period_key="",
                       recipient_email="", recipient_role="borrower"):
        """Stable key for one logical email, so retries and reruns never duplicate it."""
        raw = (
            f"{recipient_role}:{notification_type}:{loan_id or ''}:{payment_id or ''}:"
            f"{period_key}:{recipient_email.strip().lower()}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()
