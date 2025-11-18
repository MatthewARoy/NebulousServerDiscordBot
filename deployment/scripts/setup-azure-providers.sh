#!/bin/bash
# Setup script to register required Azure resource providers
# Run this once before deploying to Azure

set -e

echo "🔧 Setting up Azure Resource Providers"
echo "========================================"
echo ""

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo "❌ Azure CLI not found. Please install it first."
    echo "   Visit: https://learn.microsoft.com/cli/azure/install-azure-cli"
    exit 1
fi

# Check if logged in
if ! az account show &> /dev/null; then
    echo "❌ Not logged in to Azure. Running 'az login'..."
    az login
fi

echo "✅ Azure CLI ready"
echo ""

# Get current subscription
SUBSCRIPTION=$(az account show --query name -o tsv)
echo "📋 Current subscription: $SUBSCRIPTION"
echo ""

# Register required providers
echo "📦 Registering required resource providers..."
echo "   (This may take 2-5 minutes on first run)"
echo ""

providers=(
    "Microsoft.ContainerRegistry"
    "Microsoft.App"
    "Microsoft.OperationalInsights"
)

for provider in "${providers[@]}"; do
    echo "   Registering $provider..."
    
    # Check if already registered
    state=$(az provider show --namespace $provider --query registrationState -o tsv 2>/dev/null || echo "NotRegistered")
    
    if [ "$state" == "Registered" ]; then
        echo "   ✅ $provider (already registered)"
    else
        az provider register --namespace $provider --wait
        echo "   ✅ $provider (newly registered)"
    fi
done

echo ""
echo "✅ All resource providers registered successfully!"
echo ""
echo "🚀 You can now run: ./deploy-azure.sh"

