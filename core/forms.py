from django import forms
from django.contrib.auth import get_user_model

from .models import UserPreferences


User = get_user_model()


class BootstrapFormMixin:
    """Applies LendMate's form styling classes to every field widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            widget = field.widget

            if isinstance(widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"

            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = " ".join(
                part for part in (existing, css_class) if part
            )


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "email": "Email address",
        }

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email


class UserPreferencesForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = UserPreferences
        fields = [
            "email_notifications_enabled",
            "email_loan_created",
            "email_payment_received",
            "email_upcoming_reminders",
            "email_overdue_reminders",
            "email_loan_closed",
            "email_lender_alerts",
        ]
        labels = {
            "email_notifications_enabled": "Enable Email Notifications",
            "email_loan_created": "Loan Created Email",
            "email_payment_received": "Payment Received Email",
            "email_upcoming_reminders": "Upcoming Reminder Email",
            "email_overdue_reminders": "Overdue Reminder Email",
            "email_loan_closed": "Loan Closed Email",
            "email_lender_alerts": "My Alerts (Lender Copies)",
        }
        help_texts = {
            "email_notifications_enabled": "Master switch. Emails will only be sent when this is on.",
            "email_loan_created": "Email the borrower when a new loan is recorded.",
            "email_payment_received": "Email the borrower when a payment is recorded.",
            "email_upcoming_reminders": "Email before each due date and on the due date.",
            "email_overdue_reminders": "Email when a repayment is overdue.",
            "email_loan_closed": "Email the borrower when a loan is marked closed.",
            "email_lender_alerts": "Email me about loans I create, payments I receive, and repayments that are due or overdue.",
        }
