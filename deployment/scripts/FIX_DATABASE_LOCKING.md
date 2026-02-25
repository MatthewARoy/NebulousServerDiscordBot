# Fixing Database Locking and Migration Failures

## Problem

SQLite database on Azure Files (network storage) experiences locking issues during migrations, causing:
- Migration failures with "database is locked" errors
- Container startup failures
- Unhealthy revisions

## Root Cause

1. **SQLite on Network Storage**: Azure Files has network latency and can cause SQLite locking issues
2. **Concurrent Access**: Multiple processes or retries can lock the database
3. **Insufficient Retry Logic**: Previous retry logic was too simple

## Fixes Applied

### 1. Improved Startup Script (`start-server.sh`)

**Enhanced Migration Retry Logic:**
- Increased retries from 5 to 10 attempts
- Added exponential backoff (2s, 4s, 6s, etc.)
- Added database lock check before attempting migration
- Better error messages with diagnostic information

**Database Safety Checks:**
- Verifies database directory exists and is writable
- Checks if existing database file exists before migrations
- Preserves existing database files
- Waits for Azure Files mount to stabilize

### 2. SQLite Configuration (Already in `settings.py`)

The database is already configured with:
- **Timeout**: 30 seconds (increased from default 5s)
- **Journal Mode**: DELETE (safer for network storage than WAL)
- **Busy Timeout**: 30 seconds

## Verification

After deployment, verify database persistence:

```bash
./deployment/scripts/verify-database-persistence.sh
```

This checks:
- Volume mount is configured
- DB_PATH environment variable is set
- Database file exists and has data

## Preventing Database Wipes

### Ensure Persistent Storage is Configured

1. **Check if configured:**
   ```bash
   ./deployment/scripts/check-persistence.sh
   ```

2. **If not configured, set it up:**
   ```bash
   ./deployment/scripts/setup-persistent-storage.sh
   ```

3. **Verify after setup:**
   - Go to Azure Portal
   - Container App → Containers → Volume mounts
   - Should see: `botdata-storage` → `/mnt/data`
   - Environment variable: `DB_PATH=/mnt/data/db.sqlite3`

### Database Location

- **Without persistence**: `/app/db.sqlite3` (ephemeral, wiped on deploy)
- **With persistence**: `/mnt/data/db.sqlite3` (persists across deploys)

## Troubleshooting

### Migration Still Failing?

1. **Check logs:**
   ```bash
   az containerapp logs show \
     --name nebulous-discord-bot \
     --resource-group nebulous-bot-rg \
     --tail 100
   ```

2. **Check database file:**
   ```bash
   az containerapp exec \
     --name nebulous-discord-bot \
     --resource-group nebulous-bot-rg \
     --command "ls -lh /mnt/data/db.sqlite3"
   ```

3. **Check permissions:**
   ```bash
   az containerapp exec \
     --name nebulous-discord-bot \
     --resource-group nebulous-bot-rg \
     --command "ls -ld /mnt/data"
   ```

### Database Locked Error

If you see "database is locked" errors:

1. **Wait and retry**: The script now has better retry logic
2. **Check for multiple instances**: Ensure only one replica is running
3. **Check Azure Files**: Network storage might be slow or unavailable

### Database Wiped After Deployment

If database is wiped:

1. **Check persistent storage:**
   ```bash
   ./deployment/scripts/check-persistence.sh
   ```

2. **Verify volume mount in Azure Portal:**
   - Container App → Containers → Volume mounts
   - Must have: `botdata-storage` mounted to `/mnt/data`

3. **Check DB_PATH environment variable:**
   ```bash
   az containerapp show \
     --name nebulous-discord-bot \
     --resource-group nebulous-bot-rg \
     --query "properties.template.containers[0].env[?name=='DB_PATH']"
   ```

## Best Practices

1. **Always use persistent storage in production**
2. **Backup database before major deployments**
3. **Monitor migration logs for issues**
4. **Consider PostgreSQL for production** (better for network storage)

## Next Steps

1. ✅ Startup script improved with better retry logic
2. ✅ Database safety checks added
3. ⚠️  **Verify persistent storage is configured** (run `check-persistence.sh`)
4. ⚠️  **Redeploy** to apply fixes

