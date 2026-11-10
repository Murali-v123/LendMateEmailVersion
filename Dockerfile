FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# psycopg[binary] ships its own libpq, so no system database packages are needed.
# wget is used by the docker-compose health check.
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user to run application processes
RUN groupadd --gid 1001 lendmate && \
    useradd --uid 1001 --gid 1001 --no-create-home --shell /bin/bash lendmate

# Install Python dependencies (as root, before switching user)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY . .

# Collect static files during build (uses a throw-away key that is never used at runtime)
RUN DJANGO_SECRET_KEY=build-only-key DJANGO_DEBUG=true \
    POSTGRES_PASSWORD=build-only \
    python manage.py collectstatic --noinput

# Fix ownership so the lendmate user can write to the directories it needs
RUN mkdir -p /app/staticfiles && \
    chown -R lendmate:lendmate /app

# Switch to the non-root user for all runtime processes
USER lendmate

EXPOSE 8000
