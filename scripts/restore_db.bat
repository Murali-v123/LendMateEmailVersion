@echo off
REM Restore a LendMate PostgreSQL backup (Windows). DESTRUCTIVE: replaces the database contents.
REM Usage: scripts\restore_db.bat backups\lendmate_YYYYMMDD_HHMMSS.dump
setlocal
cd /d "%~dp0\.."

if "%~1"=="" (
  echo Usage: %~nx0 ^<backup-file.dump^>
  exit /b 1
)
if not exist "%~1" (
  echo Backup file not found: %~1
  exit /b 1
)

if not defined POSTGRES_USER set POSTGRES_USER=lendmate
if not defined POSTGRES_HOST set POSTGRES_HOST=127.0.0.1
if not defined POSTGRES_PORT set POSTGRES_PORT=5432
if not defined POSTGRES_DB set POSTGRES_DB=lendmate
if not defined POSTGRES_PASSWORD (
  echo POSTGRES_PASSWORD must be set in the environment.
  exit /b 1
)

set /p CONFIRM=This replaces all data in %POSTGRES_DB% on %POSTGRES_HOST%. Type RESTORE to continue:
if not "%CONFIRM%"=="RESTORE" (
  echo Cancelled.
  exit /b 1
)

set PGPASSWORD=%POSTGRES_PASSWORD%
pg_restore --clean --if-exists --no-owner --no-privileges -h %POSTGRES_HOST% -p %POSTGRES_PORT% -U %POSTGRES_USER% -d %POSTGRES_DB% "%~1"
set PGPASSWORD=
echo Restore finished. Run: python manage.py migrate --noinput
endlocal
