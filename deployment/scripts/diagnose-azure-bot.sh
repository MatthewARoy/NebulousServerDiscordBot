#!/bin/bash
# Comprehensive diagnostic script for Azure-deployed bot

CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-nebulous-discord-bot}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"

echo "🔍 Diagnosing Nebulous Discord Bot on Azure"
echo "=============================================="
echo ""

# 1. Check container status
echo "1️⃣  Container Status:"
echo "-----------------------------------"
STATUS=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.runningStatus" -o tsv 2>/dev/null)

if [ "$STATUS" == "Running" ]; then
    echo "✅ Status: Running"
else
    echo "❌ Status: $STATUS"
fi

# 2. Check replicas
echo ""
echo "2️⃣  Active Replicas:"
echo "-----------------------------------"
az containerapp replica list \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "[].{Name:name, Status:properties.runningState}" -o table

# 3. Check environment variables (secrets hidden)
echo ""
echo "3️⃣  Environment Variables:"
echo "-----------------------------------"
az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.template.containers[0].env[].{Name:name, Value:value}" -o table | grep -v "secretref"

# 4. Check recent logs for errors
echo ""
echo "4️⃣  Recent Logs (checking for errors):"
echo "-----------------------------------"
az containerapp logs show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --tail 50 | grep -i "error\|exception\|failed\|traceback" || echo "No errors found in recent logs"

# 5. Check if bot connected to Discord
echo ""
echo "5️⃣  Discord Connection:"
echo "-----------------------------------"
az containerapp logs show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --tail 100 | grep -i "connected to discord\|bot connected\|ready" || echo "⚠️  No connection messages found"

# 6. Check if monitoring started
echo ""
echo "6️⃣  Server Monitoring Status:"
echo "-----------------------------------"
az containerapp logs show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --tail 100 | grep -i "monitoring started\|updating server" || echo "⚠️  No monitoring messages found"

# 7. Check last 10 log entries
echo ""
echo "7️⃣  Last 10 Log Entries:"
echo "-----------------------------------"
az containerapp logs show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --tail 10

echo ""
echo "=============================================="
echo "📋 Diagnostic Summary:"
echo ""
echo "To view full logs in real-time:"
echo "  az containerapp logs show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --follow"
echo ""
echo "To restart the container:"
echo "  az containerapp revision restart --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP"
echo ""
echo "To update environment variables:"
echo "  az containerapp update --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --set-env-vars KEY=value"

