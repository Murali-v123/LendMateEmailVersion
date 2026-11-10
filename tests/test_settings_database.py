"""
Database configuration: DATABASE_URL parsing, encoded passwords, the empty-password
guard, and SSL defaults.  These tests read the settings helper directly and never
open a database connection.
"""
import os
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.settings import _database_settings


def _env(**values):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_URL", "POSTGRES_", "DB_SSLMODE"))}
    base.update(values)
    return patch.dict(os.environ, base, clear=True)


class DatabaseSettingsTests(SimpleTestCase):
    def test_database_url_is_parsed_into_postgres_settings(self):
        with _env(DATABASE_URL="postgresql://lendmate:secret123@db.example.com:5432/lendmate_prod"):
            cfg = _database_settings()
        self.assertEqual(cfg["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(cfg["NAME"], "lendmate_prod")
        self.assertEqual(cfg["USER"], "lendmate")
        self.assertEqual(cfg["PASSWORD"], "secret123")
        self.assertEqual(cfg["HOST"], "db.example.com")
        self.assertEqual(cfg["PORT"], "5432")

    def test_percent_encoded_password_is_decoded(self):
        # p@ss/w:rd encoded as p%40ss%2Fw%3Ard
        with _env(DATABASE_URL="postgres://lendmate:p%40ss%2Fw%3Ard@db.example.com/lendmate"):
            cfg = _database_settings()
        self.assertEqual(cfg["PASSWORD"], "p@ss/w:rd")

    def test_ssl_defaults_to_require_for_a_database_url(self):
        with _env(DATABASE_URL="postgresql://u:pw@host/db"):
            self.assertEqual(_database_settings()["OPTIONS"]["sslmode"], "require")

    def test_local_settings_default_to_prefer(self):
        with _env(POSTGRES_PASSWORD="local-pw"):
            cfg = _database_settings()
        self.assertEqual(cfg["HOST"], "127.0.0.1")
        self.assertEqual(cfg["PORT"], "5432")
        self.assertEqual(cfg["OPTIONS"]["sslmode"], "prefer")

    def test_ssl_mode_can_be_overridden(self):
        with _env(POSTGRES_PASSWORD="pw", DB_SSLMODE="disable"):
            self.assertEqual(_database_settings()["OPTIONS"]["sslmode"], "disable")

    def test_unknown_ssl_mode_is_rejected(self):
        with _env(POSTGRES_PASSWORD="pw", DB_SSLMODE="sometimes"):
            with self.assertRaises(ImproperlyConfigured):
                _database_settings()

    def test_mysql_url_is_rejected(self):
        with _env(DATABASE_URL="mysql://u:pw@host/db"):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                _database_settings()
        self.assertIn("postgresql://", str(ctx.exception))

    def test_empty_password_is_refused(self):
        # The old failure mode: connecting with no password and getting "Access denied".
        with _env(POSTGRES_PASSWORD=""):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                _database_settings()
        self.assertIn("password is empty", str(ctx.exception))

    def test_password_value_is_never_echoed_in_errors(self):
        with _env(DATABASE_URL="mysql://u:TopSecretPw@host/db"):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                _database_settings()
        self.assertNotIn("TopSecretPw", str(ctx.exception))
