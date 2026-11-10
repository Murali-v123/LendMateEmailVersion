import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
import threading
from django.db import connection

from .models import AuditEvent, Borrower, Loan, Payment
from . import services


class LedgerAndFinancialSafetyTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.lender = User.objects.create_user(
            username="lender1", email="lender1@example.com", password="Pass123!Secure"
        )
        self.other_lender = User.objects.create_user(
            username="lender2", email="lender2@example.com", password="Pass123!Secure"
        )
        self.borrower = Borrower.objects.create(
            lender=self.lender, full_name="Ledger User"
        )
        self.loan = Loan.objects.create(
            borrower=self.borrower,
            principal=Decimal("10000.00"),
            interest_rate=Decimal("12.00"),
            interest_period="monthly",
            interest_basis="original",
            lending_date=datetime.date(2026, 1, 1),
            due_date=datetime.date(2026, 12, 31),
            monthly_due_day=5,
            status="open",
        )
        self.payment = services.create_payment(
            loan_pk=self.loan.pk,
            payment_date=datetime.date(2026, 2, 1),
            amount=Decimal("2000.00"),
            principal_component=Decimal("1800.00"),
            interest_component=Decimal("200.00"),
            notes="Initial repayment",
            user=self.lender,
        )

    def test_payment_creation_and_balance_impact(self):
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.principal_repaid, Decimal("1800.00"))
        self.assertEqual(self.loan.outstanding_principal, Decimal("8200.00"))
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.PAYMENT_CREATED, payment=self.payment
            ).exists()
        )

    def test_overpayment_rejected(self):
        # Attempt to pay principal > remaining 8200.00
        with self.assertRaises(ValidationError):
            services.create_payment(
                loan_pk=self.loan.pk,
                payment_date=datetime.date(2026, 3, 1),
                amount=Decimal("9000.00"),
                principal_component=Decimal("8500.00"),
                interest_component=Decimal("500.00"),
                user=self.lender,
            )

    def test_void_payment_removes_from_balance_and_records_audit(self):
        services.void_payment(
            payment_pk=self.payment.pk,
            void_reason="Incorrect cheque bounce entry",
            user=self.lender,
        )
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.is_voided)
        self.assertEqual(self.payment.void_reason, "Incorrect cheque bounce entry")
        self.assertEqual(self.payment.voided_by, self.lender)

        # Balances must recalculate
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.principal_repaid, Decimal("0.00"))
        self.assertEqual(self.loan.outstanding_principal, Decimal("10000.00"))

        # Audit event recorded
        audit = AuditEvent.objects.filter(
            event_type=AuditEvent.PAYMENT_VOIDED, payment=self.payment
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.reason, "Incorrect cheque bounce entry")

    def test_voiding_already_voided_payment_fails(self):
        services.void_payment(
            payment_pk=self.payment.pk,
            void_reason="First void",
            user=self.lender,
        )
        with self.assertRaises(ValidationError):
            services.void_payment(
                payment_pk=self.payment.pk,
                void_reason="Second void",
                user=self.lender,
            )

    def test_edit_payment_updates_balance_and_audits(self):
        services.edit_payment(
            payment_pk=self.payment.pk,
            payment_date=datetime.date(2026, 2, 2),
            amount=Decimal("2400.00"),
            principal_component=Decimal("2200.00"),
            interest_component=Decimal("200.00"),
            notes="Corrected receipt amount",
            user=self.lender,
        )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount, Decimal("2400.00"))
        self.assertEqual(self.payment.principal_component, Decimal("2200.00"))

        self.loan.refresh_from_db()
        self.assertEqual(self.loan.principal_repaid, Decimal("2200.00"))
        self.assertEqual(self.loan.outstanding_principal, Decimal("7800.00"))

        # Verify audit trail
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.PAYMENT_EDITED, payment=self.payment
            ).exists()
        )

    def test_cannot_edit_voided_payment(self):
        services.void_payment(self.payment.pk, "Voided", self.lender)
        with self.assertRaises(ValidationError):
            services.edit_payment(
                payment_pk=self.payment.pk,
                payment_date=datetime.date(2026, 2, 2),
                amount=Decimal("2500.00"),
                principal_component=Decimal("2200.00"),
                interest_component=Decimal("300.00"),
                notes="Try to edit voided",
                user=self.lender,
            )

    def test_edit_loan_principal_below_repaid_fails(self):
        # Repaid is 1800.00; reducing principal to 1500.00 must fail
        with self.assertRaises(ValidationError):
            services.edit_loan(
                loan_pk=self.loan.pk,
                principal=Decimal("1500.00"),
                interest_rate=self.loan.interest_rate,
                interest_period=self.loan.interest_period,
                interest_basis=self.loan.interest_basis,
                lending_date=self.loan.lending_date,
                due_date=self.loan.due_date,
                monthly_due_day=self.loan.monthly_due_day,
                notes="Lower principal",
                user=self.lender,
            )

    def test_edit_loan_success_updates_and_audits(self):
        services.edit_loan(
            loan_pk=self.loan.pk,
            principal=Decimal("12000.00"),
            interest_rate=Decimal("14.00"),
            interest_period="monthly",
            interest_basis="original",
            lending_date=self.loan.lending_date,
            due_date=self.loan.due_date,
            monthly_due_day=5,
            notes="Increased credit limit",
            user=self.lender,
        )
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.principal, Decimal("12000.00"))
        self.assertEqual(self.loan.interest_rate, Decimal("14.00"))
        self.assertEqual(self.loan.outstanding_principal, Decimal("10200.00"))
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.LOAN_EDITED, loan=self.loan
            ).exists()
        )

    def test_lender_cannot_access_or_void_other_lenders_payment(self):
        self.client.login(username="lender2", password="Pass123!Secure")
        response = self.client.post(
            reverse("lending:void_payment", kwargs={"payment_pk": self.payment.pk}),
            {"void_reason": "Malicious void attempt"},
        )
        self.assertEqual(response.status_code, 404)
        self.payment.refresh_from_db()
        self.assertFalse(self.payment.is_voided)

    def test_payment_creation_view_uses_ledger_service_and_creates_audit_event(self):
        self.client.login(username="lender1", password="Pass123!Secure")
        response = self.client.post(
            reverse("lending:add_loan_payment", kwargs={"loan_id": self.loan.loan_id}),
            {
                "loan": self.loan.pk,
                "payment_date": "2026-03-01",
                "amount": "1000.00",
                "principal_component": "900.00",
                "interest_component": "100.00",
                "notes": "View-submitted payment",
            },
        )
        self.assertEqual(response.status_code, 302)
        created_payment = Payment.objects.filter(notes="View-submitted payment").first()
        self.assertIsNotNone(created_payment)
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.PAYMENT_CREATED,
                payment=created_payment,
            ).exists()
        )

    def test_loan_close_and_reopen_record_audit_events(self):
        # Repay the remainder (8200.00)
        services.create_payment(
            loan_pk=self.loan.pk,
            payment_date=datetime.date(2026, 3, 1),
            amount=Decimal("8200.00"),
            principal_component=Decimal("8200.00"),
            interest_component=Decimal("0.00"),
            user=self.lender,
        )
        self.assertEqual(self.loan.outstanding_principal, Decimal("0.00"))

        # Close loan
        services.close_loan(self.loan.pk, user=self.lender)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.status, "closed")
        self.assertIsNotNone(self.loan.closed_at)
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.LOAN_CLOSED,
                loan=self.loan,
            ).exists()
        )

        # Reopen loan
        services.reopen_loan(self.loan.pk, user=self.lender)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.status, "open")
        self.assertIsNone(self.loan.closed_at)
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.LOAN_REOPENED,
                loan=self.loan,
            ).exists()
        )

    def test_closed_loan_rejects_payment_creation_editing_and_voiding(self):
        # Pay in full and close
        services.create_payment(
            loan_pk=self.loan.pk,
            payment_date=datetime.date(2026, 3, 1),
            amount=Decimal("8200.00"),
            principal_component=Decimal("8200.00"),
            interest_component=Decimal("0.00"),
            user=self.lender,
        )
        services.close_loan(self.loan.pk, user=self.lender)

        # 1. Reject create_payment
        with self.assertRaises(ValidationError):
            services.create_payment(
                loan_pk=self.loan.pk,
                payment_date=datetime.date(2026, 3, 2),
                amount=Decimal("100.00"),
                principal_component=Decimal("0.00"),
                interest_component=Decimal("100.00"),
                user=self.lender,
            )

        # 2. Reject edit_payment
        with self.assertRaises(ValidationError):
            services.edit_payment(
                payment_pk=self.payment.pk,
                payment_date=datetime.date(2026, 2, 1),
                amount=Decimal("2000.00"),
                principal_component=Decimal("1800.00"),
                interest_component=Decimal("200.00"),
                user=self.lender,
            )

        # 3. Reject void_payment
        with self.assertRaises(ValidationError):
            services.void_payment(
                payment_pk=self.payment.pk,
                void_reason="Void on closed loan",
                user=self.lender,
            )

        # 4. Reject edit_loan
        with self.assertRaises(ValidationError):
            services.edit_loan(
                loan_pk=self.loan.pk,
                principal=Decimal("10000.00"),
                interest_rate=Decimal("12.00"),
                interest_period="monthly",
                interest_basis="original",
                lending_date=datetime.date(2026, 1, 1),
                due_date=datetime.date(2026, 12, 31),
                monthly_due_day=5,
                notes="Edit closed",
                user=self.lender,
            )

    def test_loans_with_outstanding_principal_cannot_be_closed(self):
        # Outstanding is 8200.00
        self.assertGreater(self.loan.outstanding_principal, Decimal("0.00"))
        with self.assertRaises(ValidationError):
            services.close_loan(self.loan.pk, user=self.lender)

        # Also via view
        self.client.login(username="lender1", password="Pass123!Secure")
        response = self.client.post(
            reverse("lending:close_loan", kwargs={"loan_id": self.loan.loan_id})
        )
        self.assertEqual(response.status_code, 302)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.status, "open")

    def test_payment_dates_validation(self):
        # Payment before lending date rejected
        before_date = self.loan.lending_date - datetime.timedelta(days=1)
        with self.assertRaises(ValidationError):
            services.create_payment(
                loan_pk=self.loan.pk,
                payment_date=before_date,
                amount=Decimal("500.00"),
                principal_component=Decimal("500.00"),
                interest_component=Decimal("0.00"),
                user=self.lender,
            )

        # Future payment date rejected
        future_date = timezone.now().date() + datetime.timedelta(days=5)
        with self.assertRaises(ValidationError):
            services.create_payment(
                loan_pk=self.loan.pk,
                payment_date=future_date,
                amount=Decimal("500.00"),
                principal_component=Decimal("500.00"),
                interest_component=Decimal("0.00"),
                user=self.lender,
            )

    def test_due_date_extension_audited_and_updates_updated_at(self):
        initial_updated_at = self.loan.updated_at
        new_due_date = datetime.date(2027, 6, 30)

        services.update_loan_due_date(
            loan_pk=self.loan.pk,
            new_due_date=new_due_date,
            user=self.lender,
        )
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, new_due_date)
        self.assertGreaterEqual(self.loan.updated_at, initial_updated_at)
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.LOAN_EDITED,
                loan=self.loan,
            ).exists()
        )

    def test_admin_lender_isolation_and_payment_protection(self):
        from django.test import RequestFactory
        from lending.admin import PaymentAdmin, LoanAdmin, BorrowerTrackerAdmin, AuditEventAdmin
        from django.contrib.admin.sites import AdminSite

        site = AdminSite()
        rf = RequestFactory()
        request = rf.get("/admin/")
        request.user = self.lender

        payment_admin = PaymentAdmin(Payment, site)
        # 1. Staff users only see their own lender payments
        qs = payment_admin.get_queryset(request)
        for p in qs:
            self.assertEqual(p.loan.borrower.lender, self.lender)

        # 2. Hard deletion is forbidden
        self.assertFalse(payment_admin.has_delete_permission(request, self.payment))

        # 3. Direct editing of financial fields on existing payments is readonly
        readonly = payment_admin.get_readonly_fields(request, self.payment)
        self.assertIn("amount", readonly)
        self.assertIn("principal_component", readonly)
        self.assertIn("interest_component", readonly)
        self.assertIn("voided_at", readonly)

        # 4. AuditEvent is completely immutable
        audit_admin = AuditEventAdmin(AuditEvent, site)
        self.assertFalse(audit_admin.has_add_permission(request))
        self.assertFalse(audit_admin.has_change_permission(request))
        self.assertFalse(audit_admin.has_delete_permission(request))


