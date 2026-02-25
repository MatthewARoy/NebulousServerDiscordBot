#!/bin/bash
# Script to fix database lock issues on Azure Files
# This removes lock files and recreates the database if needed

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"
STORAGE_ACCOUNT="nebulousbotstorage"
STORAGE_SHARE="botdata"

echo "🔧 Fixing Database Lock Issues"
echo "==============================="
echo ""

# Get storage key
STORAGE_KEY=$(az storage account keys list \
  --resource-group $RESOURCE_GROUP \
  --account-name $STORAGE_ACCOUNT \
  --query '[0].value' -o tsv)

if [ -z "$STORAGE_KEY" ]; then
    echo "❌ Failed to get storage account key"
    exit 1
fi

echo "1️⃣  Checking for lock files..."
echo "-----------------------------------"

# List all files
FILES=$(az storage file list \
  --share-name $STORAGE_SHARE \
  --account-name $STORAGE_ACCOUNT \
  --account-key "$STORAGE_KEY" \
  --output json)

# Check for lock files
LOCK_FILES=$(echo "$FILES" | jq -r '.[].name' | grep -E "\.sqlite3-(wal|shm|lock)$" || true)

if [ -n "$LOCK_FILES" ]; then
    echo "   Found lock files:"
    echo "$LOCK_FILES" | sed 's/^/      - /'
    echo ""
    echo "   Removing lock files..."
    echo "$LOCK_FILES" | while read -r file; do
        az storage file delete \
          --share-name $STORAGE_SHARE \
          --path "$file" \
          --account-name $STORAGE_ACCOUNT \
          --account-key "$STORAGE_KEY" \
          --output none 2>/dev/null && echo "      ✅ Deleted: $file" || echo "      ⚠️  Could not delete: $file"
    done
else
    echo "   ✅ No lock files found"
fi

echo ""
echo "2️⃣  Checking database file..."
echo "-----------------------------------"

DB_SIZE=$(az storage file show \
  --share-name $STORAGE_SHARE \
  --path db.sqlite3 \
  --account-name $STORAGE_ACCOUNT \
  --account-key "$STORAGE_KEY" \
  --query "properties.contentLength" -o tsv 2>/dev/null || echo "0")

if [ "$DB_SIZE" == "0" ] || [ -z "$DB_SIZE" ]; then
    echo "   ⚠️  Database file is empty (0 bytes) or doesn't exist"
    echo ""
    echo "   Options:"
    echo "   1. Delete the empty database file (will be recreated on next deployment)"
    echo "   2. Keep it (migrations will try to initialize it)"
    echo ""
    read -p "   Delete empty database file? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        az storage file delete \
          --share-name $STORAGE_SHARE \
          --path db.sqlite3 \
          --account-name $STORAGE_ACCOUNT \
          --account-key "$STORAGE_KEY" \
          --output none 2>/dev/null && echo "   ✅ Deleted empty database file" || echo "   ⚠️  Could not delete"
    else
        echo "   Keeping database file (will be initialized on next deployment)"
    fi
else
    echo "   ✅ Database file exists and has data ($DB_SIZE bytes)"
    echo "   The database should work once lock files are removed"
fi

echo ""
echo "3️⃣  Next Steps:"
echo "-----------------------------------"
echo "   1. Restart the container app to clear any in-memory locks:"
echo "      az containerapp revision restart \\"
echo "        --name nebulous-discord-bot \\"
echo "        --resource-group $RESOURCE_GROUP"
echo ""
echo "   2. Or redeploy to recreate the database:"
echo "      ./deployment/scripts/deploy-azure.sh"
echo ""
echo "   The database will be recreated/initialized on next startup"

