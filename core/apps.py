from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Core"

    def ready(self):
        # Import checks so they register with Django's check framework.
        try:
            from . import checks  # noqa: F401
        except ImportError:
            pass
