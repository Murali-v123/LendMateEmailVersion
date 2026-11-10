@echo off
REM Start LendMate Celery Beat Task Scheduler
cd /d "%~dp0.."
call venv\Scripts\activate.bat
celery -A config beat --loglevel=info
