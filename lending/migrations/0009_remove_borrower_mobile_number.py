from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("lending", "0008_rename_sms_consent_to_email_consent"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="borrower",
            name="mobile_number",
        ),
    ]