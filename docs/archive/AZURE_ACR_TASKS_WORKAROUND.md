# Azure ACR Tasks Workaround

## Problem: "TasksOperationsNotAllowed" Error

If you see this error:
```
(TasksOperationsNotAllowed) ACR Tasks requests for the registry are not permitted
```

This means your Azure subscription doesn't support **ACR Tasks**, which is the service that builds Docker images in the cloud. This is common with:
- Free/Trial Azure subscriptions
- Student Azure subscriptions
- Some enterprise subscriptions with restrictions
- Certain Azure regions

## ✅ Solution: Build Locally Instead

Instead of building in Azure, build the Docker image on your local machine and push it to Azure Container Registry.

### Method 1: Use the Local Build Script (Easiest)

I've created a dedicated script that builds locally:

```bash
./deploy-azure-local-build.sh
```

This script:
1. ✅ Builds the Docker image on your computer
2. ✅ Pushes it to Azure Container Registry
3. ✅ Deploys to Azure Container Apps
4. ✅ Handles all the same configuration as the original script

### Method 2: Manual Local Build

If you prefer to do it manually:

```bash
# 1. Set your variables
RESOURCE_GROUP="nebulous-bot-rg"
ACR_NAME="nebulousbot"
IMAGE_NAME="nebulous-bot"

# 2. Login to Azure Container Registry
az acr login --name $ACR_NAME

# 3. Get the ACR server address
ACR_SERVER=$(az acr show --name $ACR_NAME --query loginServer --output tsv)
echo "ACR Server: $ACR_SERVER"

# 4. Build the image locally for AMD64 architecture (Azure requirement)
# Note: Use --platform linux/amd64 even on Apple Silicon Macs
docker build --platform linux/amd64 -t $ACR_SERVER/$IMAGE_NAME:latest .

# 5. Push to Azure Container Registry
docker push $ACR_SERVER/$IMAGE_NAME:latest

# 6. Deploy or update Container App
az containerapp update \
  --name nebulous-discord-bot \
  --resource-group $RESOURCE_GROUP \
  --image $ACR_SERVER/$IMAGE_NAME:latest
```

### Method 3: Update the Deployment Script

The main `deploy-azure.sh` has been updated to automatically fall back to local builds if ACR Tasks fails. Just run:

```bash
./deploy-azure.sh
```

It will try ACR Tasks first, and if that fails, it will automatically build locally.

## Requirements for Local Build

You need Docker running on your machine:

### Check if Docker is Running
```bash
docker info
```

If this fails:
- **macOS**: Open Docker Desktop
- **Windows**: Open Docker Desktop
- **Linux**: `sudo systemctl start docker`

### Verify Docker is Working
```bash
# Test Docker
docker run hello-world

# Build the bot image locally to test
docker build -t nebulous-bot-test .
```

## Comparison: ACR Tasks vs Local Build

| Feature | ACR Tasks (Cloud) | Local Build |
|---------|------------------|-------------|
| **Speed** | Fast (Azure servers) | Depends on your computer |
| **Requirements** | Only Azure CLI | Docker + Azure CLI |
| **Cost** | Uses Azure compute | Free (uses your computer) |
| **Availability** | Some subscriptions | Works everywhere |
| **Build Context** | Uploads code to Azure | Builds on your machine |

## Troubleshooting Local Builds

### "Docker daemon not running"
```bash
# macOS/Windows: Start Docker Desktop
# Linux:
sudo systemctl start docker
```

### "Permission denied"
```bash
# Linux: Add user to docker group
sudo usermod -aG docker $USER
# Then log out and back in
```

### "Cannot connect to Docker daemon"
- Ensure Docker Desktop is running (macOS/Windows)
- Check Docker service: `sudo systemctl status docker` (Linux)

### Build is slow
First build can take 5-10 minutes. Subsequent builds are faster due to caching.

Tips to speed up:
```bash
# Use BuildKit for faster builds
export DOCKER_BUILDKIT=1
docker build -t nebulous-bot .
```

### Push fails with authentication error
```bash
# Re-login to ACR
az acr login --name nebulousbot
```

## Alternative: Use Azure CLI Without ACR

If you don't want to use Azure Container Registry at all, you can use Docker Hub or GitHub Container Registry instead:

### Using Docker Hub

```bash
# 1. Build and push to Docker Hub
docker build -t yourusername/nebulous-bot:latest .
docker push yourusername/nebulous-bot:latest

# 2. Deploy to Azure using public image
az containerapp create \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --environment nebulous-bot-env \
  --image yourusername/nebulous-bot:latest \
  --target-port 8000 \
  --ingress internal \
  --cpu 0.5 \
  --memory 1.0Gi
```

## Recommended Approach

For your situation, I recommend:

1. **Use `deploy-azure-local-build.sh`** - This is specifically designed for subscriptions without ACR Tasks
   ```bash
   ./deploy-azure-local-build.sh
   ```

2. **Ensure Docker Desktop is running** before you start

3. **Be patient** - First build takes 5-10 minutes locally

4. **Future updates** are faster - Docker caches layers

## Why This Happens

Azure Container Registry has different SKUs:
- **Basic** (default) - May not have ACR Tasks in all subscriptions
- **Standard** - Usually has ACR Tasks
- **Premium** - Full ACR Tasks support

Some subscription types restrict ACR Tasks even on Basic/Standard SKUs for cost control or security policies.

Local building works around this limitation by using your own computer's Docker instead of Azure's build service.

## Summary

**You have 3 options:**

1. ✅ **Easiest**: `./deploy-azure-local-build.sh`
2. ✅ **Automatic**: `./deploy-azure.sh` (now handles fallback automatically)
3. ✅ **Manual**: Follow step-by-step commands above

All three options work perfectly and deploy the same bot to Azure!

---

**Next Steps:**
1. Make sure Docker Desktop is running
2. Run: `./deploy-azure-local-build.sh`
3. Wait for "Deployment complete!" message (takes 10-15 minutes first time)

