@echo off
REM Start LendMate Celery Asynchronous Background Worker
cd /d "%~dp0.."
call venv\Scripts\activate.bat
celery -A config worker --loglevel=info --pool=solo
