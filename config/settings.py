"""
LendMate settings.

Secrets and environment-specific values come from environment variables.
In development they are loaded from a local .env file. Nothing sensitive is
hardcoded here.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.environ.get(name, "true" if default else "false")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# --- Core -----------------------------------------------------------------

DEBUG = env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")

# Reject blank, placeholder, and known development keys in any mode.
_KNOWN_INSECURE_KEYS = {
    "",
    "insecure-development-key-do-not-use-in-production",
    "replace-with-a-long-random-string",
    "build-only-key",
    "your-secret-key-here",
    "changeme",
}
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")
    SECRET_KEY = "insecure-development-key-do-not-use-in-production"
elif SECRET_KEY in _KNOWN_INSECURE_KEYS and not DEBUG:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is a placeholder value. Set a real secret key for production."
    )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Render provides its public hostname automatically; add it when present.
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _render_host:
    if _render_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_render_host)
    _render_origin = f"https://{_render_host}"
    if _render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_render_origin)

# --- Self-registration control -------------------------------------------
# Disabled by default. Enable only when you explicitly want public sign-up.
ALLOW_SELF_REGISTRATION = env_bool("ALLOW_SELF_REGISTRATION", default=False)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "core",
    "notifications.apps.NotificationsConfig",
    "lending.apps.LendingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "frontend" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database (PostgreSQL) -------------------------------------------------
#
# Two ways to configure the database, in this order of precedence:
#   1. DATABASE_URL  e.g. postgresql://user:pass@host:5432/dbname
#      Used on Render (the Render Postgres connection string is provided as-is).
#      Percent-encoded characters in the password are decoded correctly, so a
#      password containing '@', '/' or ':' works when it is URL-encoded.
#   2. POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST / POSTGRES_PORT
#      Used for local development and docker-compose.
#
# An empty password is refused.  Earlier versions silently connected with an
# empty password when the variable was missing, which produced confusing
# "Access denied" errors.

from urllib.parse import unquote, urlsplit  # noqa: E402


def _database_settings():
    url = os.environ.get("DATABASE_URL", "").strip()

    if url:
        parts = urlsplit(url)
        if parts.scheme not in ("postgres", "postgresql"):
            raise ImproperlyConfigured(
                "DATABASE_URL must start with postgresql:// (got a different scheme)."
            )
        name = unquote(parts.path.lstrip("/"))
        user = unquote(parts.username or "")
        password = unquote(parts.password or "")
        host = parts.hostname or ""
        port = str(parts.port or 5432)
        # Hosted databases (Render) require TLS; local servers usually do not offer it.
        default_sslmode = "require"
    else:
        name = os.environ.get("POSTGRES_DB", "lendmate")
        user = os.environ.get("POSTGRES_USER", "lendmate")
        password = os.environ.get("POSTGRES_PASSWORD", "")
        host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
        port = os.environ.get("POSTGRES_PORT", "5432")
        default_sslmode = "prefer"

    if not user or not name or not host:
        raise ImproperlyConfigured(
            "Database is not configured. Set DATABASE_URL, or POSTGRES_DB, "
            "POSTGRES_USER and POSTGRES_HOST."
        )
    if not password:
        raise ImproperlyConfigured(
            "Database password is empty. Set DATABASE_URL with a password, or POSTGRES_PASSWORD."
        )

    sslmode = os.environ.get("DB_SSLMODE", default_sslmode).strip() or default_sslmode
    if sslmode not in ("disable", "allow", "prefer", "require", "verify-ca", "verify-full"):
        raise ImproperlyConfigured(f"DB_SSLMODE has an unknown value: {sslmode!r}.")

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": user,
        "PASSWORD": password,
        "HOST": host,
        "PORT": port,
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"sslmode": sslmode},
    }


DATABASES = {"default": _database_settings()}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Caching (used for login throttling) ---------------------------------

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "socket_connect_timeout": 2,
            "socket_timeout": 2,
        },
        # If Redis is unavailable, fall through gracefully (login still works;
        # throttle will not apply). This is a documented fail-open behaviour.
        # To fail-closed instead, replace with a dummy backend that always fails.
    },
    # Fallback in-memory cache used by login throttle when Redis is down.
    "locmem": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    },
}

# --- Authentication -------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# Login brute-force throttle settings (used by ThrottledLoginView)
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "900"))  # 15 min

# --- Internationalisation -------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Kolkata")  # Indian lenders and borrowers
USE_I18N = True
USE_TZ = True

# --- Static files ---------------------------------------------------------

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "frontend" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise compression and storage configuration (Django 5.2 STORAGES)
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# --- Email (password reset) ----------------------------------------------

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
if not DEBUG and EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
    raise ImproperlyConfigured(
        "EMAIL_BACKEND is set to the console backend while DJANGO_DEBUG is off. "
        "Explicitly configure a production email backend (e.g. SMTP) or set EMAIL_BACKEND in your environment."
    )
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "LendMate <no-reply@lendmate.local>")

# --- Celery ---------------------------------------------------------------

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60
CELERY_TASK_SOFT_TIME_LIMIT = 45
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ACKS_LATE = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

from celery.schedules import crontab  # noqa: E402

# --- Reminder schedule (all configurable by environment variable) -------------
# Days before a due date that the borrower and lender get an upcoming reminder.
REMINDER_UPCOMING_DAYS = int(os.environ.get("REMINDER_UPCOMING_DAYS", "5"))
# Repeat overdue reminders every N days after the first one. 0 = send once only.
REMINDER_OVERDUE_REPEAT_DAYS = int(os.environ.get("REMINDER_OVERDUE_REPEAT_DAYS", "7"))
# Stop sending overdue reminders this many days after the due date.
REMINDER_OVERDUE_LOOKBACK_DAYS = int(os.environ.get("REMINDER_OVERDUE_LOOKBACK_DAYS", "30"))
# Daily send times, HH:MM in TIME_ZONE.
REMINDER_UPCOMING_TIME = os.environ.get("REMINDER_UPCOMING_TIME", "09:00")
REMINDER_OVERDUE_TIME = os.environ.get("REMINDER_OVERDUE_TIME", "10:00")


def _parse_hhmm(value, setting_name):
    try:
        hour, minute = (int(part) for part in value.split(":"))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (ValueError, AttributeError):
        pass
    raise ImproperlyConfigured(
        f"{setting_name} must be a time in HH:MM format, for example 09:00. Got {value!r}."
    )


if REMINDER_UPCOMING_DAYS < 0:
    raise ImproperlyConfigured("REMINDER_UPCOMING_DAYS cannot be negative.")
if REMINDER_OVERDUE_REPEAT_DAYS < 0:
    raise ImproperlyConfigured("REMINDER_OVERDUE_REPEAT_DAYS cannot be negative.")
if REMINDER_OVERDUE_LOOKBACK_DAYS < 1:
    raise ImproperlyConfigured("REMINDER_OVERDUE_LOOKBACK_DAYS must be at least 1.")

_upcoming_hour, _upcoming_minute = _parse_hhmm(REMINDER_UPCOMING_TIME, "REMINDER_UPCOMING_TIME")
_overdue_hour, _overdue_minute = _parse_hhmm(REMINDER_OVERDUE_TIME, "REMINDER_OVERDUE_TIME")

CELERY_BEAT_SCHEDULE = {
    "upcoming-reminders": {
        "task": "notifications.tasks.send_upcoming_reminders",
        "schedule": crontab(hour=_upcoming_hour, minute=_upcoming_minute),
    },
    "overdue-reminders": {
        "task": "notifications.tasks.send_overdue_reminders",
        "schedule": crontab(hour=_overdue_hour, minute=_overdue_minute),
    },
    "recover-stuck": {
        "task": "notifications.tasks.recover_stuck_notifications",
        "schedule": crontab(minute="*/15"),
    },
    "dispatch-pending": {
        "task": "notifications.tasks.dispatch_pending_notifications",
        "schedule": crontab(minute="*/5"),
    },
}

# --- Proxy / HTTPS trust --------------------------------------------------

# Only trust forwarded headers when explicitly configured AND a trusted proxy
# is in front. Never enable this without a correctly configured reverse proxy.
TRUST_PROXY_HEADERS = env_bool("TRUST_PROXY_HEADERS", default=False)

# --- Session --------------------------------------------------------------

SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", str(60 * 60 * 12)))  # 12 hours

# --- Logging --------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "notifications": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "lending": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# --- Security hardening outside development ------------------------------

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Only trust X-Forwarded-Proto when behind a known, trusted proxy.
    if TRUST_PROXY_HEADERS:
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # SECURE_SSL_REDIRECT defaults to False unless explicitly enabled or behind trusted proxy,
    # preventing infinite redirect loops behind Render's proxy and allowing local Docker HTTP testing.
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=False)
    # Exempt the health endpoint so load-balancers can reach it over HTTP.
    SECURE_REDIRECT_EXEMPT = [r"^health/$"]

    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", str(60 * 60 * 24 * 365)))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", default=False)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
