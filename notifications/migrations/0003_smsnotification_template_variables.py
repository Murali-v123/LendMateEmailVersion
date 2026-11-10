from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0002_smsnotification_updated_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="smsnotification",
            name="template_variables",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Variables sent to the DLT-approved MSG91 template.",
            ),
        ),
    ]
