from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lending", "0010_borrower_deleted_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="borrower",
            name="phone_number",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
