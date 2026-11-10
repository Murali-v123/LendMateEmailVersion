from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_sms_preferences_to_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreferences",
            name="email_lender_alerts",
            field=models.BooleanField(
                default=True,
                help_text="Email me about loans I create, payments I receive, and repayments that are due or overdue.",
            ),
        ),
    ]
