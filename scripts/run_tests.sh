#!/usr/bin/env bash
# Run LendMate Django Test Suite
set -e
cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true
# Tests render templates that use the manifest static storage, so collect first.
DJANGO_DEBUG=true python manage.py collectstatic --noinput
python manage.py test notifications accounts core lending tests
