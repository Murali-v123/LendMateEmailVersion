from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lending", "0007_payment_voiding_audit_timestamps"),
    ]

    operations = [
        migrations.RenameField(
            model_name="borrower",
            old_name="sms_consent",
            new_name="email_consent",
        ),
        migrations.AlterField(
            model_name="borrower",
            name="mobile_number",
            field=models.CharField(blank=True, max_length=15),
        ),
    ]
