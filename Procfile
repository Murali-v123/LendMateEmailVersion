# Process types for Heroku-style platforms. Render uses render.yaml instead.
# Run migrations once per release, before the web processes start:
#   release: python manage.py migrate --noinput
release: python manage.py migrate --noinput
web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 120
worker: celery -A config worker --loglevel=info --concurrency=2
# Run exactly one beat process; two beats send every reminder twice.
beat: celery -A config beat --loglevel=info
