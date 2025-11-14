#!/bin/bash
# Deployment script for Azure Container Apps
# Prerequisites: Azure CLI installed and logged in

set -e

# Configuration
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"
LOCATION="${AZURE_LOCATION:-eastus}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-nebulous-discord-bot}"
CONTAINER_APP_ENV="${CONTAINER_APP_ENV:-nebulous-bot-env}"
ACR_NAME="${ACR_NAME:-nebulousbot}"
IMAGE_NAME="nebulous-bot"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "🚀 Deploying Nebulous Discord Bot to Azure"
echo "=========================================="

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo "❌ Azure CLI not found. Please install it first."
    exit 1
fi

# Check if logged in
if ! az account show &> /dev/null; then
    echo "❌ Not logged in to Azure. Please run 'az login' first."
    exit 1
fi

echo "✅ Azure CLI ready"

# Register required resource providers
echo "📋 Registering Azure resource providers..."
echo "   This may take a few minutes on first run..."

# Register Container Registry provider
az provider register --namespace Microsoft.ContainerRegistry --wait || true

# Register Container Apps provider  
az provider register --namespace Microsoft.App --wait || true

# Register Operational Insights (for Container App logs)
az provider register --namespace Microsoft.OperationalInsights --wait || true

echo "✅ Resource providers registered"

# Create resource group if it doesn't exist
echo "📦 Creating resource group..."
az group create --name $RESOURCE_GROUP --location $LOCATION || true

# Create Azure Container Registry if it doesn't exist
echo "📦 Creating Azure Container Registry..."
az acr create \
  --resource-group $RESOURCE_GROUP \
  --name $ACR_NAME \
  --sku Basic \
  --admin-enabled true || true

# Build and push Docker image
echo "🔨 Building Docker image..."

# Try ACR build first, fall back to local build if ACR Tasks not available
if az acr build \
  --registry $ACR_NAME \
  --image $IMAGE_NAME:$IMAGE_TAG \
  --file Dockerfile \
  . 2>/dev/null; then
  echo "✅ Image built using ACR"
else
  echo "⚠️  ACR Tasks not available, building locally instead..."
  
  # Get ACR login server
  ACR_SERVER=$(az acr show --name $ACR_NAME --query loginServer --output tsv)
  
  # Login to ACR
  echo "🔑 Logging into Azure Container Registry..."
  az acr login --name $ACR_NAME
  
  # Build image locally for AMD64 (Azure requirement)
  echo "🔨 Building image locally for linux/amd64 (this may take a few minutes)..."
  docker build --platform linux/amd64 -t $ACR_SERVER/$IMAGE_NAME:$IMAGE_TAG .
  
  # Push to ACR
  echo "📤 Pushing image to Azure Container Registry..."
  docker push $ACR_SERVER/$IMAGE_NAME:$IMAGE_TAG
  
  echo "✅ Image built and pushed locally"
fi

# Create Container App Environment if it doesn't exist
echo "🌍 Creating Container App Environment..."
az containerapp env create \
  --name $CONTAINER_APP_ENV \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION || true

# Get ACR credentials
ACR_SERVER=$(az acr show --name $ACR_NAME --query loginServer --output tsv)
ACR_USERNAME=$(az acr credential show --name $ACR_NAME --query username --output tsv)
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query passwords[0].value --output tsv)

echo "🚢 Deploying Container App..."

# Check if .env file exists for secrets
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found. You'll need to set secrets manually."
    echo "Creating container app without secrets..."
    
    az containerapp create \
      --name $CONTAINER_APP_NAME \
      --resource-group $RESOURCE_GROUP \
      --environment $CONTAINER_APP_ENV \
      --image $ACR_SERVER/$IMAGE_NAME:$IMAGE_TAG \
      --registry-server $ACR_SERVER \
      --registry-username $ACR_USERNAME \
      --registry-password $ACR_PASSWORD \
      --target-port 8000 \
      --ingress internal \
      --cpu 0.5 \
      --memory 1.0Gi \
      --min-replicas 1 \
      --max-replicas 1
else
    echo "📝 Loading environment variables from .env file..."
    # Use set -a to export all variables, then source safely
    set -a
    source <(grep -v '^#' .env | grep -v '^$' | sed 's/\r$//')
    set +a
    
    az containerapp create \
      --name $CONTAINER_APP_NAME \
      --resource-group $RESOURCE_GROUP \
      --environment $CONTAINER_APP_ENV \
      --image $ACR_SERVER/$IMAGE_NAME:$IMAGE_TAG \
      --registry-server $ACR_SERVER \
      --registry-username $ACR_USERNAME \
      --registry-password $ACR_PASSWORD \
      --target-port 8000 \
      --ingress internal \
      --cpu 0.5 \
      --memory 1.0Gi \
      --min-replicas 1 \
      --max-replicas 1 \
      --secrets \
        discord-token="$DISCORD_TOKEN" \
        steam-api-key="$STEAM_API_KEY" \
        django-secret-key="${DJANGO_SECRET_KEY:-$(openssl rand -base64 32)}" \
      --env-vars \
        DISCORD_TOKEN=secretref:discord-token \
        STEAM_API_KEY=secretref:steam-api-key \
        DJANGO_SECRET_KEY=secretref:django-secret-key \
        APPLICATION_ID="$APPLICATION_ID" \
        SERVER_CONFIGS="$SERVER_CONFIGS" \
        PLAYER_THRESHOLD="${PLAYER_THRESHOLD:-40}" \
        NOTIFICATION_INTERVAL="${NOTIFICATION_INTERVAL:-3600}" \
        DEBUG="False" \
        PYTHONUNBUFFERED="1"
fi

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📊 View logs with:"
echo "   az containerapp logs show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --follow"
echo ""
echo "🔄 Update the app with:"
echo "   az containerapp update --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --image $ACR_SERVER/$IMAGE_NAME:$IMAGE_TAG"
echo ""
echo "🗑️  Delete resources with:"
echo "   az group delete --name $RESOURCE_GROUP"

