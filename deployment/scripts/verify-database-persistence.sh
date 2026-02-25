#!/bin/bash
# Script to verify database persistence is working correctly
# Run this after deployment to ensure database wasn't wiped

CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-nebulous-discord-bot}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"

echo "🔍 Verifying Database Persistence"
echo "=================================="
echo ""

# Check if persistent storage is configured
echo "1️⃣  Checking persistent storage configuration..."
VOLUME_MOUNTS=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.template.containers[0].volumeMounts" -o json 2>/dev/null)

if echo "$VOLUME_MOUNTS" | grep -q "/mnt/data"; then
  echo "   ✅ Volume mount configured for /mnt/data"
else
  echo "   ❌ No volume mount found for /mnt/data"
  echo "   Database will be wiped on each deployment!"
  echo ""
  echo "   To fix, run: ./deployment/scripts/setup-persistent-storage.sh"
  exit 1
fi

# Check DB_PATH environment variable
echo ""
echo "2️⃣  Checking DB_PATH environment variable..."
DB_PATH=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.template.containers[0].env[?name=='DB_PATH'].value" -o tsv 2>/dev/null)

if [ -n "$DB_PATH" ]; then
  echo "   ✅ DB_PATH is set: $DB_PATH"
  if [ "$DB_PATH" == "/mnt/data/db.sqlite3" ]; then
    echo "   ✅ DB_PATH is correct!"
  else
    echo "   ⚠️  DB_PATH should be '/mnt/data/db.sqlite3' but is '$DB_PATH'"
  fi
else
  echo "   ❌ DB_PATH environment variable is NOT set"
  echo "   Database will be created in ephemeral storage and wiped on deployment!"
  exit 1
fi

# Check if database file exists in persistent storage
echo ""
echo "3️⃣  Checking if database exists in persistent storage..."
DB_EXISTS=$(az containerapp exec \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --command "test -f $DB_PATH && echo 'EXISTS' || echo 'NOT_FOUND'" 2>/dev/null | grep -q "EXISTS" && echo "Yes" || echo "No")

if [ "$DB_EXISTS" == "Yes" ]; then
  echo "   ✅ Database file exists at $DB_PATH"
  
  # Get database size
  DB_SIZE=$(az containerapp exec \
    --name $CONTAINER_APP_NAME \
    --resource-group $RESOURCE_GROUP \
    --command "stat -c%s $DB_PATH 2>/dev/null || stat -f%z $DB_PATH 2>/dev/null || echo '0'" 2>/dev/null | tail -1)
  
  if [ -n "$DB_SIZE" ] && [ "$DB_SIZE" != "0" ]; then
    echo "   ✅ Database size: $DB_SIZE bytes"
  else
    echo "   ⚠️  Warning: Database file exists but appears to be empty"
  fi
else
  echo "   ⚠️  Database file not found at $DB_PATH"
  echo "   This is normal for first deployment"
fi

echo ""
echo "=================================="
echo "✅ Database persistence verification complete!"
echo ""
echo "Your database is configured to persist across deployments."

