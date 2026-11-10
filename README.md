# LendMate · Personal Lending & Repayment Management System

LendMate is a private money-lending ledger web application designed for personal lenders who manage loans to friends, family, or private borrowers. Borrowers do not require user accounts—only the lender logs in to record loans, track repayments, generate automated monthly payment schedules, and monitor outbound email updates.

---

## 1. Technologies Used

- **Backend**: Python 3.11+, Django 5.2, Gunicorn
- **Database**: PostgreSQL 16
- **Task Queue & Broker**: Celery 5.4+, Redis 6.1+
- **Frontend**: Django Templates, Bootstrap 5.3, Custom LendMate CSS (Warm luxury editorial design)
- **Email Notifications**: Durable email queue with retries, borrower reminders (upcoming, due today, overdue), and loan event emails via Django's mail backend (SMTP in production)
- **Deployment**: Render (Blueprint), Docker, Docker Compose

---

## 2. Project Folder Structure

```
LendMate/
│
├── frontend/                     # FRONTEND TIER (UI & Presentation)
│   ├── templates/                # HTML templates grouped by app
│   │   ├── accounts/             # Login, register, password change
│   │   ├── core/                 # Dashboard and settings UI
│   │   ├── layouts/              # Base shell, topbars, sidebar frames
│   │   ├── lending/              # Borrowers, loans, payments, trackers
│   │   ├── notifications/        # Outbound email history & retry dashboard
│   │   ├── partials/             # Navigation links, messages, form helpers
│   │   └── registration/         # Password reset flow
│   │
│   └── static/                   # Static files (CSS, JS, Images, Favicon)
│       ├── css/                  # Custom stylesheet (lendmate.css)
│       ├── js/                   # Client-side JavaScript helpers
│       ├── img/                  # Logos and marks (SVG)
│       └── favicon/              # Browser tab icon
│
├── accounts/                     # BACKEND: Authentication, accounts, passwords
├── core/                         # BACKEND: Dashboard KPIs, user preferences
├── lending/                      # BACKEND: Borrowers, loans, payments, monthly trackers
├── notifications/                # BACKEND: email queue, templates, mail adapter, Celery tasks
├── config/                       # BACKEND: Django settings, urls, wsgi, asgi, celery
│
├── docs/                         # DOCUMENTATION GUIDES
│   ├── PROJECT_STRUCTURE.md      # Detailed map of every file
│   ├── FRONTEND_GUIDE.md         # Where to modify UI, CSS, and templates
│   ├── BACKEND_GUIDE.md          # Where to modify views, calculations, logic
│   ├── DATABASE_GUIDE.md         # Models, migrations, PostgreSQL backup/restore
│   └── DEPLOYMENT_GUIDE.md       # Render, Docker and local setup
│
├── scripts/                      # HELPER AUTOMATION SCRIPTS
│   ├── run_server.bat / .sh      # Launch web server
│   ├── run_worker.bat / .sh      # Launch Celery worker
│   ├── run_beat.bat / .sh        # Launch Celery Beat scheduler
│   ├── run_tests.bat / .sh       # Run full test suite
│   └── backup_db.bat / .sh       # PostgreSQL database dump (pg_dump)
│
├── tests/                        # Integration and end-to-end smoke tests
├── manage.py                     # Django management entry point
├── requirements.txt              # Pinned Python dependencies
├── .env.example                  # Environment variable reference
├── .gitignore                    # Git exclusions
└── README.md                     # Project overview (this file)
```

---

## 3. Quick Reference: Where is Everything?

| Component | Directory Location |
| :--- | :--- |
| **Frontend Templates** | `frontend/templates/` |
| **Frontend Styles & Images** | `frontend/static/` |
| **Backend Business Logic** | `accounts/`, `core/`, `lending/`, `notifications/` |
| **Database Models** | `core/models.py`, `lending/models.py`, `notifications/models.py` |
| **Database Migrations** | `<app_name>/migrations/` (e.g. `lending/migrations/`, `notifications/migrations/`) |
| **Email Notification Logic & Adapter** | `notifications/email_backend.py`, `notifications/service.py` |
| **Email Message Templates** | `notifications/templates_email.py` |
| **Background Tasks & Scheduler** | `notifications/tasks.py` and `config/celery.py` |

---

## 4. Local Installation & Setup

### Step 1: Install Python Dependencies
```bash
# Windows:
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Linux / macOS:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
Copy `.env.example` to `.env` and fill in your PostgreSQL credentials:
```bash
cp .env.example .env
```
Key settings in `.env`:
```ini
DJANGO_SECRET_KEY=your-random-secret-key
DJANGO_DEBUG=true
POSTGRES_DB=lendmate
POSTGRES_USER=lendmate
POSTGRES_PASSWORD=your_database_password
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
REDIS_URL=redis://127.0.0.1:6379/0
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

### Step 3: Run Database Migrations
```bash
python manage.py migrate
```

---

## 5. Running LendMate Locally

### A. Start the Web Server
```bash
# Using Python directly:
python manage.py runserver

# Or using the helper script:
scripts\run_server.bat        # Windows
./scripts/run_server.sh       # Linux / macOS
```
Visit: `http://localhost:8000`

### B. Start the Celery Worker (for Background Email)
In a second terminal window:
```bash
# Windows (requires solo pool):
celery -A config worker --loglevel=info --pool=solo

# Linux / macOS / Docker:
celery -A config worker --loglevel=info --concurrency=2

# Or using the helper script:
scripts\run_worker.bat        # Windows
./scripts/run_worker.sh       # Linux / macOS
```

### C. Start the Celery Beat Scheduler (for Periodic Reminders)
In a third terminal window:
```bash
celery -A config beat --loglevel=info

# Or using the helper script:
scripts\run_beat.bat          # Windows
./scripts/run_beat.sh         # Linux / macOS
```

---

## 6. Running with Docker Compose (All 5 Services)

To run Django, PostgreSQL, Redis, Celery Worker, and Celery Beat in containers with a single command:
```bash
docker compose up --build
```
Access the application at `http://localhost:8000`. Health check: `http://localhost:8000/health/`.

---

## 7. Running the Automated Tests

LendMate includes comprehensive tests covering loan calculations, trackers, consent, email queue, retries, and frontend template resolution:
```bash
# Run notification tests (63 tests):
python manage.py test notifications

# Run integration smoke tests:
python manage.py test tests

# Or run the helper script:
scripts\run_tests.bat         # Windows
./scripts/run_tests.sh        # Linux / macOS
```
