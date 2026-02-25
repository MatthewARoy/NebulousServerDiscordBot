#!/bin/bash
# Startup script for running both web server and bot in container
# This allows health checks while bot runs in background

set -e

echo "🚀 Starting Nebulous Discord Bot (Django)"

# Ensure persistent storage mount directory exists and has proper permissions
if [ -n "$DB_PATH" ]; then
  echo "📁 Setting up persistent storage for database..."
  DB_DIR=$(dirname "$DB_PATH")
  
  # Create directory if it doesn't exist
  if [ ! -d "$DB_DIR" ]; then
    echo "   Creating database directory: $DB_DIR"
    mkdir -p "$DB_DIR"
  fi
  
  # Check if directory is writable
  if [ ! -w "$DB_DIR" ]; then
    echo "   ⚠️  Warning: Database directory is not writable: $DB_DIR"
    echo "   Attempting to fix permissions..."
    chmod 755 "$DB_DIR" 2>/dev/null || true
  fi
  
  # Wait for mount to stabilize (Azure Files can be slow)
  if [ -d "/mnt/data" ]; then
    echo "   Waiting for Azure Files mount to stabilize..."
    sleep 3
  fi
  
  # Check if existing database file exists and is valid
  if [ -f "$DB_PATH" ]; then
    DB_SIZE=$(stat -f%z "$DB_PATH" 2>/dev/null || stat -c%s "$DB_PATH" 2>/dev/null || echo "0")
    if [ "$DB_SIZE" -gt 0 ]; then
      echo "   ✅ Found existing database ($DB_SIZE bytes) - will preserve data"
    else
      echo "   ⚠️  Warning: Database file exists but is empty"
    fi
  else
    echo "   📝 No existing database found - will create new one"
  fi
fi

# Run migrations with improved retry logic for SQLite locking issues
echo "📦 Running database migrations..."
MAX_RETRIES=10
RETRY_COUNT=0
BASE_DELAY=2

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  # Check if database is locked before attempting migration
  if [ -n "$DB_PATH" ] && [ -f "$DB_PATH" ]; then
    # Try to check if database is accessible (simple lock check)
    python3 -c "
import sqlite3
import sys
try:
    conn = sqlite3.connect('$DB_PATH', timeout=1.0)
    conn.execute('SELECT 1')
    conn.close()
    sys.exit(0)
except sqlite3.OperationalError as e:
    if 'locked' in str(e).lower():
        sys.exit(1)
    sys.exit(0)
except Exception:
    sys.exit(0)
" 2>/dev/null || {
      RETRY_COUNT=$((RETRY_COUNT + 1))
      DELAY=$((BASE_DELAY * RETRY_COUNT))
      echo "   ⚠️  Database is locked (attempt $RETRY_COUNT/$MAX_RETRIES), waiting ${DELAY}s..."
      sleep $DELAY
      continue
    }
  fi
  
  # Attempt migration
  if python manage.py migrate --noinput 2>&1; then
    echo "✅ Migrations completed successfully"
    break
  else
    MIGRATION_EXIT_CODE=$?
    RETRY_COUNT=$((RETRY_COUNT + 1))
    
    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
      # Exponential backoff with jitter
      DELAY=$((BASE_DELAY * RETRY_COUNT + (RANDOM % 3)))
      echo "   ⚠️  Migration failed (attempt $RETRY_COUNT/$MAX_RETRIES, exit code: $MIGRATION_EXIT_CODE)"
      echo "   Retrying in ${DELAY} seconds..."
      sleep $DELAY
    else
      echo "❌ Migration failed after $MAX_RETRIES attempts"
      echo ""
      echo "   Common causes:"
      echo "   - Database file is locked by another process"
      echo "   - Network storage (Azure Files) is slow or unavailable"
      echo "   - Insufficient permissions on database directory"
      echo ""
      if [ -n "$DB_PATH" ]; then
        echo "   Database path: $DB_PATH"
        echo "   Directory exists: $([ -d "$(dirname "$DB_PATH")" ] && echo 'Yes' || echo 'No')"
        echo "   Directory writable: $([ -w "$(dirname "$DB_PATH")" ] && echo 'Yes' || echo 'No')"
      fi
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

