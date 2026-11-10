# LendMate · Backend Guide

This guide explains the backend architecture of LendMate, detailing where business logic, models, controllers, background workers, and third-party integrations reside.

---

## Backend Application Inventory

LendMate is composed of 5 focused Django apps:

### 1. `config/` – Application Orchestration
- `config/settings.py`: Central configuration, environment variable readers, Celery Beat crontab schedules, security flags, logging, and database connectors.
- `config/celery.py`: Celery application instance configuring Redis broker and task auto-discovery.
- `config/urls.py`: Root URL routing including admin, authentication, lending, notifications, and `/health/` health check.
- `config/wsgi.py` & `config/asgi.py`: WSGI / ASGI production deployment handlers.

### 2. `accounts/` – Identity & Security
- `accounts/views.py`: `RegisterView`, `LendMatePasswordChangeView`.
- `accounts/forms.py`: Registration and password change validation.
- `accounts/urls.py`: Account-related endpoints.

### 3. `core/` – Lender Dashboard & Preferences
- `core/models.py`: `UserPreferences` storing both reminder toggles and email notification flags (`email_notifications_enabled`, `email_loan_created`, `email_payment_received`, etc.).
- `core/views.py`: Aggregates portfolio figures (total lent, principal repaid, outstanding balance, interest collected) for the authenticated lender.
- `core/forms.py`: `ProfileForm` and `UserPreferencesForm`.

### 4. `lending/` – Financial Ledger & Loan Management
- `lending/models.py`:
  - `Borrower`: Name, contact details, notes, and `email_consent` boolean.
  - `Loan`: Principal, interest rate, monthly due day, lending date, return date, status (open/closed), and closed timestamp.
  - `Payment`: Amount, principal component, interest component, date, validation checks ensuring principal paid cannot exceed total balance.
  - `BorrowerTracker` & `TrackerItem`: Custom and automated monthly tracking checklists.
- `lending/views.py`: Borrower CRUD, Loan CRUD, Payment entry, Loan closing/reopening, Tracker generators, and safe notification trigger invocations.

### 5. `notifications/` – email Notification Queue & Workers
- `notifications/models.py`: `EmailNotification` model. Durable queue surviving restarts with statuses (`pending`, `processing`, `sent`, `failed`, `suppressed`), retry counters, error logs, and SHA-256 idempotency `event_key`.
- `notifications/service.py`: Enqueue service verifying borrower consent, lender master switch, category preferences, and borrower email format before enqueuing.
- `notifications/tasks.py`: Celery tasks:
  - `send_email_notification`: Row-locking message sender with exponential backoff.
  - `send_upcoming_reminders`: Daily task queuing upcoming reminders (`REMINDER_UPCOMING_DAYS`, default 5) and due-today reminders, plus a lender copy of each.
  - `send_overdue_reminders`: Daily task queuing overdue reminders, repeating every `REMINDER_OVERDUE_REPEAT_DAYS` (default 7) for up to `REMINDER_OVERDUE_LOOKBACK_DAYS` (default 30).
  - `send_overdue_reminders`: Scheduled task finding unpaid loans past their due day.
  - `recover_stuck_notifications`: Maintenance task rescuing worker crashes.
- `notifications/email_backend.py`: Mail adapter built on Django's configured email backend. Returns a result flagged as retryable or final, so the sender knows whether a retry is safe.
- `notifications/templates_email.py`: The 5 domain-populated email templates.

---

## Where to Make Common Backend Changes

| Goal | Files to modify |
| :--- | :--- |
| **Change email message wording** | `notifications/templates_email.py` |
| **Add a new email provider (e.g. Twilio)** | Subclass `BaseemailBackend` in `notifications/email_backend.py` and set `email_BACKEND` |
| **Modify loan interest calculation** | `lending/models.py` (`outstanding_principal` property) and `notifications/tasks.py` (`_calculate_monthly_payment`) |
| **Change reminder lead time, repeat frequency or send times** | `.env` (`REMINDER_UPCOMING_DAYS`, `REMINDER_OVERDUE_REPEAT_DAYS`, `REMINDER_OVERDUE_LOOKBACK_DAYS`, `REMINDER_UPCOMING_TIME`, `REMINDER_OVERDUE_TIME`); defaults in `config/settings.py` |
| **Change Celery Beat scheduled times** | `config/settings.py` (`CELERY_BEAT_SCHEDULE`) |
| **Add validation to payments or loans** | `lending/forms.py` and `lending/models.py` |
| **Add new notification events** | Add type to `notifications/models.py`, create template in `notifications/templates_email.py`, and create helper in `notifications/service.py` |
