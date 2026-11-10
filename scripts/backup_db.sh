#!/usr/bin/env bash
# Timestamped PostgreSQL backup for LendMate.
# Uses the POSTGRES_* variables from the environment (or .env in the project root).
# The password is passed through PGPASSWORD, never on the command line.
set -euo pipefail

cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi

DB_USER="${POSTGRES_USER:-lendmate}"
DB_HOST="${POSTGRES_HOST:-127.0.0.1}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-lendmate}"

mkdir -p backups
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="backups/lendmate_${STAMP}.dump"

export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"
pg_dump --format=custom --no-owner --no-privileges \
  -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -f "$OUT"
unset PGPASSWORD

echo "Backup written to $OUT"
echo "Keep backups outside the project folder and out of version control."
