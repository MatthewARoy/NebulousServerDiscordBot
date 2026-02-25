# Database Lock Issue - Fix Guide

## Problem Identified

Your persistence is **correctly configured**, but the database file is **empty (0 bytes)** and SQLite is getting "database is locked" errors. This is a known issue with SQLite on Azure Files (network storage).

## Root Cause

1. ✅ Volume mount is configured correctly
2. ✅ DB_PATH environment variable is set correctly  
3. ✅ Storage account and file share exist
4. ❌ Database file exists but is **0 bytes** (empty/corrupted)
5. ❌ SQLite can't initialize empty database due to locking issues

## Solution

### Option 1: Delete Empty Database (Recommended)

Delete the empty database file and let it be recreated:

```bash
# Get storage key
STORAGE_KEY=$(az storage account keys list \
  --resource-group nebulous-bot-rg \
  --account-name nebulousbotstorage \
  --query '[0].value' -o tsv)

# Delete the empty database file
az storage file delete \
  --share-name botdata \
  --path db.sqlite3 \
  --account-name nebulousbotstorage \
  --account-key "$STORAGE_KEY"
```

Then restart the container app:

```bash
az containerapp revision restart \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg
```

The database will be automatically recreated and initialized on next startup.

### Option 2: Use the Fix Script

Run the automated fix script:

```bash
./deployment/scripts/fix-database-lock.sh
```

This will:
- Check for and remove lock files
- Detect empty database
- Offer to delete it
- Provide next steps

### Option 3: Redeploy

Simply redeploy - the empty database will be replaced:

```bash
./deployment/scripts/deploy-azure.sh
```

## Why This Happened

The database file was likely created but never properly initialized with migrations. This can happen when:
- Container restarts during migration
- Network latency causes SQLite locking issues
- Multiple processes try to access the database simultaneously

## Prevention

The current setup already has:
- ✅ Retry logic for migrations (5 attempts)
- ✅ SQLite configured for network storage (DELETE journal mode, 30s timeout)
- ✅ Proper volume mounting

The issue was likely a one-time initialization problem. Once the database is properly created, it should work fine.

## Verify After Fix

After deleting and restarting, check logs:

```bash
az containerapp logs show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --tail 50 | grep -i "migration\|database"
```

You should see:
- ✅ "Migrations completed successfully"
- ✅ No "database is locked" errors
- ✅ Database file size > 0 bytes

## Check Database Size

After the fix, verify the database has data:

```bash
STORAGE_KEY=$(az storage account keys list \
  --resource-group nebulous-bot-rg \
  --account-name nebulousbotstorage \
  --query '[0].value' -o tsv)

az storage file show \
  --share-name botdata \
  --path db.sqlite3 \
  --account-name nebulousbotstorage \
  --account-key "$STORAGE_KEY" \
  --query "properties.contentLength" -o tsv
```

Should show a size > 0 (typically several KB after migrations).

