#!/bin/bash
# Script to verify that a deployment actually updated the container app

CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-nebulous-discord-bot}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"

echo "🔍 Verifying Azure Container App Deployment"
echo "============================================"
echo ""

# Check if container app exists
if ! az containerapp show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP &>/dev/null; then
    echo "❌ Container app not found: $CONTAINER_APP_NAME"
    exit 1
fi

# Get current image
echo "1️⃣  Current Running Image:"
echo "-----------------------------------"
CURRENT_IMAGE=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.template.containers[0].image" -o tsv)

echo "   $CURRENT_IMAGE"
echo ""

# Get all revisions
echo "2️⃣  Recent Revisions:"
echo "-----------------------------------"
az containerapp revision list \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "[].{Name:name, Active:properties.active, Created:properties.createdTime, Image:properties.template.containers[0].image}" \
  --output table \
  --max-items 5

echo ""

# Get active revision
echo "3️⃣  Active Revision Details:"
echo "-----------------------------------"
ACTIVE_REVISION=$(az containerapp revision list \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "[?properties.active==\`true\`].name" -o tsv | head -1)

if [ -n "$ACTIVE_REVISION" ]; then
    echo "   Active Revision: $ACTIVE_REVISION"
    
    REVISION_IMAGE=$(az containerapp revision show \
      --name $CONTAINER_APP_NAME \
      --resource-group $RESOURCE_GROUP \
      --revision $ACTIVE_REVISION \
      --query "properties.template.containers[0].image" -o tsv)
    
    echo "   Image: $REVISION_IMAGE"
    echo "   Created: $(az containerapp revision show \
      --name $CONTAINER_APP_NAME \
      --resource-group $RESOURCE_GROUP \
      --revision $ACTIVE_REVISION \
      --query "properties.createdTime" -o tsv)"
else
    echo "   ⚠️  No active revision found"
fi

echo ""

# Check if image matches
if [[ "$CURRENT_IMAGE" == *"latest-"* ]]; then
    echo "✅ Image uses timestamped tag (good for forcing updates)"
else
    echo "⚠️  Image uses 'latest' tag - updates may not be detected if image digest is the same"
fi

echo ""
echo "4️⃣  Container Status:"
echo "-----------------------------------"
STATUS=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.runningStatus" -o tsv)
echo "   Status: $STATUS"

HEALTH=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.healthState" -o tsv)
echo "   Health: $HEALTH"

echo ""
echo "5️⃣  Recent Logs (last 5 lines):"
echo "-----------------------------------"
az containerapp logs show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --tail 5

echo ""
echo "============================================"
echo "💡 Tips:"
echo ""
echo "If the image hasn't updated, try:"
echo "  1. Check if the build actually pushed a new image"
echo "  2. Use a unique tag (timestamp-based tags are now used automatically)"
echo "  3. Force a revision restart:"
echo "     az containerapp revision restart --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --revision $ACTIVE_REVISION"

