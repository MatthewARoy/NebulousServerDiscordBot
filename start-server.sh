#!/bin/bash
# Startup script for running both web server and bot in container
# This allows health checks while bot runs in background

set -e

echo "🚀 Starting Nebulous Discord Bot (Django)"

# Ensure persistent storage mount directory exists and has proper permissions
if [ -n "$DB_PATH" ] && [ -d "/mnt/data" ]; then
  echo "📁 Setting up persistent storage mount..."
  mkdir -p /mnt/data
  # Try to set permissions, but don't fail if we can't (mounted volumes may have fixed permissions)
  chmod 755 /mnt/data 2>/dev/null || true
  # Wait a moment for mount to stabilize (Azure Files can be slow)
  sleep 1
fi

# Run migrations with retry logic (SQLite on network storage can have locking issues)
echo "📦 Running database migrations..."
MAX_RETRIES=5
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if python manage.py migrate --noinput; then
    echo "✅ Migrations completed successfully"
    break
  else
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
      echo "⚠️  Migration failed (attempt $RETRY_COUNT/$MAX_RETRIES), retrying in 2 seconds..."
      sleep 2
    else
      echo "❌ Migration failed after $MAX_RETRIES attempts"
      exit 1
    fi
  fi
done

# Collect static files
echo "📦 Collecting static files..."
python manage.py collectstatic --noinput || true

# Start gunicorn in background for health checks
echo "🌐 Starting web server for health checks..."
gunicorn nebulous_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 1 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --daemon

# Wait for gunicorn to fully start and listen on port 8000
echo "⏳ Waiting for web server to be ready..."
sleep 3
# Check if gunicorn process is running
if pgrep -f "gunicorn.*8000" > /dev/null; then
  echo "✅ Web server is running"
else
  echo "⚠️  Warning: Web server process not found, but continuing..."
fi

# Start the Discord bot (this runs in foreground)
echo "🤖 Starting Discord bot..."
python manage.py runbot

