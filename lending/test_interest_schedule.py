"""
Expected-versus-received interest schedule: statuses, outstanding amounts,
zero-rate loans, and voided payments.
"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Borrower, Loan
from .services import create_payment, interest_schedule, void_payment

User = get_user_model()
TODAY = datetime.date(2026, 3, 20)


class InterestScheduleTests(TestCase):
    def setUp(self):
        self.lender = User.objects.create_user(username="sched2", password="pass-1234-xyz")
        self.borrower = Borrower.objects.create(
            lender=self.lender, full_name="Ledger User"
        )
        # 100,000 at 2% a month, due on the 15th: 2000 accrues on Jan 15, Feb 15 and Mar 15.
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

    def _pay_interest(self, date, interest):
        return create_payment(
            loan_pk=self.loan.pk,
            payment_date=date,
            amount=Decimal(interest),
            principal_component=Decimal("0.00"),
            interest_component=Decimal(interest),
        )

    def _rows(self):
        self.loan.refresh_from_db()
        return interest_schedule(Loan.objects.get(pk=self.loan.pk), today=TODAY)

    def test_partial_payment_leaves_later_periods_overdue(self):
        self._pay_interest(datetime.date(2026, 1, 20), "2000.00")
        rows = self._rows()
        self.assertEqual([r["status"] for r in rows], ["paid", "overdue", "overdue"])
        self.assertEqual(rows[1]["outstanding"], Decimal("2000.00"))
        self.assertEqual(rows[2]["outstanding"], Decimal("4000.00"))

    def test_catching_up_marks_every_period_paid(self):
        self._pay_interest(datetime.date(2026, 1, 20), "2000.00")
        self._pay_interest(datetime.date(2026, 3, 10), "4000.00")
        rows = self._rows()
        self.assertEqual([r["status"] for r in rows], ["paid", "paid", "paid"])
        self.assertTrue(all(r["outstanding"] == Decimal("0.00") for r in rows))

    def test_future_due_date_in_the_current_month_is_upcoming(self):
        # Today is 10 Feb: the 15 Feb due date has not passed yet.
        rows = interest_schedule(self.loan, today=datetime.date(2026, 2, 10))
        self.assertEqual([r["status"] for r in rows], ["overdue", "upcoming"])

    def test_voided_payment_is_not_counted_as_received(self):
        payment = self._pay_interest(datetime.date(2026, 1, 20), "2000.00")
        void_payment(payment_pk=payment.pk, void_reason="Entered in error")
        rows = self._rows()
        self.assertEqual(rows[0]["status"], "overdue")
        self.assertEqual(rows[0]["outstanding"], Decimal("2000.00"))

    def test_zero_rate_loan_has_no_schedule_rows(self):
        self.loan.interest_rate = Decimal("0.00")
        self.loan.save()
        self.assertEqual(self._rows(), [])
