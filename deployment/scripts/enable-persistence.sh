#!/bin/bash
# Automated script to enable database persistence using YAML configuration
# This adds Azure Files mount to the existing container app

set -e

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-nebulous-discord-bot}"
CONTAINER_APP_ENV="${CONTAINER_APP_ENV:-nebulous-bot-env}"
STORAGE_ACCOUNT_NAME="nebulousbotstorage"
STORAGE_SHARE_NAME="botdata"

echo "🗄️  Enabling database persistence for Nebulous Discord Bot"
echo "=========================================================="

# 1. Create storage account
echo "📦 Step 1: Setting up Azure Storage..."
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
    --https-only true \
    --output none
  echo "   ✅ Storage account created"
else
  echo "   ✅ Storage account already exists"
fi

# 2. Get storage key
STORAGE_KEY=$(az storage account keys list \
  --resource-group $RESOURCE_GROUP \
  --account-name $STORAGE_ACCOUNT_NAME \
  --query '[0].value' \
  --output tsv)

# 3. Create file share
echo "📁 Step 2: Creating file share..."
az storage share create \
  --name $STORAGE_SHARE_NAME \
  --account-name $STORAGE_ACCOUNT_NAME \
  --account-key "$STORAGE_KEY" \
  --quota 1 \
  --output none 2>/dev/null || echo "   ✅ File share already exists"

# 4. Configure storage in environment
echo "🔧 Step 3: Configuring storage in Container App Environment..."
az containerapp env storage set \
  --name $CONTAINER_APP_ENV \
  --resource-group $RESOURCE_GROUP \
  --storage-name botdata-storage \
  --azure-file-account-name $STORAGE_ACCOUNT_NAME \
  --azure-file-account-key "$STORAGE_KEY" \
  --azure-file-share-name $STORAGE_SHARE_NAME \
  --access-mode ReadWrite \
  --output none 2>/dev/null || echo "   ✅ Storage already configured"

# 5. Export current container app configuration
echo "📋 Step 4: Exporting current container app configuration..."
az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --output yaml > /tmp/containerapp-config.yaml

# 6. Check if volume mount already exists
if grep -q "volumeMounts:" /tmp/containerapp-config.yaml; then
  echo "   ✅ Volume mount already configured"
  rm /tmp/containerapp-config.yaml
  echo ""
  echo "🎉 Database persistence is already enabled!"
  exit 0
fi

# 7. Add volume configuration using Python (more reliable than sed)
echo "🔗 Step 5: Adding volume mount to configuration..."
python3 << 'PYTHON_SCRIPT'
import yaml
import sys

# Read the YAML
with open('/tmp/containerapp-config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Navigate to the container template
containers = config['properties']['template']['containers']
if not containers:
    print("Error: No containers found in configuration")
    sys.exit(1)

container = containers[0]

# Add volume mount
if 'volumeMounts' not in container:
    container['volumeMounts'] = []

# Check if mount already exists
mount_exists = any(m.get('mountPath') == '/mnt/data' for m in container.get('volumeMounts', []))
if not mount_exists:
    container['volumeMounts'].append({
        'volumeName': 'botdata-storage',
        'mountPath': '/mnt/data'
    })

# Add volume to template
template = config['properties']['template']
if 'volumes' not in template:
    template['volumes'] = []

volume_exists = any(v.get('name') == 'botdata-storage' for v in template.get('volumes', []))
if not volume_exists:
    template['volumes'].append({
        'name': 'botdata-storage',
        'storageType': 'AzureFile',
        'storageName': 'botdata-storage'
    })

# Add DB_PATH environment variable
if 'env' not in container:
    container['env'] = []

db_path_exists = any(e.get('name') == 'DB_PATH' for e in container.get('env', []))
if not db_path_exists:
    container['env'].append({
        'name': 'DB_PATH',
        'value': '/mnt/data/db.sqlite3'
    })

# Write back
with open('/tmp/containerapp-config-updated.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)

print("✅ Configuration updated")
PYTHON_SCRIPT

if [ $? -ne 0 ]; then
  echo "❌ Failed to update configuration. Trying manual approach..."
  echo ""
  echo "Please run the manual setup script instead:"
  echo "   ./deployment/scripts/setup-persistent-storage.sh"
  rm /tmp/containerapp-config.yaml
  exit 1
fi

# 8. Apply the updated configuration
echo "🚀 Step 6: Applying updated configuration..."
az containerapp update \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --yaml /tmp/containerapp-config-updated.yaml \
  --output none

# Cleanup
rm /tmp/containerapp-config.yaml /tmp/containerapp-config-updated.yaml

echo ""
echo "✅ Database persistence enabled successfully!"
echo ""
echo "📊 Details:"
echo "   Storage Account: $STORAGE_ACCOUNT_NAME"
echo "   File Share: $STORAGE_SHARE_NAME"
echo "   Mount Path: /mnt/data"
echo "   Database Path: /mnt/data/db.sqlite3"
echo ""
echo "💰 Cost: ~\$0.06/month (1GB storage)"
echo ""
echo "🎉 Your database will now persist across deployments!"

