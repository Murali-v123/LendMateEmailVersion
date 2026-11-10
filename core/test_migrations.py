"""
Guard against model and migration drift.

If a model field is changed or removed without a matching migration (the way
the reminder-preference fields once caused a silent notification outage), this test fails
before the change can be deployed.
"""
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase


class MigrationsMatchModelsTests(SimpleTestCase):
    databases = {"default"}

    def test_no_missing_migrations(self):
        out = StringIO()
        try:
            call_command(
                "makemigrations", "--check", "--dry-run",
                stdout=out, stderr=out,
            )
        except SystemExit as exc:  # makemigrations --check exits non-zero on drift
            self.fail(f"Models have changes without migrations:\n{out.getvalue()}\n(exit {exc.code})")
