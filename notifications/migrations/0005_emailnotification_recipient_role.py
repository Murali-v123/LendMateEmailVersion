from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0004_email_notifications"),
    ]

    operations = [
        migrations.AddField(
            model_name="emailnotification",
            name="recipient_role",
            field=models.CharField(
                choices=[("borrower", "Borrower"), ("lender", "Lender")],
                default="borrower",
                max_length=10,
            ),
        ),
    ]
