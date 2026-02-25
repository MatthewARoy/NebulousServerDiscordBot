#!/bin/bash
# Deployment script for Azure Container Apps
# Prerequisites: Azure CLI installed and logged in

set -e

# Get the project root directory (2 levels up from this script)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

# Change to project root
cd "$PROJECT_ROOT"

echo "📁 Project root: $PROJECT_ROOT"

# Configuration
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"
LOCATION="${AZURE_LOCATION:-westus}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-nebulous-discord-bot}"
CONTAINER_APP_ENV="${CONTAINER_APP_ENV:-nebulous-bot-env}"
ACR_NAME="${ACR_NAME:-nebulousbot}"
IMAGE_NAME="nebulous-bot"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DEPLOY_IMAGE_TAG="${IMAGE_TAG:-latest}"  # Will be set to timestamped tag during build

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

# Generate a unique tag based on timestamp to ensure Azure detects changes
if [ "$IMAGE_TAG" == "latest" ]; then
  TIMESTAMP_TAG="latest-$(date +%Y%m%d-%H%M%S)"
  echo "   Using timestamped tag: $TIMESTAMP_TAG (will also tag as latest)"
else
  TIMESTAMP_TAG="$IMAGE_TAG"
fi

# Try ACR build first, fall back to local build if ACR Tasks not available
if az acr build \
  --registry $ACR_NAME \
  --image $IMAGE_NAME:$TIMESTAMP_TAG \
  --image $IMAGE_NAME:latest \
  --file deployment/docker/Dockerfile \
  . 2>/dev/null; then
  echo "✅ Image built using ACR"
  # Use timestamped tag for deployment to force update
  DEPLOY_IMAGE_TAG="$TIMESTAMP_TAG"
else
  echo "⚠️  ACR Tasks not available, building locally instead..."
  
  # Get ACR login server
  ACR_SERVER=$(az acr show --name $ACR_NAME --query loginServer --output tsv)
  
  # Login to ACR
  echo "🔑 Logging into Azure Container Registry..."
  az acr login --name $ACR_NAME
  
  # Build image locally for AMD64 (Azure requirement)
  echo "🔨 Building image locally for linux/amd64 (this may take a few minutes)..."
  docker build --platform linux/amd64 -f deployment/docker/Dockerfile -t $ACR_SERVER/$IMAGE_NAME:$TIMESTAMP_TAG -t $ACR_SERVER/$IMAGE_NAME:latest .
  
  # Push to ACR
  echo "📤 Pushing image to Azure Container Registry..."
  docker push $ACR_SERVER/$IMAGE_NAME:$TIMESTAMP_TAG
  docker push $ACR_SERVER/$IMAGE_NAME:latest
  
  echo "✅ Image built and pushed locally"
  # Use timestamped tag for deployment to force update
  DEPLOY_IMAGE_TAG="$TIMESTAMP_TAG"
fi

# Create or reuse Log Analytics workspace
LOG_WORKSPACE_NAME="nebulous-bot-logs"
echo "📊 Setting up Log Analytics workspace..."

LOG_WORKSPACE_EXISTS=$(az monitor log-analytics workspace show \
  --resource-group $RESOURCE_GROUP \
  --workspace-name $LOG_WORKSPACE_NAME \
  --query name \
  --output tsv 2>/dev/null || echo "")

if [ -z "$LOG_WORKSPACE_EXISTS" ]; then
  echo "   Creating Log Analytics workspace: $LOG_WORKSPACE_NAME"
  az monitor log-analytics workspace create \
    --resource-group $RESOURCE_GROUP \
    --workspace-name $LOG_WORKSPACE_NAME \
    --location $LOCATION \
    --output none
  echo "   ✅ Log Analytics workspace created"
else
  echo "   ✅ Using existing Log Analytics workspace: $LOG_WORKSPACE_NAME"
fi

# Get workspace ID and key
LOG_WORKSPACE_ID=$(az monitor log-analytics workspace show \
  --resource-group $RESOURCE_GROUP \
  --workspace-name $LOG_WORKSPACE_NAME \
  --query customerId \
  --output tsv)

LOG_WORKSPACE_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --resource-group $RESOURCE_GROUP \
  --workspace-name $LOG_WORKSPACE_NAME \
  --query primarySharedKey \
  --output tsv)

