# Azure Deployment Guide

**Quick Start Guide for Deploying to Azure Container Apps**

---

## 📋 Prerequisites

Before you begin, make sure you have:

1. ✅ **Azure Account** - [Create free account](https://azure.microsoft.com/free/)
2. ✅ **Azure CLI** - [Install guide](https://docs.microsoft.com/cli/azure/install-azure-cli)
3. ✅ **Docker** - [Install Docker Desktop](https://www.docker.com/products/docker-desktop/) (if building locally)
4. ✅ **Your Bot Credentials**:
   - Discord Bot Token
   - Discord Application ID
   - Steam API Key
   - Discord Server/Channel IDs

---

## 🚀 Quick Deployment (5 Steps)

### **Step 1: Install Azure CLI**

**macOS:**
```bash
brew update && brew install azure-cli
```

**Windows:**
Download installer from: https://aka.ms/installazurecliwindows

**Linux:**
```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

**Verify installation:**
```bash
az --version
```

---

### **Step 2: Login to Azure**

```bash
az login
```

This will open your browser to authenticate. After logging in:

```bash
# Set your subscription (if you have multiple)
az account list --output table
az account set --subscription "<SUBSCRIPTION_ID>"
```

---

### **Step 3: Prepare Your Environment File**

Create a `.env` file in the project root with your credentials:

```bash
cd path/to/NebulousServerDiscordBot

# Copy the example file
cp env_example.txt .env

# Edit with your credentials
nano .env  # or use your preferred editor
```

**Required variables in `.env`:**
```bash
# Discord Configuration
DISCORD_TOKEN=your_discord_bot_token_here
APPLICATION_ID=your_application_id_here

# Server Configuration (JSON format, single line!)
SERVER_CONFIGS=[{"guild_id": 1234567890, "status_channel_id": 0987654321}]

# Steam API
STEAM_API_KEY=your_steam_api_key_here

# Django (auto-generated if not provided)
DJANGO_SECRET_KEY=your_django_secret_here

# Optional
PLAYER_THRESHOLD=40
NOTIFICATION_INTERVAL=3600
```

**Important**: `SERVER_CONFIGS` must be on a single line!

---

### **Step 4: Run the Deployment Script**

```bash
# Navigate to project root (if not already there)
cd path/to/NebulousServerDiscordBot

# Make script executable
chmod +x deployment/scripts/deploy-azure.sh

# Run deployment (can be run from any directory now!)
./deployment/scripts/deploy-azure.sh
```

**Note**: The script automatically changes to the project root, so you can run it from anywhere!

**What this does:**
1. ✅ Registers Azure resource providers (2-5 min first time)
2. ✅ Creates resource group
3. ✅ Creates Azure Container Registry
4. ✅ Builds Docker image (can take 5-10 minutes)
5. ✅ Pushes image to Azure
6. ✅ Creates Container App
7. ✅ Deploys your bot

**Total time**: ~10-15 minutes on first deployment

---

### **Step 5: Verify Deployment**

```bash
# Check if container is running
az containerapp show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --query "properties.runningStatus" \
  --output tsv

# View live logs
az containerapp logs show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --follow
```

**Look for these log messages:**
```
✅ Bot has connected to Discord!
✅ Configuration validated successfully
✅ Server monitoring started
```

---

## 🎯 Alternative: Local Docker Build

If ACR Tasks aren't available in your region, the script automatically falls back to local build.

**Ensure Docker is running:**
```bash
docker info
```

**The script will:**
1. Build for `linux/amd64` platform (required for Azure)
2. Login to Azure Container Registry
3. Push the image

**This requires:**
- ✅ Docker Desktop running
- ✅ ~2GB disk space for image
- ✅ Good internet connection for push

---

## 🔧 Configuration Options

### Environment Variables

You can override defaults:

```bash
# Custom resource names
export AZURE_RESOURCE_GROUP="my-bot-rg"
export AZURE_LOCATION="westus2"
export CONTAINER_APP_NAME="my-discord-bot"
export ACR_NAME="myuniquebotregistry"

# Then deploy
./deploy-azure.sh
```

### Resource Sizes

Default: **0.5 CPU, 1GB RAM** (costs ~$15-20/month)

To change, edit `deploy-azure.sh`:
```bash
--cpu 0.5 \        # 0.25, 0.5, 0.75, 1.0, etc.
--memory 1.0Gi \   # 0.5Gi, 1.0Gi, 2.0Gi, etc.
```

---

## 📊 Monitoring Your Bot

### View Logs

```bash
# Live logs (follow mode)
cd deployment/scripts
./check-azure-logs.sh

# Or manually:
az containerapp logs show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --follow
```

### Check Status

```bash
# Container status
az containerapp show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --query "properties.{Status:runningStatus,Health:healthState,Replicas:template.scale}" \
  --output table

# Recent revisions
az containerapp revision list \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --output table
```

### Diagnose Issues

```bash
# Run diagnostic script
cd deployment/scripts
./diagnose-azure-bot.sh
```

---

## 🔄 Updating Your Bot

### Method 1: Redeploy (Recommended)

```bash
cd deployment/scripts
./deploy-azure.sh
```

This rebuilds and deploys the latest code.

### Method 2: Manual Update

```bash
# 1. Build new image
cd deployment/docker
docker build -t nebulous-bot:latest ../..

# 2. Tag for ACR
docker tag nebulous-bot:latest \
  nebulousbot.azurecr.io/nebulous-bot:latest

# 3. Push to ACR
az acr login --name nebulousbot
docker push nebulousbot.azurecr.io/nebulous-bot:latest

# 4. Update container app
az containerapp update \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --image nebulousbot.azurecr.io/nebulous-bot:latest
```

### Update Environment Variables Only

```bash
az containerapp update \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --set-env-vars "PLAYER_THRESHOLD=50"
```

---

## 💰 Cost Estimate

**Azure Container Apps Pricing (as of 2024):**

| Resource | Amount | Cost/Month |
|----------|--------|------------|
| Container App | 0.5 vCPU, 1GB RAM | ~$15-20 |
| Container Registry | Basic tier | ~$5 |
| Logs & Monitoring | Included | Free |
| **Total** | | **~$20-25/month** |

**Cost-saving tips:**
- Use the free tier (limited resources)
- Scale to 0 when not in use (if acceptable)
- Use shared Container App Environment

---

## 🧹 Cleanup / Delete Resources

### Delete Everything

```bash
# WARNING: This deletes ALL resources in the resource group!
az group delete --name nebulous-bot-rg --yes
```

### Delete Individual Resources

```bash
# Just the container app
az containerapp delete \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --yes

# Just the container registry
az acr delete \
  --name nebulousbot \
  --resource-group nebulous-bot-rg \
  --yes
```

---

## 🐛 Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| "Subscription not registered" | Run `deployment/scripts/setup-azure-providers.sh` |
| "ACR not found" | Wait 2-5 min for provider registration, then retry |
| "Build failed" | Check Docker is running, disk space available |
| "Bot not connecting" | Check logs for errors, verify credentials in .env |
| "Out of memory" | Increase `--memory` in deploy script |

**Full troubleshooting guide:**
```bash
cat deployment/azure/TROUBLESHOOTING.md
```

---

## 📚 Additional Resources

- **Azure Container Apps Docs**: https://docs.microsoft.com/azure/container-apps/
- **Discord Bot Setup**: See main `README.md`
- **Local Testing**: Use `docker-compose -f deployment/docker/docker-compose.yml up`
- **Deployment Scripts**: All in `deployment/scripts/`

---

## ✅ Deployment Checklist

Before deploying, ensure:

- [ ] Azure CLI installed and logged in (`az login`)
- [ ] `.env` file created with all credentials
- [ ] `SERVER_CONFIGS` is valid JSON on single line
- [ ] Docker Desktop running (for local builds)
- [ ] Azure subscription has sufficient quota
- [ ] Discord bot added to your server
- [ ] Steam API key is valid

After deployment:

- [ ] Check logs for "Bot has connected to Discord!"
- [ ] Verify bot appears online in Discord
- [ ] Test with `!status` command
- [ ] Monitor logs for any errors
- [ ] Set up billing alerts in Azure Portal

---

## 🚨 Need Help?

1. **Check logs**: `deployment/scripts/check-azure-logs.sh`
2. **Run diagnostics**: `deployment/scripts/diagnose-azure-bot.sh`
3. **Review troubleshooting**: `deployment/azure/TROUBLESHOOTING.md`
4. **Test locally first**: `python main.py` or `docker-compose up`

---

**You're ready to deploy!** 🚀

Run: `cd deployment/scripts && ./deploy-azure.sh`

