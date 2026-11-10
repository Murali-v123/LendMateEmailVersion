@echo off
REM Timestamped PostgreSQL backup for LendMate (Windows).
REM Reads POSTGRES_* from the environment. Run from anywhere; paths are relative to the project.
setlocal
cd /d "%~dp0\.."

if not defined POSTGRES_USER set POSTGRES_USER=lendmate
if not defined POSTGRES_HOST set POSTGRES_HOST=127.0.0.1
if not defined POSTGRES_PORT set POSTGRES_PORT=5432
if not defined POSTGRES_DB set POSTGRES_DB=lendmate
if not defined POSTGRES_PASSWORD (
  echo POSTGRES_PASSWORD must be set in the environment.
  exit /b 1
)

if not exist backups mkdir backups
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set STAMP=%%i
set OUT=backups\lendmate_%STAMP%.dump

set PGPASSWORD=%POSTGRES_PASSWORD%
pg_dump --format=custom --no-owner --no-privileges -h %POSTGRES_HOST% -p %POSTGRES_PORT% -U %POSTGRES_USER% -d %POSTGRES_DB% -f "%OUT%"
set PGPASSWORD=

echo Backup written to %OUT%
echo Keep backups outside the project folder and out of version control.
endlocal