# Create Container App Environment if it doesn't exist
echo "🌍 Setting up Container App Environment..."

ENV_EXISTS=$(az containerapp env show \
  --name $CONTAINER_APP_ENV \
  --resource-group $RESOURCE_GROUP \
  --query name \
  --output tsv 2>/dev/null || echo "")

if [ -z "$ENV_EXISTS" ]; then
  echo "   Creating Container App Environment: $CONTAINER_APP_ENV"
  az containerapp env create \
    --name $CONTAINER_APP_ENV \
    --resource-group $RESOURCE_GROUP \
    --location $LOCATION \
    --logs-workspace-id $LOG_WORKSPACE_ID \
    --logs-workspace-key $LOG_WORKSPACE_KEY \
    --output none
  echo "   ✅ Container App Environment created"
else
  echo "   ✅ Using existing Container App Environment: $CONTAINER_APP_ENV"
fi

# Check if persistent storage is configured (skip if app doesn't exist yet or flag is set)
if [ -z "${SKIP_PERSISTENCE_CHECK:-}" ]; then
  echo "🔍 Checking database persistence configuration..."
  PERSISTENCE_CHECK=$(az containerapp show \
    --name $CONTAINER_APP_NAME \
    --resource-group $RESOURCE_GROUP \
    --query "properties.template.containers[0].volumeMounts" \
    --output json 2>/dev/null || echo "[]")

  if echo "$PERSISTENCE_CHECK" | grep -q "/mnt/data" 2>/dev/null; then
    echo "   ✅ Database persistence is configured"
    DB_PATH_ENV=$(az containerapp show \
      --name $CONTAINER_APP_NAME \
      --resource-group $RESOURCE_GROUP \
      --query "properties.template.containers[0].env[?name=='DB_PATH'].value" \
      --output tsv 2>/dev/null || echo "")
    if [ -n "$DB_PATH_ENV" ]; then
      echo "   ✅ Database path: $DB_PATH_ENV"
    fi
  else
    echo ""
    echo "⚠️  WARNING: Database persistence is NOT configured!"
    echo "   Your database will be wiped on each deployment."
    echo ""
    echo "   To enable persistence (prevents data loss):"
    echo "   1. Run: ./deployment/scripts/enable-persistence.sh"
    echo "      OR: ./deployment/scripts/setup-persistent-storage.sh"
    echo "   2. Then redeploy"
    echo ""
    echo "   Cost: ~\$0.06/month for 1GB storage"
    echo ""
    if [ -t 0 ]; then
      # Interactive terminal - ask user
      read -p "   Continue with deployment anyway? (y/N): " -n 1 -r
      echo
      if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "   Deployment cancelled. Please set up persistence first."
        exit 1
      fi
    else
      # Non-interactive - just warn
      echo "   ⚠️  Non-interactive mode: Proceeding with ephemeral database"
      echo "   Set SKIP_PERSISTENCE_CHECK=1 to suppress this warning"
    fi
    echo "   ⚠️  WARNING: Database will be wiped on next deployment!"
  fi
else
  echo "   ⏭️  Skipping persistence check (SKIP_PERSISTENCE_CHECK is set)"
fi

# Get ACR credentials
ACR_SERVER=$(az acr show --name $ACR_NAME --query loginServer --output tsv)
ACR_USERNAME=$(az acr credential show --name $ACR_NAME --query username --output tsv)
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query passwords[0].value --output tsv)

echo "🚢 Deploying Container App..."

# Check if container app already exists
APP_EXISTS=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query name \
  --output tsv 2>/dev/null || echo "")

if [ -n "$APP_EXISTS" ]; then
  echo "   ℹ️  Container app already exists, will update with new image..."
  UPDATE_MODE=true
else
  echo "   Creating new container app..."
  UPDATE_MODE=false
fi

