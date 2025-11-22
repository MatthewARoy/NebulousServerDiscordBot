#!/bin/bash
# Cleanup script to delete old auto-generated Log Analytics workspaces
# These were created by previous deployments and are no longer needed

set -e

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"
KEEP_WORKSPACE="nebulous-bot-logs"

echo "🧹 Cleaning up old Log Analytics workspaces"
echo "==========================================="
echo ""
echo "This will DELETE all auto-generated workspaces except: $KEEP_WORKSPACE"
echo ""

# Get all workspaces in the resource group
WORKSPACES=$(az monitor log-analytics workspace list \
  --resource-group $RESOURCE_GROUP \
  --query "[].name" \
  --output tsv)

if [ -z "$WORKSPACES" ]; then
  echo "No workspaces found in resource group: $RESOURCE_GROUP"
  exit 0
fi

# Count workspaces to delete
TO_DELETE=()
for workspace in $WORKSPACES; do
  if [[ $workspace == workspace-* ]] || [[ $workspace != $KEEP_WORKSPACE ]]; then
    # Skip the one we want to keep
    if [ "$workspace" != "$KEEP_WORKSPACE" ]; then
      TO_DELETE+=("$workspace")
    fi
  fi
done

if [ ${#TO_DELETE[@]} -eq 0 ]; then
  echo "✅ No old workspaces to clean up!"
  echo "   Current workspace: $KEEP_WORKSPACE"
  exit 0
fi

echo "Found ${#TO_DELETE[@]} workspace(s) to delete:"
for workspace in "${TO_DELETE[@]}"; do
  echo "   ❌ $workspace"
done
echo ""

# Ask for confirmation
read -p "Delete these workspaces? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelled."
  exit 0
fi

# Delete workspaces
DELETED=0
FAILED=0

for workspace in "${TO_DELETE[@]}"; do
  echo "Deleting: $workspace..."
  if az monitor log-analytics workspace delete \
    --resource-group $RESOURCE_GROUP \
    --workspace-name "$workspace" \
    --force true \
    --yes \
    --output none 2>/dev/null; then
    echo "   ✅ Deleted"
    DELETED=$((DELETED + 1))
  else
    echo "   ⚠️  Failed to delete (may already be deleted)"
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "🎉 Cleanup complete!"
echo "   Deleted: $DELETED workspace(s)"
if [ $FAILED -gt 0 ]; then
  echo "   Failed: $FAILED workspace(s)"
fi
echo "   Kept: $KEEP_WORKSPACE"
echo ""
echo "💰 This will reduce your Azure costs (each workspace costs ~\$2-5/month)"

