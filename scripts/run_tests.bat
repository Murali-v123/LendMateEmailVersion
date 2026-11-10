@echo off
REM Run LendMate Django Test Suite
cd /d "%~dp0.."
call venv\Scripts\activate.bat
REM Tests render templates that use the manifest static storage, so collect first.
set DJANGO_DEBUG=true
python manage.py collectstatic --noinput
python manage.py test notifications accounts core lending tests
