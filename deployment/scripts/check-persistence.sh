#!/bin/bash
# Script to check if database persistence is properly configured

CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-nebulous-discord-bot}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"
CONTAINER_APP_ENV="${CONTAINER_APP_ENV:-nebulous-bot-env}"

echo "🔍 Checking Database Persistence Configuration"
echo "==============================================="
echo ""

# Check if container app exists
if ! az containerapp show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP &>/dev/null; then
    echo "❌ Container app not found: $CONTAINER_APP_NAME"
    exit 1
fi

echo "1️⃣  Container App Configuration:"
echo "-----------------------------------"

# Get full container app config
echo "   Fetching container app configuration..."
CONFIG_YAML=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --output yaml)

# Check for volume mounts
echo ""
echo "2️⃣  Volume Mounts:"
echo "-----------------------------------"
if echo "$CONFIG_YAML" | grep -A 5 "volumeMounts:" | grep -q "/mnt/data"; then
    echo "   ✅ Volume mount found!"
    echo "$CONFIG_YAML" | grep -A 5 "volumeMounts:" | grep -E "(mountPath|volumeName)" | sed 's/^/      /'
else
    echo "   ❌ No volume mount found for /mnt/data"
    echo "   This is the problem - the volume isn't mounted!"
fi

# Check for volumes definition
echo ""
echo "3️⃣  Volumes Definition:"
echo "-----------------------------------"
if echo "$CONFIG_YAML" | grep -A 5 "volumes:" | grep -q "botdata-storage"; then
    echo "   ✅ Volume 'botdata-storage' is defined"
    echo "$CONFIG_YAML" | grep -A 5 "volumes:" | grep -E "(name|storageType|storageName)" | sed 's/^/      /'
else
    echo "   ❌ Volume 'botdata-storage' is NOT defined"
    echo "   The volume needs to be added to the container app template"
fi

# Check for DB_PATH environment variable
echo ""
echo "4️⃣  Environment Variables:"
echo "-----------------------------------"
DB_PATH=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.template.containers[0].env[?name=='DB_PATH'].value" \
  --output tsv 2>/dev/null)

if [ -n "$DB_PATH" ]; then
    echo "   ✅ DB_PATH is set: $DB_PATH"
    if [ "$DB_PATH" == "/mnt/data/db.sqlite3" ]; then
        echo "   ✅ DB_PATH is correct!"
    else
        echo "   ⚠️  DB_PATH should be '/mnt/data/db.sqlite3' but is '$DB_PATH'"
    fi
else
    echo "   ❌ DB_PATH environment variable is NOT set"
    echo "   This needs to be set to '/mnt/data/db.sqlite3'"
fi

# Check Container App Environment storage
echo ""
echo "5️⃣  Container App Environment Storage:"
echo "-----------------------------------"
ENV_STORAGE=$(az containerapp env storage list \
  --name $CONTAINER_APP_ENV \
  --resource-group $RESOURCE_GROUP \
  --query "[?name=='botdata-storage']" \
  --output json 2>/dev/null)

if [ -n "$ENV_STORAGE" ] && [ "$ENV_STORAGE" != "[]" ]; then
    echo "   ✅ Storage 'botdata-storage' is configured in environment"
    echo "$ENV_STORAGE" | grep -E "(name|azureFileAccountName|azureFileShareName)" | sed 's/^/      /'
else
    echo "   ❌ Storage 'botdata-storage' is NOT configured in environment"
    echo "   This needs to be set up first"
fi

# Check if storage account exists
echo ""
echo "6️⃣  Storage Account:"
echo "-----------------------------------"
STORAGE_ACCOUNT="nebulousbotstorage"
if az storage account show --name $STORAGE_ACCOUNT --resource-group $RESOURCE_GROUP &>/dev/null; then
    echo "   ✅ Storage account '$STORAGE_ACCOUNT' exists"
    
    # Check file share
    STORAGE_KEY=$(az storage account keys list \
      --resource-group $RESOURCE_GROUP \
      --account-name $STORAGE_ACCOUNT \
      --query '[0].value' -o tsv 2>/dev/null)
    
    if [ -n "$STORAGE_KEY" ]; then
        if az storage share show \
          --name botdata \
          --account-name $STORAGE_ACCOUNT \
          --account-key "$STORAGE_KEY" &>/dev/null; then
            echo "   ✅ File share 'botdata' exists"
            
            # Check if database file exists
            if az storage file exists \
              --share-name botdata \
              --path db.sqlite3 \
              --account-name $STORAGE_ACCOUNT \
              --account-key "$STORAGE_KEY" \
              --query "exists" -o tsv 2>/dev/null | grep -q "true"; then
                echo "   ✅ Database file 'db.sqlite3' exists in storage"
            else
                echo "   ⚠️  Database file 'db.sqlite3' does NOT exist in storage"
                echo "      (This is normal if persistence was just set up)"
            fi
        else
            echo "   ❌ File share 'botdata' does NOT exist"
        fi
    fi
else
    echo "   ❌ Storage account '$STORAGE_ACCOUNT' does NOT exist"
fi

# Summary
echo ""
echo "==============================================="
echo "📋 Summary:"
echo ""

ISSUES=0

if ! echo "$CONFIG_YAML" | grep -A 5 "volumeMounts:" | grep -q "/mnt/data"; then
    echo "❌ Volume mount is missing"
    ISSUES=$((ISSUES + 1))
fi

if ! echo "$CONFIG_YAML" | grep -A 5 "volumes:" | grep -q "botdata-storage"; then
    echo "❌ Volume definition is missing"
    ISSUES=$((ISSUES + 1))
fi

if [ -z "$DB_PATH" ]; then
    echo "❌ DB_PATH environment variable is missing"
    ISSUES=$((ISSUES + 1))
fi

if [ "$ISSUES" -eq 0 ]; then
    echo "✅ All persistence checks passed!"
    echo ""
    echo "However, if your database was still wiped, possible causes:"
    echo "  1. Volume mount was added after the database was created"
    echo "  2. Database was created in wrong location before persistence was set up"
    echo "  3. Container is not actually using the mounted volume"
    echo ""
    echo "To verify the container is using the persistent storage:"
    echo "  Check logs: az containerapp logs show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --tail 50"
    echo "  Look for database initialization messages"
else
    echo "❌ Found $ISSUES issue(s) with persistence configuration"
    echo ""
    echo "To fix:"
    echo "  Run: ./deployment/scripts/enable-persistence.sh"
    echo "  OR: ./deployment/scripts/setup-persistent-storage.sh"
fi

