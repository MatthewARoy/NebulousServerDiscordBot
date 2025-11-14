#!/bin/bash
# Quick script to check Azure Container App logs

CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-nebulous-discord-bot}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"

echo "📊 Checking Azure Container App logs..."
echo "=========================================="
echo ""

# Check if container is running
echo "1. Container Status:"
az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.runningStatus" -o tsv

echo ""
echo "2. Recent Logs (last 50 lines):"
echo "-----------------------------------"
az containerapp logs show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --tail 50

echo ""
echo "3. To follow logs in real-time, run:"
echo "   az containerapp logs show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --follow"