# Check if .env file exists for secrets
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found. You'll need to set secrets manually."
    
    if [ "$UPDATE_MODE" = true ]; then
      echo "Updating container app with new image..."
      if ! az containerapp update \
        --name $CONTAINER_APP_NAME \
        --resource-group $RESOURCE_GROUP \
        --image $ACR_SERVER/$IMAGE_NAME:$DEPLOY_IMAGE_TAG; then
        echo "❌ Error: Failed to update container app"
        exit 1
      fi
      
      # Verify update
      echo "   ⏳ Verifying update..."
      sleep 5
      LATEST_REVISION=$(az containerapp revision list \
        --name $CONTAINER_APP_NAME \
        --resource-group $RESOURCE_GROUP \
        --query "[0].name" -o tsv 2>/dev/null)
      if [ -n "$LATEST_REVISION" ]; then
        echo "   ✅ New revision: $LATEST_REVISION"
      fi
    else
      echo "Creating container app without secrets..."
      if ! az containerapp create \
        --name $CONTAINER_APP_NAME \
        --resource-group $RESOURCE_GROUP \
        --environment $CONTAINER_APP_ENV \
        --image $ACR_SERVER/$IMAGE_NAME:$DEPLOY_IMAGE_TAG \
        --registry-server $ACR_SERVER \
        --registry-username $ACR_USERNAME \
        --registry-password $ACR_PASSWORD \
        --target-port 8000 \
        --ingress internal \
        --cpu 0.5 \
        --memory 1.0Gi \
        --min-replicas 1 \
        --max-replicas 1 \
        --env-vars \
          PYTHONUNBUFFERED="1"; then
        echo "❌ Error: Failed to create container app"
        exit 1
      fi
    fi
