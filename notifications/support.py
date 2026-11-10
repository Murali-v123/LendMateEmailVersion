"""Shared fixtures for the notification test modules (not a test module itself)."""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model

from core.models import UserPreferences
from lending.models import Borrower, Loan

User = get_user_model()


class LendMateTestMixin:
    """A lender with every email switch on, one consenting borrower and one open monthly loan."""

    def setUp(self):
        super().setUp()
        self.lender = User.objects.create_user(
            username="lender1", password="pass-1234-xyz", first_name="Test", last_name="Lender",
        )
        self.prefs = UserPreferences.objects.create(
            user=self.lender,
            email_notifications_enabled=True,
            email_loan_created=True,
            email_payment_received=True,
            email_upcoming_reminders=True,
            email_overdue_reminders=True,
            email_loan_closed=True,
        )
        self.borrower = Borrower.objects.create(
            lender=self.lender,
            full_name="Ravi Kumar",
            email="ravi@example.com",
            email_consent=True,
        )
        self.loan = Loan.objects.create(
            borrower=self.borrower,
            principal=Decimal("100000.00"),
            interest_rate=Decimal("2.00"),
            interest_period="monthly",
            interest_basis="original",
            lending_date=datetime.date(2026, 1, 15),
            monthly_due_day=15,
            status="open",
        )
