#!/bin/bash
# Script to fix unhealthy Azure Container App revision
# This configures health probes and can deactivate unhealthy revisions

set -e

CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-nebulous-discord-bot}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"

echo "🔧 Fixing Unhealthy Azure Container App Revision"
echo "================================================"
echo ""

# 1. Check current revision status
echo "1️⃣  Current Revisions:"
echo "-----------------------------------"
az containerapp revision list \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --output table

echo ""
echo "2️⃣  Checking logs for unhealthy revision..."
echo "-----------------------------------"
UNHEALTHY_REVISION=$(az containerapp revision list \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "[?properties.healthState=='Unhealthy'].name" -o tsv | head -1)

if [ -n "$UNHEALTHY_REVISION" ]; then
  echo "   Found unhealthy revision: $UNHEALTHY_REVISION"
  echo ""
  echo "   Recent logs from unhealthy revision:"
  az containerapp logs show \
    --name $CONTAINER_APP_NAME \
    --resource-group $RESOURCE_GROUP \
    --revision $UNHEALTHY_REVISION \
    --tail 50 | tail -20
else
  echo "   ✅ No unhealthy revisions found"
fi

echo ""
echo "3️⃣  Options to fix:"
echo "-----------------------------------"
echo ""
echo "Option A: Deactivate unhealthy revision (if healthy one exists)"
if [ -n "$UNHEALTHY_REVISION" ]; then
  HEALTHY_REVISION=$(az containerapp revision list \
    --name $CONTAINER_APP_NAME \
    --resource-group $RESOURCE_GROUP \
    --query "[?properties.healthState=='Healthy'].name" -o tsv | head -1)
  
  if [ -n "$HEALTHY_REVISION" ]; then
    echo "   Found healthy revision: $HEALTHY_REVISION"
    echo ""
    read -p "   Deactivate unhealthy revision $UNHEALTHY_REVISION? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
      echo "   Deactivating unhealthy revision..."
      az containerapp revision deactivate \
        --name $CONTAINER_APP_NAME \
        --resource-group $RESOURCE_GROUP \
        --revision $UNHEALTHY_REVISION
      echo "   ✅ Unhealthy revision deactivated"
    fi
  else
    echo "   ⚠️  No healthy revision found to switch to"
  fi
fi

echo ""
echo "Option B: Redeploy with health probes configured"
echo "   Run: ./deployment/scripts/deploy-azure.sh"
echo ""
echo "Option C: Manually configure health probes"
echo "   This requires updating via YAML file with probe configuration"
echo ""

# 4. Check if health probes are configured
echo "4️⃣  Checking health probe configuration..."
echo "-----------------------------------"
PROBES=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.template.containers[0].probes" -o json 2>/dev/null || echo "[]")

if [ "$PROBES" == "[]" ] || [ -z "$PROBES" ]; then
  echo "   ❌ Health probes are NOT configured!"
  echo ""
  echo "   This is why revisions are marked as unhealthy."
  echo "   Health probes need to be configured during deployment."
  echo ""
  echo "   To fix: Redeploy using deploy-azure.sh (which will be updated)"
else
  echo "   ✅ Health probes are configured"
  echo "   $PROBES" | python3 -m json.tool 2>/dev/null || echo "$PROBES"
fi

echo ""
echo "================================================"
echo "📋 Summary:"
echo ""
echo "Common causes of unhealthy revisions:"
echo "  1. Health probes not configured (most common)"
echo "  2. Health endpoint not responding (/health/)"
echo "  3. Container taking too long to start"
echo "  4. Application errors preventing startup"
echo ""
echo "To view full logs:"
echo "  az containerapp logs show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --follow"
echo ""
echo "To check health endpoint manually:"
echo "  # Get container app URL (if ingress is external)"
echo "  az containerapp show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --query properties.configuration.ingress.fqdn -o tsv"
echo ""

