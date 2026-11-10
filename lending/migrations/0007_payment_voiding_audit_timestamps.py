"""
Migration: Add voiding fields to Payment, updated_at to Loan and Payment,
and create AuditEvent model.

This migration is safe for existing data:
- voided_at / void_reason / voided_by are all null/blank by default.
- updated_at uses auto_now so existing rows get the migration timestamp.
- AuditEvent is a new table with no effect on existing data.
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lending", "0006_borrowertracker_end_date_borrowertracker_loan_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # --- Add updated_at to Loan ---
        migrations.AddField(
            model_name="loan",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),

        # --- Add updated_at to Payment ---
        migrations.AddField(
            model_name="payment",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),

        # --- Add voiding fields to Payment ---
        migrations.AddField(
            model_name="payment",
            name="voided_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="void_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="voided_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="voided_payments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # --- Create AuditEvent table ---
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(
                    choices=[
                        ("loan_created", "Loan Created"),
                        ("loan_edited", "Loan Edited"),
                        ("loan_closed", "Loan Closed"),
                        ("loan_reopened", "Loan Reopened"),
                        ("payment_created", "Payment Created"),
                        ("payment_edited", "Payment Edited"),
                        ("payment_voided", "Payment Voided"),
                    ],
                    max_length=30,
                )),
                ("details", models.TextField(blank=True)),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("loan", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="audit_events",
                    to="lending.loan",
                )),
                ("payment", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="audit_events",
                    to="lending.payment",
                )),
                ("user", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="audit_events",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
