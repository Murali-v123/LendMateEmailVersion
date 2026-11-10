from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_remove_unused_reminder_preferences"),
    ]

    operations = [
        migrations.RenameField(
            model_name="userpreferences",
            old_name="sms_notifications_enabled",
            new_name="email_notifications_enabled",
        ),
        migrations.RenameField(
            model_name="userpreferences",
            old_name="sms_loan_created",
            new_name="email_loan_created",
        ),
        migrations.RenameField(
            model_name="userpreferences",
            old_name="sms_payment_received",
            new_name="email_payment_received",
        ),
        migrations.RenameField(
            model_name="userpreferences",
            old_name="sms_monthly_reminders",
            new_name="email_upcoming_reminders",
        ),
        migrations.RenameField(
            model_name="userpreferences",
            old_name="sms_overdue_reminders",
            new_name="email_overdue_reminders",
        ),
        migrations.RenameField(
            model_name="userpreferences",
            old_name="sms_loan_closed",
            new_name="email_loan_closed",
        ),
        migrations.AlterField(
            model_name="userpreferences",
            name="email_notifications_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Master switch: enable email notifications for this lender's borrowers.",
            ),
        ),
        migrations.AlterField(
            model_name="userpreferences",
            name="email_loan_created",
            field=models.BooleanField(
                default=True,
                help_text="Email the borrower when a new loan is recorded.",
            ),
        ),
        migrations.AlterField(
            model_name="userpreferences",
            name="email_payment_received",
            field=models.BooleanField(
                default=True,
                help_text="Email the borrower when a payment is recorded.",
            ),
        ),
        migrations.AlterField(
            model_name="userpreferences",
            name="email_upcoming_reminders",
            field=models.BooleanField(
                default=True,
                help_text="Email the borrower before each repayment due date and on the due date.",
            ),
        ),
        migrations.AlterField(
            model_name="userpreferences",
            name="email_overdue_reminders",
            field=models.BooleanField(
                default=True,
                help_text="Email the borrower when a repayment is overdue.",
            ),
        ),
        migrations.AlterField(
            model_name="userpreferences",
            name="email_loan_closed",
            field=models.BooleanField(
                default=True,
                help_text="Email the borrower when a loan is marked closed.",
            ),
        ),
    ]
