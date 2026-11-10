
from django.conf import settings
from django.db import models


class UserPreferences(models.Model):

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences"
    )

    # --- Email notification preferences ---
    email_notifications_enabled = models.BooleanField(
        default=False,
        help_text="Master switch: enable email notifications for this lender's borrowers."
    )
    email_loan_created = models.BooleanField(
        default=True,
        help_text="Email the borrower when a new loan is recorded."
    )
    email_payment_received = models.BooleanField(
        default=True,
        help_text="Email the borrower when a payment is recorded."
    )
    email_upcoming_reminders = models.BooleanField(
        default=True,
        help_text="Email the borrower before each repayment due date and on the due date."
    )
    email_overdue_reminders = models.BooleanField(
        default=True,
        help_text="Email the borrower when a repayment is overdue."
    )
    email_loan_closed = models.BooleanField(
        default=True,
        help_text="Email the borrower when a loan is marked closed."
    )
    email_lender_alerts = models.BooleanField(
        default=True,
        help_text="Email me about loans I create, payments I receive, and repayments that are due or overdue."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences - {self.user.username}"
