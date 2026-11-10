
"""
LendMate email templates.

Provides plain-text and HTML email content for borrowers
and lenders. All dynamic content is HTML-escaped.
"""

from decimal import Decimal
from html import escape


def _format_amount(amount):
    try:
        return f"₹{Decimal(str(amount)):,.2f}"
    except (ValueError, TypeError, ArithmeticError):
        return str(amount)


def _format_date(value):
    if not value:
        return "Not specified"

    if hasattr(value, "strftime"):
        return value.strftime("%d %b %Y")

    return str(value)


def build_email(subject, greeting, paragraphs, details=None):
    """
    Return a dictionary containing subject, text and HTML email bodies.
    """

    paragraphs = paragraphs or []
    details = details or {}

    text_lines = [greeting, ""]

    for paragraph in paragraphs:
        text_lines.extend([paragraph, ""])

    if details:
        text_lines.extend(["Details:"])

        for label, value in details.items():
            text_lines.append(f"{label}: {value}")

        text_lines.append("")

    text_lines.extend([
        "Regards,",
        "LendMate",
    ])

    text_body = "\n".join(text_lines)

    html_paragraphs = "".join(
        f"<p>{escape(str(paragraph))}</p>"
        for paragraph in paragraphs
    )

    html_details = ""

    if details:
        rows = "".join(
            f"<tr>"
            f"<td style='padding:8px;border:1px solid #ddd;'>"
            f"<strong>{escape(str(label))}</strong></td>"
            f"<td style='padding:8px;border:1px solid #ddd;'>"
            f"{escape(str(value))}</td>"
            f"</tr>"
            for label, value in details.items()
        )

        html_details = (
            "<table style='border-collapse:collapse;width:100%;"
            "margin-top:16px;'>"
            f"{rows}</table>"
        )

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family:Arial,sans-serif;color:#333;
                 line-height:1.6;max-width:600px;margin:auto;">
        <div style="background:#173b57;color:white;padding:20px;">
            <h2 style="margin:0;">LendMate</h2>
        </div>

        <div style="padding:24px;">
            <p>{escape(str(greeting))}</p>
            {html_paragraphs}
            {html_details}

            <p style="margin-top:28px;">
                Regards,<br><strong>LendMate</strong>
            </p>
        </div>

        <div style="background:#f3f4f6;padding:14px;
                    font-size:12px;color:#666;">
            This is an automated notification from LendMate.
        </div>
    </body>
    </html>
    """

    return {
        "subject": subject,
        "text": text_body,
        "html": html_body,
    }


def build_loan_created_email(loan):
    borrower = loan.borrower

    return build_email(
        subject="Your LendMate loan has been recorded",
        greeting=f"Hello {borrower.full_name},",
        paragraphs=[
            "Your loan has been successfully recorded.",
            "Please review the loan details below.",
        ],
        details={
            "Loan amount": _format_amount(loan.principal),
            "Interest rate": f"{loan.interest_rate}%",
            "Interest period": loan.get_interest_period_display(),
            "Loan date": _format_date(loan.lending_date),
            "Due date": _format_date(loan.due_date),
        },
    )


def build_payment_received_email(payment):
    loan = payment.loan
    borrower = loan.borrower

    return build_email(
        subject="Your LendMate payment has been recorded",
        greeting=f"Hello {borrower.full_name},",
        paragraphs=[
            "Your payment has been successfully recorded.",
            "Thank you for your payment.",
        ],
        details={
            "Payment amount": _format_amount(payment.amount),
            "Payment date": _format_date(payment.payment_date),
            "Principal paid": _format_amount(payment.principal_component),
            "Interest paid": _format_amount(payment.interest_component),
            "Remaining principal": _format_amount(
                loan.outstanding_principal
            ),
        },
    )


def build_loan_closed_email(loan):
    borrower = loan.borrower

    return build_email(
        subject="Your LendMate loan has been closed",
        greeting=f"Hello {borrower.full_name},",
        paragraphs=[
            "Your loan has been fully repaid and marked as closed.",
            "Thank you for settling your loan.",
        ],
        details={
            "Loan amount": _format_amount(loan.principal),
            "Loan date": _format_date(loan.lending_date),
            "Closed on": _format_date(loan.closed_at.date() if loan.closed_at else None),
        },
    )


def build_borrower_due_email(
    loan,
    due_date,
    amount,
    reminder_type="upcoming",
):
    borrower = loan.borrower

    subjects = {
        "upcoming": "Upcoming LendMate repayment reminder",
        "due_today": "Your LendMate repayment is due today",
        "overdue": "Your LendMate repayment is overdue",
    }

    messages = {
        "upcoming": (
            f"Your scheduled repayment is approaching. "
            f"Please arrange payment by {_format_date(due_date)}."
        ),
        "due_today": (
            "Your scheduled repayment is due today. "
            "Please arrange payment if you have not already paid."
        ),
        "overdue": (
            "Our records show that your scheduled repayment is overdue. "
            "Please contact your lender regarding the payment."
        ),
    }

    if reminder_type not in subjects:
        raise ValueError("Invalid borrower reminder type.")

    return build_email(
        subject=subjects[reminder_type],
        greeting=f"Hello {borrower.full_name},",
        paragraphs=[
            messages[reminder_type],
            "If you have already made this payment, please contact "
            "your lender.",
        ],
        details={
            "Loan amount": _format_amount(loan.principal),
            "Scheduled payment": _format_amount(amount),
            "Due date": _format_date(due_date),
            "Lender": (
                loan.borrower.lender.get_full_name()
                or loan.borrower.lender.get_username()
                if loan.borrower.lender else "LendMate lender"
            ),
        },
    )


def build_lender_alert_email(
    lender,
    borrower,
    loan,
    event_type,
    payment=None,
    due_date=None,
    amount=None,
):
    subjects = {
        "loan_created": "New loan recorded in LendMate",
        "upcoming": "Upcoming borrower repayment",
        "due_today": "Borrower repayment due today",
        "overdue": "Borrower repayment overdue",
        "payment_received": "Borrower payment received",
    }

    messages = {
        "loan_created": "A new loan has been recorded.",
        "upcoming": "A borrower's repayment due date is approaching.",
        "due_today": "A borrower's repayment is due today.",
        "overdue": "A borrower's repayment is overdue.",
        "payment_received": "A payment has been recorded.",
    }

    if event_type not in subjects:
        raise ValueError("Invalid lender notification type.")

    details = {
        "Borrower": borrower.full_name,
        "Loan amount": _format_amount(loan.principal),
        "Loan due date": _format_date(loan.due_date),
    }

    if due_date:
        details["Scheduled repayment date"] = _format_date(due_date)

    if amount is not None:
        details["Scheduled payment"] = _format_amount(amount)

    if payment:
        details["Payment received"] = _format_amount(payment.amount)
        details["Payment date"] = _format_date(payment.payment_date)

    return build_email(
        subject=subjects[event_type],
        greeting=f"Hello {lender.get_full_name() or lender.get_username()},",
        paragraphs=[messages[event_type]],
        details=details,
    )
