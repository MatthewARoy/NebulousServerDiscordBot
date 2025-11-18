# Azure Deployment Troubleshooting Guide

## Common Issues and Solutions

### 1. "Subscription not registered" Error

**Error Message:**
```
The subscription is not registered to use namespace 'Microsoft.ContainerRegistry'
```

**Solution:**

The deployment script now automatically registers required providers, but if you see this error, run:

```bash
# Option 1: Use the setup script (recommended)
./setup-azure-providers.sh

# Option 2: Manual registration
az provider register --namespace Microsoft.ContainerRegistry --wait
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait

# Verify registration
az provider show --namespace Microsoft.ContainerRegistry --query registrationState
```

Registration takes 2-5 minutes. The `--wait` flag ensures the command waits for completion.

### 2. "Resource not found" Errors

**Error Message:**
```
The resource with name 'nebulousbot' could not be found
```

**Cause:** The Azure Container Registry wasn't created successfully (often due to provider registration issue above).

**Solution:**
1. First, register providers (see issue #1)
2. Then re-run deployment:
   ```bash
   ./deploy-azure.sh
   ```

### 3. Location/Region Issues

**Error Message:**
```
The specified location 'XXX' is invalid or unavailable
```

**Solution:**

Check available locations:
```bash
# List all locations
az account list-locations --query "[].name" -o table

# Use a different location in deploy script
export AZURE_LOCATION="westus"  # or westus, centralus, etc.
./deploy-azure.sh
```

Common locations:
- `westus` (East US)
- `westus` (West US)
- `westeurope` (West Europe)
- `eastasia` (East Asia)

### 4. Authentication Issues

**Error Message:**
```
Please run 'az login' to setup account.
```

**Solution:**
```bash
# Login to Azure
az login

# If you have multiple subscriptions, set the correct one
az account list --output table
az account set --subscription "Your Subscription Name"

# Verify
az account show
```

### 5. Quota/Limit Exceeded

**Error Message:**
```
Operation could not be completed as it results in exceeding approved quota
```

**Solution:**
```bash
# Check your quotas
az vm list-usage --location westus -o table

# Request quota increase
# Visit: https://portal.azure.com → Subscriptions → Usage + quotas
```

Or use smaller container size in deploy script:
```bash
# Edit deploy-azure.sh
# Change: --cpu 0.5 --memory 1.0Gi
# To: --cpu 0.25 --memory 0.5Gi
```

### 6. Container App Creation Fails

**Error Message:**
```
The container app environment does not exist
```

**Solution:**

The environment might not have been created. Check and create manually:

```bash
# Check if environment exists
az containerapp env list --resource-group nebulous-bot-rg

# Create if missing
az containerapp env create \
  --name nebulous-bot-env \
  --resource-group nebulous-bot-rg \
  --location westus

# Then re-run deployment
./deploy-azure.sh
```

### 7. "Too many requests" / Rate Limiting

**Error Message:**
```
TooManyRequests: The request was rejected due to request throttling
```

**Solution:**

Wait a few minutes and try again. Azure has rate limits for API calls.

```bash
# Wait 5-10 minutes, then retry
./deploy-azure.sh
```

### 8. ACR Tasks Not Allowed

**Error Message:**
```
(TasksOperationsNotAllowed) ACR Tasks requests for the registry are not permitted
```

**Cause:** Your Azure subscription doesn't support ACR Tasks (common with free/trial/student subscriptions).

**Solution:**

Build the Docker image locally instead:

```bash
# Use the local build script (recommended)
./deploy-azure-local-build.sh

# OR let the main script fall back automatically
./deploy-azure.sh
```

**Requirements:** Docker must be running on your computer.

See [AZURE_ACR_TASKS_WORKAROUND.md](AZURE_ACR_TASKS_WORKAROUND.md) for detailed instructions.

### 9. Container Build Fails

**Error Message:**
```
error building at STEP "RUN...": error while running runtime
```

**Solution:**

Test Docker build locally first:

```bash
# Build locally
docker build -t nebulous-bot .

# If local build works, try Azure again
./deploy-azure.sh
```

Check Dockerfile for issues:
- Verify all COPY commands reference existing files
- Check requirements.txt is valid
- Ensure Python version matches

### 9. Container Won't Start

**Check logs:**
```bash
az containerapp logs show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --follow
```

**Common causes:**
- Missing environment variables
- Invalid Discord token
- Invalid Steam API key
- Configuration errors

**Solution:**

Update secrets:
```bash
az containerapp update \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --set-env-vars \
    DISCORD_TOKEN="your-new-token" \
    STEAM_API_KEY="your-new-key"
```

### 10. Health Check Failures

**Error Message:**
```
Container failed health check
```

**Solution:**

1. Check if port 8000 is exposed:
   ```bash
   # In Dockerfile, ensure:
   EXPOSE 8000
   ```

2. Verify health endpoint works locally:
   ```bash
   docker run -p 8000:8000 nebulous-bot
   curl http://localhost:8000/health/
   ```

3. Check Container App logs for startup errors

## Debugging Commands

### Check Resource Status
```bash
# List all resources in resource group
az resource list --resource-group nebulous-bot-rg --output table

# Check container app status
az containerapp show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --query "properties.provisioningState"
```

### View Container Logs
```bash
# Follow logs in real-time
az containerapp logs show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --follow

# View recent logs
az containerapp logs show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --tail 100
```

### Check Container App Configuration
```bash
# View all settings
az containerapp show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg

# View environment variables (secrets are hidden)
az containerapp show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --query "properties.template.containers[0].env"
```

### Restart Container
```bash
az containerapp revision restart \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg
```

### Delete and Recreate
```bash
# Delete container app
az containerapp delete \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --yes

# Re-run deployment
./deploy-azure.sh
```

## Clean Up Resources

If you need to start fresh:

```bash
# Delete entire resource group (WARNING: Deletes everything!)
az group delete --name nebulous-bot-rg --yes --no-wait

# Then redeploy
./deploy-azure.sh
```

## Cost Management

### Check Current Costs
```bash
# View cost analysis in portal
# Portal → Resource Group → Cost Analysis
```

### Reduce Costs
```bash
# Use smaller container size
az containerapp update \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --cpu 0.25 \
  --memory 0.5Gi

# Stop container (not delete) when not needed
az containerapp revision deactivate \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --revision <revision-name>
```

## Getting Help

1. **Check logs first**: `az containerapp logs show --follow`
2. **Test locally**: `docker-compose up` before deploying
3. **Azure Status**: https://status.azure.com/
4. **Azure Support**: https://azure.microsoft.com/support/

## Prevention Checklist

Before deploying, ensure:

- [ ] Azure CLI installed and updated
- [ ] Logged in: `az login`
- [ ] Correct subscription: `az account show`
- [ ] Resource providers registered: `./setup-azure-providers.sh`
- [ ] `.env` file configured correctly
- [ ] Docker builds locally: `docker build -t nebulous-bot .`
- [ ] Container runs locally: `docker run -p 8000:8000 nebulous-bot`
- [ ] Health check works: `curl http://localhost:8000/health/`

## Quick Reference

| Issue | Command |
|-------|---------|
| Register providers | `./setup-azure-providers.sh` |
| View logs | `az containerapp logs show --follow` |
| Restart app | `az containerapp revision restart` |
| Update secrets | `az containerapp update --set-env-vars KEY=value` |
| Delete and start over | `az group delete --name nebulous-bot-rg` |
| Check status | `az containerapp show --name nebulous-discord-bot` |

---

**Still having issues?**
1. Check [README_DJANGO.md](README_DJANGO.md) for deployment instructions
2. Verify local setup works first: `docker-compose up`
3. Review Azure Portal for detailed error messages

