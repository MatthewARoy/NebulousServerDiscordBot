# Azure Deployment - Quick Start

**Yes, the bot can still deploy to Azure!** All Azure deployment functionality remains intact.

---

## ✅ Azure Deployment Status

- ✅ **Deployment scripts**: All working (`deployment/scripts/deploy-azure.sh`)
- ✅ **Dockerfile**: Compatible with Azure (AMD64/x86_64)
- ✅ **Configuration**: No changes needed
- ✅ **Documentation**: `AZURE_DEPLOYMENT_GUIDE.md` is up to date

**Note**: The Oracle Cloud migration documentation is separate and doesn't affect Azure deployment.

---

## 🚀 Quick Deployment (3 Steps)

### Step 1: Prerequisites

```bash
# Install Azure CLI (if not already installed)
# macOS:
brew install azure-cli

# Linux:
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Windows:
# Download from: https://aka.ms/installazurecliwindows

# Login to Azure
az login
```

### Step 2: Prepare Environment File

Create `.env` file in project root:

```bash
cd path/to/NebulousServerDiscordBot

# Copy example (if you don't have one)
cp env_example.txt .env

# Edit with your credentials
nano .env  # or your preferred editor
```

**Required in `.env`:**
```env
DISCORD_TOKEN=your_discord_bot_token_here
APPLICATION_ID=your_application_id_here
SERVER_CONFIGS=[{"guild_id": 1234567890, "status_channel_id": 0987654321}]
STEAM_API_KEY=your_steam_api_key_here
```

### Step 3: Deploy

```bash
# Run the deployment script
./deployment/scripts/deploy-azure.sh
```

That's it! The script will:
1. ✅ Register Azure resource providers (first time only)
2. ✅ Create resource group
3. ✅ Create Azure Container Registry
4. ✅ Build Docker image (AMD64 for Azure)
5. ✅ Push image to Azure
6. ✅ Create/update Container App
7. ✅ Deploy your bot

**Total time**: ~10-15 minutes (first deployment)

---

## 📋 Detailed Steps

### Option A: Automated Script (Recommended)

```bash
# From project root
cd path/to/NebulousServerDiscordBot

# Make sure you're logged in
az login

# Run deployment
./deployment/scripts/deploy-azure.sh
```

### Option B: Custom Configuration

```bash
# Set custom resource names
export AZURE_RESOURCE_GROUP="my-bot-rg"
export AZURE_LOCATION="eastus"
export CONTAINER_APP_NAME="my-discord-bot"
export ACR_NAME="myuniqueregistry"

# Deploy
./deployment/scripts/deploy-azure.sh
```

### Option C: Manual Deployment

See **[AZURE_DEPLOYMENT_GUIDE.md](AZURE_DEPLOYMENT_GUIDE.md)** for manual step-by-step instructions.

---

## 🔍 Verify Deployment

```bash
# Quick verification script (recommended)
./deployment/scripts/verify-deployment.sh

# Or manually check container status
az containerapp show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --query "properties.runningStatus"

# View logs
az containerapp logs show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --follow

# Check revisions to see if update created a new revision
az containerapp revision list \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --output table

# Check in Discord
# Bot should appear online and respond to !status
```

---

## 🔄 Update Existing Deployment

To update an existing Azure deployment:

```bash
# Just run the deployment script again
./deployment/scripts/deploy-azure.sh

# It will automatically:
# - Build new image with timestamped tag (ensures Azure detects changes)
# - Push to Azure Container Registry
# - Update the Container App with new image
# - Verify that a new revision was created
# - Show any errors if the update fails

# After deployment, verify it worked:
./deployment/scripts/verify-deployment.sh
```

**Important**: The deployment script now uses timestamped image tags (e.g., `latest-20241215-143022`) to ensure Azure Container Apps always detects when a new image is available. This prevents silent failures where deployments appear to succeed but don't actually update the running container.

---

## 💾 Database Persistence (Optional)

By default, the database is ephemeral (resets on deployment). To enable persistence:

