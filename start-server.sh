#!/bin/bash
# Startup script for running both web server and bot in container
# This allows health checks while bot runs in background

set -e

echo "🚀 Starting Nebulous Discord Bot (Django)"

# Run migrations
echo "📦 Running database migrations..."
python manage.py migrate --noinput

# Collect static files
echo "📦 Collecting static files..."
python manage.py collectstatic --noinput || true

# Start gunicorn in background for health checks
echo "🌐 Starting web server for health checks..."
gunicorn nebulous_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --daemon

# Give gunicorn a moment to start
sleep 2

# Start the Discord bot (this runs in foreground)
echo "🤖 Starting Discord bot..."
python manage.py runbot

