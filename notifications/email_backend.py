
"""
Email delivery adapter for LendMate.

Uses Django's configured email backend (SMTP in production,
console or locmem during development/testing).
"""

import logging
import smtplib
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email


logger = logging.getLogger(__name__)


class EmailStatus:
    SENT = "sent"
    FAILED = "failed"


@dataclass(frozen=True)
class EmailResult:
    status: str
    provider: str = "django"
    error: str = ""
    # False when a retry cannot help (bad address, empty content, permanent
    # SMTP rejection).  True for transient failures such as a dropped connection.
    retryable: bool = True

    @property
    def was_sent(self):
        # SMTP/backend acceptance, not proof of inbox delivery.
        return self.status == EmailStatus.SENT


def send_email(to_email, subject, text_body, html_body=None):
    """
    Send one email using Django's configured email backend.

    Returns EmailResult instead of raising delivery exceptions.
    """

    recipient = str(to_email or "").strip()

    if not recipient:
        return EmailResult(
            status=EmailStatus.FAILED,
            error="Recipient email address is missing.",
            retryable=False,
        )

    try:
        validate_email(recipient)
    except ValidationError:
        return EmailResult(
            status=EmailStatus.FAILED,
            error="Recipient email address is invalid.",
            retryable=False,
        )

    subject = str(subject or "").strip()

    if not subject:
        return EmailResult(
            status=EmailStatus.FAILED,
            error="Email subject is missing.",
            retryable=False,
        )

    if "\n" in subject or "\r" in subject:
        return EmailResult(
            status=EmailStatus.FAILED,
            error="Email subject contains invalid characters.",
            retryable=False,
        )

    text_body = str(text_body or "").strip()

    if not text_body:
        return EmailResult(
            status=EmailStatus.FAILED,
            error="Email message body is empty.",
            retryable=False,
        )

    from_email = getattr(
        settings,
        "DEFAULT_FROM_EMAIL",
        "",
    )

    if not from_email:
        return EmailResult(
            status=EmailStatus.FAILED,
            error="DEFAULT_FROM_EMAIL is not configured.",
            retryable=False,
        )

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=[recipient],
        )

        if html_body:
            message.attach_alternative(
                str(html_body),
                "text/html",
            )

        sent_count = message.send(fail_silently=False)

        if sent_count == 1:
            logger.info(
                "Email accepted by configured backend for %s",
                recipient,
            )
            return EmailResult(status=EmailStatus.SENT)

        return EmailResult(
            status=EmailStatus.FAILED,
            error="Email backend did not confirm sending.",
        )

    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
        logger.error("SMTP refused recipient %s: %s", recipient, exc)
        return EmailResult(
            status=EmailStatus.FAILED,
            error=str(exc)[:500],
            retryable=False,
        )

    except smtplib.SMTPResponseException as exc:
        # 5xx is a permanent rejection; 4xx is temporary and worth retrying.
        permanent = 500 <= int(exc.smtp_code or 0) < 600
        logger.error("SMTP error %s for %s: %s", exc.smtp_code, recipient, exc)
        return EmailResult(
            status=EmailStatus.FAILED,
            error=str(exc)[:500],
            retryable=not permanent,
        )

    except Exception as exc:
        # Connection drops and timeouts may have happened after the message was
        # accepted, so they are retried only as far as the task's attempt limit allows.
        logger.exception("Email sending failed for recipient %s", recipient)
        return EmailResult(
            status=EmailStatus.FAILED,
            error=str(exc)[:500],
            retryable=True,
        )
