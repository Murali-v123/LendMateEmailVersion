from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Drop UserPreferences.payment_reminders / due_date_reminders.

    Nothing ever read these flags: reminder sending is controlled by the
    sms_* preferences. Reversible (both fields have defaults).
    """

    dependencies = [
        ('core', '0002_add_sms_preferences'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='userpreferences',
            name='payment_reminders',
        ),
        migrations.RemoveField(
            model_name='userpreferences',
            name='due_date_reminders',
        ),
    ]