else
    echo "📝 Loading environment variables from .env file..."
    
    # Load .env file safely (handle complex values like JSON)
    if [ -f .env ]; then
        while IFS='=' read -r key value; do
            # Skip comments and empty lines
            [[ $key =~ ^#.*$ ]] && continue
            [[ -z $key ]] && continue
            # Trim whitespace from key only
            key=$(echo "$key" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
            # For value, only trim leading/trailing whitespace but preserve internal content
            value=$(echo "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
            # Export the variable (use quotes to preserve special characters)
            export "$key"="$value"
        done < .env
    fi
    
    # Validate required environment variables
    echo "🔍 Validating environment variables..."
    MISSING_VARS=()
    
    if [ -z "$DISCORD_TOKEN" ]; then
        MISSING_VARS+=("DISCORD_TOKEN")
    fi
    
    if [ -z "$STEAM_API_KEY" ]; then
        MISSING_VARS+=("STEAM_API_KEY")
    fi
    
    if [ -z "$APPLICATION_ID" ]; then
        MISSING_VARS+=("APPLICATION_ID")
    fi
    
    if [ -z "$SERVER_CONFIGS" ]; then
        MISSING_VARS+=("SERVER_CONFIGS")
    fi
    
    if [ ${#MISSING_VARS[@]} -gt 0 ]; then
        echo "❌ Error: Missing required environment variables in .env file:"
        printf '   - %s\n' "${MISSING_VARS[@]}"
        echo ""
        echo "Please ensure your .env file contains:"
        echo "  DISCORD_TOKEN=your_token_here"
        echo "  STEAM_API_KEY=your_key_here"
        echo "  APPLICATION_ID=your_app_id_here"
        echo "  SERVER_CONFIGS=[{\"guild_id\": 123, \"status_channel_id\": 456}]"
        exit 1
    fi
    
    echo "✅ All required variables present"
    
    # Generate Django secret key if not provided
    if [ -z "$DJANGO_SECRET_KEY" ]; then
        DJANGO_SECRET_KEY=$(openssl rand -base64 32)
        echo "🔑 Generated Django secret key"
    fi
    
    if [ "$UPDATE_MODE" = true ]; then
      echo "🔄 Updating existing container app..."
      
      # Create temporary YAML file for update with health probes
      # Use YAML literal block scalar to handle JSON values properly
      TEMP_YAML=$(mktemp)
      
      # Write YAML with proper escaping for SERVER_CONFIGS JSON
      {
        echo "properties:"
        echo "  template:"
        echo "    containers:"
        echo "      - name: nebulous-bot"
        echo "        image: $ACR_SERVER/$IMAGE_NAME:$DEPLOY_IMAGE_TAG"
        echo "        env:"
        echo "          - name: DISCORD_TOKEN"
        echo "            secretRef: discord-token"
        echo "          - name: STEAM_API_KEY"
        echo "            secretRef: steam-api-key"
        echo "          - name: DJANGO_SECRET_KEY"
        echo "            secretRef: django-secret-key"
        echo "          - name: APPLICATION_ID"
        echo "            value: \"$APPLICATION_ID\""
        echo "          - name: SERVER_CONFIGS"
        echo "            value: |"
        echo "              $SERVER_CONFIGS"
        echo "          - name: PLAYER_THRESHOLD"
        echo "            value: \"${PLAYER_THRESHOLD:-40}\""
        echo "          - name: NOTIFICATION_INTERVAL"
        echo "            value: \"${NOTIFICATION_INTERVAL:-3600}\""
        echo "          - name: DEBUG"
        echo "            value: \"False\""
        echo "          - name: PYTHONUNBUFFERED"
        echo "            value: \"1\""
        echo "          - name: DJANGO_SETTINGS_MODULE"
        echo "            value: \"nebulous_project.settings\""
        echo "        probes:"
        echo "          - type: liveness"
        echo "            httpGet:"
        echo "              path: /health/"
        echo "              port: 8000"
        echo "            initialDelaySeconds: 30"
        echo "            periodSeconds: 30"
        echo "          - type: readiness"
        echo "            httpGet:"
        echo "              path: /health/"
        echo "              port: 8000"
        echo "            initialDelaySeconds: 10"
        echo "            periodSeconds: 10"
      } > "$TEMP_YAML"
      
      # Update container app with YAML (includes health probes)
      if ! az containerapp update \
        --name $CONTAINER_APP_NAME \
        --resource-group $RESOURCE_GROUP \
        --yaml "$TEMP_YAML"; then
        echo "❌ Error: Failed to update container app"
        rm -f "$TEMP_YAML"
        exit 1
      fi
      
      # Clean up temp file
      rm -f "$TEMP_YAML"
      
      # Verify the update created a new revision
      echo "   ⏳ Waiting for new revision to be created..."
      sleep 5
      
      # Get the latest revision
      LATEST_REVISION=$(az containerapp revision list \
        --name $CONTAINER_APP_NAME \
        --resource-group $RESOURCE_GROUP \
        --query "[0].name" -o tsv 2>/dev/null)
      
      if [ -n "$LATEST_REVISION" ]; then
        echo "   ✅ New revision created: $LATEST_REVISION"
        
        # Check revision status
        REVISION_STATUS=$(az containerapp revision show \
          --name $CONTAINER_APP_NAME \
          --resource-group $RESOURCE_GROUP \
          --revision $LATEST_REVISION \
          --query "properties.active" -o tsv 2>/dev/null)
        
        if [ "$REVISION_STATUS" == "True" ]; then
          echo "   ✅ Revision is active"
        else
          echo "   ⚠️  Warning: Revision exists but may not be active yet"
        fi
      else
        echo "   ⚠️  Warning: Could not verify new revision (deployment may still be in progress)"
      fi
      
      echo "   ✅ Container app updated with new image"
    else
      echo "🚢 Creating container app with secrets..."
      if ! az containerapp create \
        --name $CONTAINER_APP_NAME \
        --resource-group $RESOURCE_GROUP \
        --environment $CONTAINER_APP_ENV \
        --image $ACR_SERVER/$IMAGE_NAME:$DEPLOY_IMAGE_TAG \
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
          django-secret-key="$DJANGO_SECRET_KEY" \
        --env-vars \
          DISCORD_TOKEN=secretref:discord-token \
          STEAM_API_KEY=secretref:steam-api-key \
          DJANGO_SECRET_KEY=secretref:django-secret-key \
          APPLICATION_ID="$APPLICATION_ID" \
          SERVER_CONFIGS="$SERVER_CONFIGS" \
          PLAYER_THRESHOLD="${PLAYER_THRESHOLD:-40}" \
          NOTIFICATION_INTERVAL="${NOTIFICATION_INTERVAL:-3600}" \
          DEBUG="False" \
          PYTHONUNBUFFERED="1"; then
        echo "❌ Error: Failed to create container app"
        exit 1
      fi
      echo "   ✅ Container app created"
    fi
fi

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📊 View logs with:"
echo "   az containerapp logs show --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --follow"
echo ""
echo "🔄 Update the app with:"
echo "   az containerapp update --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --image $ACR_SERVER/$IMAGE_NAME:$DEPLOY_IMAGE_TAG"
echo ""
echo "📋 Check revision status with:"
echo "   az containerapp revision list --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP --output table"
echo ""
echo "🗑️  Delete resources with:"
echo "   az group delete --name $RESOURCE_GROUP"

