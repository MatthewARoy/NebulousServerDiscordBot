# Fixing Unhealthy Azure Container App Revision

## Problem

When deploying updates, the new revision is marked as "Unhealthy" because health probes weren't configured during the update. This causes:
- The bot to show old deployment time in `!status` command
- Traffic to stay on the old (healthy) revision
- New code not being deployed

## Immediate Fix

### Option 1: Deactivate Unhealthy Revision (Quick Fix)

If you have a healthy revision running:

```bash
# List revisions
az containerapp revision list \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --output table

# Deactivate the unhealthy revision (if healthy one exists)
az containerapp revision deactivate \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --revision nebulous-discord-bot--0000032
```

### Option 2: Check Logs and Diagnose

```bash
# Run the diagnostic script
./deployment/scripts/fix-unhealthy-revision.sh

# Or check logs manually
az containerapp logs show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --revision nebulous-discord-bot--0000032 \
  --tail 100
```

### Option 3: Redeploy with Fixed Script

The deployment script has been updated to include health probes. Redeploy:

```bash
./deployment/scripts/deploy-azure.sh
```

This will:
1. Update the image
2. Configure health probes automatically
3. Create a healthy revision

## Root Cause

The `az containerapp update` command doesn't configure health probes by default. The deployment script now:
1. Updates the container app with new image
2. Configures health probes via YAML
3. Ensures revisions are marked as healthy

## Health Probe Configuration

The health probes are configured to:
- **Liveness probe**: Check `/health/` every 30 seconds, starting after 30 seconds
- **Readiness probe**: Check `/health/` every 10 seconds, starting after 10 seconds
- **Port**: 8000
- **Path**: `/health/`

## Verification

After fixing, verify:

```bash
# Check revision status
az containerapp revision list \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --output table

# Should show new revision as "Healthy"
```

## Prevention

Future deployments using `./deployment/scripts/deploy-azure.sh` will automatically configure health probes, preventing this issue.

