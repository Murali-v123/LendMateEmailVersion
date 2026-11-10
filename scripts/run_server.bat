@echo off
REM Start LendMate Django Development Web Server
cd /d "%~dp0.."
call venv\Scripts\activate.bat
python manage.py runserver
