"""
core/checks.py — Django system checks for production safety.

These run via: python manage.py check --deploy
They warn about configuration problems before they cause incidents.
"""
from django.conf import settings
from django.core.checks import Error, Warning, register, Tags


@register(Tags.security, deploy=True)
def check_secret_key(app_configs, **kwargs):
    errors = []
    _bad = {
        "",
        "insecure-development-key-do-not-use-in-production",
        "replace-with-a-long-random-string",
        "build-only-key",
        "your-secret-key-here",
        "changeme",
    }
    key = getattr(settings, "SECRET_KEY", "")
    if not key or key in _bad:
        errors.append(Error(
            "SECRET_KEY is missing or is a placeholder value.",
            hint="Set DJANGO_SECRET_KEY to a long random string in production.",
            id="lendmate.E001",
        ))
    elif len(key) < 50:
        errors.append(Warning(
            "SECRET_KEY appears too short (< 50 characters).",
            hint="Use a long random secret key in production.",
            id="lendmate.W001",
        ))
    return errors


@register(Tags.security, deploy=True)
def check_debug_off(app_configs, **kwargs):
    errors = []
    if getattr(settings, "DEBUG", True):
        errors.append(Error(
            "DEBUG is True in a deployment check.",
            hint="Set DJANGO_DEBUG=false in production.",
            id="lendmate.E002",
        ))
    return errors


@register(Tags.security, deploy=True)
def check_allowed_hosts(app_configs, **kwargs):
    errors = []
    hosts = getattr(settings, "ALLOWED_HOSTS", [])
    if not hosts or hosts == ["*"]:
        errors.append(Error(
            "ALLOWED_HOSTS is empty or set to wildcard.",
            hint="Set DJANGO_ALLOWED_HOSTS to your production domain(s).",
            id="lendmate.E003",
        ))
    return errors


@register(Tags.security, deploy=True)
def check_registration_disabled(app_configs, **kwargs):
    errors = []
    if getattr(settings, "ALLOW_SELF_REGISTRATION", False):
        errors.append(Warning(
            "Self-registration is enabled (ALLOW_SELF_REGISTRATION=true).",
            hint="Disable public registration in production unless intentional.",
            id="lendmate.W002",
        ))
    return errors


@register(Tags.security, deploy=True)
def check_email_backend(app_configs, **kwargs):
    errors = []
    backend = getattr(settings, "EMAIL_BACKEND", "")
    if "console" in backend.lower():
        errors.append(Warning(
            "EMAIL_BACKEND is set to console backend.",
            hint="Configure a real email backend for production password resets.",
            id="lendmate.W003",
        ))
    return errors


@register(Tags.security, deploy=True)
def check_proxy_headers(app_configs, **kwargs):
    """Warn if SECURE_PROXY_SSL_HEADER is set without TRUST_PROXY_HEADERS."""
    errors = []
    proxy_ssl = getattr(settings, "SECURE_PROXY_SSL_HEADER", None)
    trust = getattr(settings, "TRUST_PROXY_HEADERS", False)
    if proxy_ssl and not trust:
        errors.append(Warning(
            "SECURE_PROXY_SSL_HEADER is set but TRUST_PROXY_HEADERS is False.",
            hint="Set TRUST_PROXY_HEADERS=true only when behind a trusted reverse proxy.",
            id="lendmate.W004",
        ))
    return errors


@register(Tags.security, deploy=True)
def check_email_settings(app_configs, **kwargs):
    """Warn about email settings that would stop borrower notifications from being delivered."""
    errors = []
    backend = getattr(settings, "EMAIL_BACKEND", "") or ""

    if backend.endswith("console.EmailBackend") or backend.endswith("locmem.EmailBackend"):
        errors.append(Warning(
            "EMAIL_BACKEND is a development backend, so borrower emails are not delivered.",
            hint="Set EMAIL_BACKEND to django.core.mail.backends.smtp.EmailBackend in production.",
            id="lendmate.W005",
        ))

    if not (getattr(settings, "DEFAULT_FROM_EMAIL", "") or "").strip():
        errors.append(Warning(
            "DEFAULT_FROM_EMAIL is empty.",
            hint="Set DEFAULT_FROM_EMAIL to the sender address your mail server allows.",
            id="lendmate.W006",
        ))

    if backend.endswith("smtp.EmailBackend"):
        if getattr(settings, "EMAIL_HOST", "") in ("", "localhost", "smtp.example.com"):
            errors.append(Warning(
                "EMAIL_HOST is not set to your mail server.",
                hint="Set EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER and EMAIL_HOST_PASSWORD.",
                id="lendmate.W007",
            ))
        if not (getattr(settings, "EMAIL_HOST_USER", "") or "").strip():
            errors.append(Warning(
                "EMAIL_HOST_USER is empty, so SMTP sending may be refused.",
                hint="Set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD for your mail provider.",
                id="lendmate.W008",
            ))
    return errors