class ConcurrentPaymentTests(TransactionTestCase):
    def test_concurrent_payments_cannot_exceed_outstanding(self):
        from django.contrib.auth.models import User
        lender = User.objects.create_user(
            username="concurrent_lender", email="conc@example.com", password="Pass123!Secure"
        )
        borrower = Borrower.objects.create(
            lender=lender, full_name="Ledger User"
        )
        loan = Loan.objects.create(
            borrower=borrower,
            principal=Decimal("5000.00"),
            interest_rate=Decimal("10.00"),
            interest_period="monthly",
            interest_basis="original",
            lending_date=datetime.date(2026, 1, 1),
            status="open",
        )

        successes = []
        failures = []

        def attempt_payment():
            connection.close()  # Ensure separate thread gets its own fresh DB connection
            try:
                p = services.create_payment(
                    loan_pk=loan.pk,
                    payment_date=datetime.date(2026, 2, 1),
                    amount=Decimal("3000.00"),
                    principal_component=Decimal("3000.00"),
                    interest_component=Decimal("0.00"),
                    notes="Concurrent payment attempt",
                    user=lender,
                )
                successes.append(p)
            except ValidationError as e:
                failures.append(e)
            finally:
                connection.close()

        # Launch two concurrent attempts of 3000.00 on a 5000.00 loan
        t1 = threading.Thread(target=attempt_payment)
        t2 = threading.Thread(target=attempt_payment)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        loan.refresh_from_db()
        # Exactly one must succeed and one must fail
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(loan.principal_repaid, Decimal("3000.00"))
        self.assertEqual(loan.outstanding_principal, Decimal("2000.00"))
