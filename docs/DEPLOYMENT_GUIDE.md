# LendMate Deployment Guide

LendMate runs on **Django 5.2 + PostgreSQL + Celery + Redis**, with email as the only notification channel.
This guide covers Render (production) and local development.

## What runs

| Process | Purpose | Instances |
|---|---|---|
| Web (Gunicorn) | The website and API. Health check at `/health/`. | Any number |
| Worker (Celery) | Sends emails and runs retries. | Any number |
| Beat (Celery) | Schedules reminders and recovery jobs. | **Exactly one** |
| PostgreSQL | All ledger and notification data. | 1 |
| Redis | Celery broker, result backend and login throttling cache. | 1 |

Two beat schedulers would send every reminder twice, so keep beat at one instance.

## Render (production)

`render.yaml` in the repository defines all five resources.

1. Push the repository to GitHub. Do not commit `.env`.
2. In Render: **New → Blueprint**, select the repository, and apply it.
3. Render creates `lendmate-web`, `lendmate-worker`, `lendmate-beat`, `lendmate-redis` and `lendmate-db`.
   Render generates `DJANGO_SECRET_KEY` automatically, and it stays in Render, not in the repository.
4. Open `lendmate-web` → **Environment** and enter the values marked as manual:
   - `EMAIL_HOST_USER`: your sending address (for Gmail, your Gmail address).
   - `EMAIL_HOST_PASSWORD`: an **app password** (Gmail requires one; your normal password will not work).
   - `DEFAULT_FROM_EMAIL`: the sender shown to recipients, for example `LendMate <yourname@gmail.com>`.
   Copy the same three values to `lendmate-worker` and `lendmate-beat`.
5. Wait for the first deploy. The web service runs `python manage.py migrate --noinput` before it starts (pre-deploy),
   so migrations run once per release.
6. Open `https://<your-service>.onrender.com/health/`. It should return `{"status": "ok"}`.
7. Run `python manage.py check --deploy` from the web service's **Shell** tab and resolve any errors it reports.

### Render notes

- `DATABASE_URL` and `REDIS_URL` are wired automatically from the database and key-value store.
- The public hostname is added to the allowed hosts automatically (`RENDER_EXTERNAL_HOSTNAME`).
- The `basic-256mb` database plan is paid. Hosted databases require TLS, and `DB_SSLMODE=require` is set for that.
- Pre-deploy migrations are run by the web service only. Workers and beat never run migrations.

## Local development (without Docker)

Requirements: Python 3.13, a local PostgreSQL 16 server, and Redis (optional for simple tests; Celery needs it to run).

```
python -m venv venv
venv\Scripts\activate            # Windows (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # then edit .env: set POSTGRES_PASSWORD and DJANGO_SECRET_KEY
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Set `DJANGO_DEBUG=true` for local development. Leave it `false` anywhere else.

Create the database once in PostgreSQL:

```
CREATE USER lendmate WITH PASSWORD 'your-password';
CREATE DATABASE lendmate OWNER lendmate;
```

Run the test suite with `scripts\run_tests.bat` (Windows) or `./scripts/run_tests.sh`. The scripts collect static files first.

## Local development with Docker Compose

```
copy .env.example .env           # set POSTGRES_PASSWORD, DJANGO_SECRET_KEY and the email settings
docker compose up --build -d
docker compose run --rm migrate
```

Open `http://localhost:8000`. Only the web service is exposed. PostgreSQL and Redis stay inside the Docker network.

## Email setup

Borrowers receive email only when they have given consent and have an address on file. Lenders
receive their own copies when their alert switch is on.

- Development: `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` prints emails to the console.
- Production: `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` with the SMTP settings above.
  Send one test email to yourself and confirm it shows as **Sent** in the notification history.

## Reminder schedule

Set these in the environment to change timing. Defaults are shown.

| Variable | Default | Meaning |
|---|---|---|
| `REMINDER_UPCOMING_DAYS` | 5 | Days before the due date to send the upcoming reminder |
| `REMINDER_OVERDUE_REPEAT_DAYS` | 7 | Overdue reminders repeat every N days (0 = once) |
| `REMINDER_OVERDUE_LOOKBACK_DAYS` | 30 | Stop overdue reminders after N days |
| `REMINDER_UPCOMING_TIME` | 09:00 | Daily upcoming and due-today run (Asia/Kolkata) |
| `REMINDER_OVERDUE_TIME` | 10:00 | Daily overdue run (Asia/Kolkata) |

## Backups

Use `scripts/backup_db.sh` or `scripts/backup_db.bat` to create a timestamped `pg_dump` file in `backups/`.
Restore with `scripts/restore_db.sh` or `.bat`, which asks for confirmation first. Restores replace data, so take a
backup first. Store backups outside the project folder.
