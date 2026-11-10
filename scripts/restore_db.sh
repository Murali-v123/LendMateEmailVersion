#!/usr/bin/env bash
# Restore a LendMate PostgreSQL backup (custom format from backup_db.sh).
# DESTRUCTIVE: replaces the contents of the target database.
# Usage: scripts/restore_db.sh backups/lendmate_YYYYMMDD_HHMMSS.dump
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <backup-file.dump>" >&2
  exit 1
fi
BACKUP_FILE="$1"
[ -f "$BACKUP_FILE" ] || { echo "Backup file not found: $BACKUP_FILE" >&2; exit 1; }

cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi

DB_USER="${POSTGRES_USER:-lendmate}"
DB_HOST="${POSTGRES_HOST:-127.0.0.1}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-lendmate}"

read -r -p "This replaces all data in '$DB_NAME' on $DB_HOST. Type RESTORE to continue: " CONFIRM
[ "$CONFIRM" = "RESTORE" ] || { echo "Cancelled."; exit 1; }

export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"
pg_restore --clean --if-exists --no-owner --no-privileges \
  -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  "$BACKUP_FILE"
unset PGPASSWORD
echo "Restore finished. Run: python manage.py migrate --noinput"
