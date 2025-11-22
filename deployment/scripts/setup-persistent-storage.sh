#!/bin/bash
# One-time setup script for persistent database storage
# Run this ONCE after initial deployment to enable database persistence

set -e

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-nebulous-discord-bot}"
CONTAINER_APP_ENV="${CONTAINER_APP_ENV:-nebulous-bot-env}"
STORAGE_ACCOUNT_NAME="nebulousbotstorage"
STORAGE_SHARE_NAME="botdata"

echo "🗄️  Setting up persistent storage for database"
echo "=============================================="

# Check if storage account exists
echo "📦 Checking for existing storage account..."
STORAGE_EXISTS=$(az storage account show \
  --name $STORAGE_ACCOUNT_NAME \
  --resource-group $RESOURCE_GROUP \
  --query 'name' \
  --output tsv 2>/dev/null || echo "")

if [ -z "$STORAGE_EXISTS" ]; then
  echo "   Creating storage account: $STORAGE_ACCOUNT_NAME"
  az storage account create \
    --name $STORAGE_ACCOUNT_NAME \
    --resource-group $RESOURCE_GROUP \
    --location westus \
    --sku Standard_LRS \
    --kind StorageV2 \
    --https-only true
else
  echo "   ✅ Storage account already exists"
fi

# Get storage key
echo "🔑 Getting storage account key..."
STORAGE_KEY=$(az storage account keys list \
  --resource-group $RESOURCE_GROUP \
  --account-name $STORAGE_ACCOUNT_NAME \
  --query '[0].value' \
  --output tsv)

# Create file share
echo "📁 Creating file share..."
az storage share create \
  --name $STORAGE_SHARE_NAME \
  --account-name $STORAGE_ACCOUNT_NAME \
  --account-key "$STORAGE_KEY" \
  --quota 1 2>/dev/null || echo "   ✅ File share already exists"

# Configure storage in Container App Environment
echo "🔧 Configuring storage in Container App Environment..."
az containerapp env storage set \
  --name $CONTAINER_APP_ENV \
  --resource-group $RESOURCE_GROUP \
  --storage-name botdata-storage \
  --azure-file-account-name $STORAGE_ACCOUNT_NAME \
  --azure-file-account-key "$STORAGE_KEY" \
  --azure-file-share-name $STORAGE_SHARE_NAME \
  --access-mode ReadWrite 2>/dev/null || echo "   ✅ Storage already configured"

# Update container app to mount the storage
echo "🔗 Mounting storage to container app..."
az containerapp update \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --set-env-vars DB_PATH=/mnt/data/db.sqlite3 \
  --output none

echo ""
echo "⚠️  IMPORTANT: Azure CLI doesn't support adding volume mounts directly."
echo "   You need to complete the setup manually:"
echo ""
echo "   1. Go to: https://portal.azure.com"
echo "   2. Navigate to: Resource Groups > $RESOURCE_GROUP > $CONTAINER_APP_NAME"
echo "   3. Click 'Containers' in the left menu"
echo "   4. Click 'Edit and deploy' (top)"
echo "   5. Under 'Container' section, click 'Volume mounts' tab"
echo "   6. Click '+ Add'"
echo "   7. Select:"
echo "      - Volume name: botdata-storage"
echo "      - Mount path: /mnt/data"
echo "   8. Click 'Save' then 'Create'"
echo ""
echo "   Once complete, your database will persist across deployments! 🎉"
echo ""
echo "   Estimated cost: ~\$0.06/month for 1GB storage"