```bash
# Run the persistence setup script
./deployment/scripts/setup-persistent-storage.sh

# Then redeploy
./deployment/scripts/deploy-azure.sh
```

See **[deployment/ENABLE_PERSISTENCE.md](deployment/ENABLE_PERSISTENCE.md)** for details.

---

## 🐛 Troubleshooting

### "Subscription not registered"

```bash
# Register providers manually
./deployment/scripts/setup-azure-providers.sh
```

### "Azure CLI not found"

```bash
# Install Azure CLI (see Step 1 above)
```

### "Not logged in"

```bash
az login
```

### Bot not connecting

```bash
# Check logs
az containerapp logs show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --follow

# Verify credentials in .env file
cat .env | grep DISCORD_TOKEN
```

### Deployment appears to succeed but bot doesn't update

```bash
# Verify the deployment actually created a new revision
./deployment/scripts/verify-deployment.sh

# Check if image was updated
az containerapp show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --query "properties.template.containers[0].image"

# If image hasn't changed, the deployment script should now catch this
# The script now uses timestamped tags to force updates
```

### Build fails

```bash
# Check Docker is running
docker info

# Try local build method
./deployment/scripts/deploy-azure-local-build.sh
```

**Full troubleshooting**: See **[deployment/azure/TROUBLESHOOTING.md](deployment/azure/TROUBLESHOOTING.md)**

---

## 📊 Useful Commands

```bash
# View logs
./deployment/scripts/check-azure-logs.sh

# Diagnose issues
./deployment/scripts/diagnose-azure-bot.sh

# Verify deployment (check if update actually happened)
./deployment/scripts/verify-deployment.sh

# Check status
az containerapp show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --query "properties.{Status:runningStatus,Health:healthState}"

# Update environment variables only
az containerapp update \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --set-env-vars "PLAYER_THRESHOLD=50"
```

---

## 📚 Full Documentation

- **Complete Guide**: **[AZURE_DEPLOYMENT_GUIDE.md](AZURE_DEPLOYMENT_GUIDE.md)**
- **Persistence Setup**: **[deployment/ENABLE_PERSISTENCE.md](deployment/ENABLE_PERSISTENCE.md)**
- **Troubleshooting**: **[deployment/azure/TROUBLESHOOTING.md](deployment/azure/TROUBLESHOOTING.md)**

---

## 💰 Cost

**Current Azure costs** (approximate):
- Container App (0.5 CPU, 1GB RAM): ~$15-20/month
- Container Registry (Basic): ~$5/month
- Storage (if using persistence): ~$0.06/month
- **Total**: ~$20-25/month

**Note**: If you want to reduce costs, consider migrating to Oracle Cloud Free Tier (see Oracle Cloud migration guides).

---

## ✅ Deployment Checklist

Before deploying:

- [ ] Azure CLI installed (`az --version`)
- [ ] Logged into Azure (`az login`)
- [ ] `.env` file created with all credentials
- [ ] `SERVER_CONFIGS` is valid JSON on single line
- [ ] Docker Desktop running (for local builds, if needed)

After deploying:

- [ ] Check logs for "Bot has connected to Discord!"
- [ ] Verify bot appears online in Discord
- [ ] Test with `!status` command
- [ ] Monitor logs for any errors

---

## 🆚 Azure vs Oracle Cloud

| Feature | Azure | Oracle Cloud |
|---------|-------|--------------|
| **Cost** | ~$20-25/month | $0/month (free tier) |
| **Architecture** | AMD64 (x86_64) | ARM64 |
| **Deployment** | Container Apps (serverless) | Compute VM |
| **Scaling** | Auto-scaling | Manual |
| **Setup** | Automated scripts | Manual + scripts |

**Both work!** Choose based on your needs:
- **Azure**: Easier setup, managed services, costs money
- **Oracle**: Free forever, more control, manual management

---

**Ready to deploy?** Run `./deployment/scripts/deploy-azure.sh`! 🚀

