# LendMate · Database & Migration Guide

This guide covers the PostgreSQL database architecture, migration records, and safe operations for LendMate.

---

## Database Configuration

LendMate uses **PostgreSQL 16** in local development, Docker and Render.

Connection settings are loaded via environment variables in `config/settings.py`:
- `POSTGRES_DB` (default: `lendmate`)
- `POSTGRES_USER` (default: `lendmate`)
- `POSTGRES_PASSWORD` (required; an empty password is refused)
- `POSTGRES_HOST` (default: `127.0.0.1`)
- `POSTGRES_PORT` (default: `5432`)
- `DATABASE_URL` (Render): `postgresql://user:password@host:port/name`. Percent-encode special characters in the password.

---

## Database Tables & Migration History

### 1. `accounts`
- Uses Django's built-in `auth_user` model.

### 2. `core`
- `core/migrations/0001_initial.py`: Creates `core_userpreferences` table (later columns `payment_reminders` and `due_date_reminders` were removed by `0003_remove_unused_reminder_preferences`).
- `core/migrations/0005_email_lender_alerts.py`: Adds the lender alert switch (`email_lender_alerts`).
- `core/migrations/0004_sms_preferences_to_email.py`: Renames the SMS preference flags to their email equivalents (data is kept).
- `core/migrations/0002_add_sms_preferences.py`: Extends `core_userpreferences` with the original notification flags:
  - `email_notifications_enabled` (master switch)
  - `email_loan_created`
  - `email_payment_received`
  - `email_upcoming_reminders`
  - `email_overdue_reminders`
  - `email_loan_closed`

### 3. `lending`
- `0001_initial.py`: Baseline `Borrower` model.
- `0002_borrower_lender.py`: Associates borrowers with authenticated lenders (`lending_borrower.lender_id`).
- `0003_loan.py`: Creates `lending_loan` table.
- `0004_payment.py`: Creates `lending_payment` table.
- `0005_loan_closed_at_borrowertracker_trackeritem.py`: Adds `closed_at` and creates custom trackers.
- `0006_borrowertracker_end_date_borrowertracker_loan_and_more.py`: Adds automatic monthly tracker support.
- `0007_payment_voiding_audit_timestamps.py`: Adds payment voiding, audit events and timestamps.
- `0008_rename_sms_consent_to_email_consent.py`: Renames `sms_consent` to `email_consent`. `mobile_number` becomes optional.
- `0009_remove_borrower_mobile_number.py`: Removes `mobile_number` from `lending_borrower`. Phone numbers are not used in the email-only version.

### 4. `notifications`
- `0001_initial_sms_notification.py`: Originally created the SMS queue table; superseded by `0004_email_notifications.py`.
- `0004_email_notifications.py`: Creates `notifications_emailnotification` and removes the SMS queue table `notifications_smsnotification`.
  Existing SMS history is not carried over. Export it first if you need the audit trail.
- `0005_emailnotification_recipient_role.py`: Adds `recipient_role` so each email records whether it went to the borrower or the lender.
  - Fields: `borrower_id`, `loan_id`, `payment_id`, `lender_id`, `notification_type`, `recipient_number`, `message`, `status`, `provider_message_id`, `attempts`, `last_error`, `event_key`, `created_at`, `sent_at`, `next_retry_at`.
  - Indexes: `(status, next_retry_at)` and `(lender, status)`.

---

## Safe Database Backup & Restore

### Backing Up Local PostgreSQL:
Using the included script:
```bash
# On Windows:
scripts\backup_db.bat

# On Linux / macOS:
./scripts/backup_db.sh
```

Or manually with `pg_dump`:
```bash
pg_dump --format=custom --no-owner -h 127.0.0.1 -U lendmate -d lendmate -f lendmate_backup.dump
```

### Restoring to PostgreSQL (Local or Render):
```bash
pg_restore --clean --if-exists --no-owner -h <HOST> -p <PORT> -U <USER> -d <DATABASE_NAME> lendmate_backup.dump
```

### Verifying Record Counts After Migration:
```sql
SELECT 'Borrowers' as model, COUNT(*) as count FROM lending_borrower
UNION ALL
SELECT 'Loans', COUNT(*) FROM lending_loan
UNION ALL
SELECT 'Payments', COUNT(*) FROM lending_payment
UNION ALL
SELECT 'Notifications', COUNT(*) FROM notifications_emailnotification;
```
