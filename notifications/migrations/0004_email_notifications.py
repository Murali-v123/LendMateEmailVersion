import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("lending", "0008_rename_sms_consent_to_email_consent"),
        ("notifications", "0003_smsnotification_template_variables"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "notification_type",
                    models.CharField(
                        choices=[
                            ("loan_created", "Loan Created"),
                            ("payment_received", "Payment Received"),
                            ("loan_closed", "Loan Closed"),
                            ("upcoming_due", "Upcoming Due Date"),
                            ("due_today", "Due Today"),
                            ("overdue", "Overdue"),
                        ],
                        max_length=30,
                    ),
                ),
                ("recipient_email", models.EmailField(max_length=254)),
                ("subject", models.CharField(max_length=255)),
                ("message", models.TextField()),
                ("html_message", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                            ("suppressed", "Suppressed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=15,
                    ),
                ),
                ("provider_message_id", models.CharField(blank=True, max_length=200)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("last_error", models.TextField(blank=True)),
                (
                    "event_key",
                    models.CharField(
                        help_text="Unique key to prevent duplicate email notifications.",
                        max_length=64,
                        unique=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("next_retry_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                (
                    "borrower",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="email_notifications",
                        to="lending.borrower",
                    ),
                ),
                (
                    "lender",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "loan",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="email_notifications",
                        to="lending.loan",
                    ),
                ),
                (
                    "payment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="email_notifications",
                        to="lending.payment",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["status", "next_retry_at"], name="email_status_retry_idx"),
                    models.Index(fields=["lender", "status"], name="email_lender_status_idx"),
                ],
            },
        ),
        migrations.DeleteModel(
            name="SMSNotification",
        ),
    ]
