#!/bin/bash
# Test script to verify .env file is properly formatted

echo "🔍 Testing .env file configuration"
echo "=================================="

# Get the project root directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$PROJECT_ROOT"

if [ ! -f .env ]; then
    echo "❌ Error: .env file not found in project root"
    echo "   Expected location: $PROJECT_ROOT/.env"
    echo ""
    echo "Create .env file with:"
    echo "  cp env_example.txt .env"
    echo "  nano .env  # Edit with your credentials"
    exit 1
fi

echo "✅ Found .env file at: $PROJECT_ROOT/.env"
echo ""

# Load environment variables safely (handle complex values like JSON)
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

# Check each required variable
echo "Checking required variables:"
echo ""

check_var() {
    VAR_NAME=$1
    VAR_VALUE="${!VAR_NAME}"
    
    if [ -z "$VAR_VALUE" ]; then
        echo "❌ $VAR_NAME: NOT SET"
        return 1
    else
        # Mask the value for security (show first 10 chars only)
        MASKED="${VAR_VALUE:0:10}..."
        echo "✅ $VAR_NAME: $MASKED (${#VAR_VALUE} chars)"
        return 0
    fi
}

ERRORS=0

check_var "DISCORD_TOKEN" || ERRORS=$((ERRORS+1))
check_var "APPLICATION_ID" || ERRORS=$((ERRORS+1))
check_var "STEAM_API_KEY" || ERRORS=$((ERRORS+1))
check_var "SERVER_CONFIGS" || ERRORS=$((ERRORS+1))

echo ""
echo "Optional variables:"
check_var "DJANGO_SECRET_KEY" || echo "⚠️  DJANGO_SECRET_KEY: Not set (will be auto-generated)"
check_var "PLAYER_THRESHOLD" || echo "ℹ️  PLAYER_THRESHOLD: Not set (will use default: 40)"
check_var "NOTIFICATION_INTERVAL" || echo "ℹ️  NOTIFICATION_INTERVAL: Not set (will use default: 3600)"

echo ""
echo "=================================="

if [ $ERRORS -eq 0 ]; then
    echo "✅ All required variables are set!"
    echo ""
    echo "You're ready to deploy with:"
    echo "  ./deployment/scripts/deploy-azure.sh"
    exit 0
else
    echo "❌ $ERRORS required variable(s) missing"
    echo ""
    echo "Please edit your .env file and add the missing variables:"
    echo "  nano .env"
    exit 1
fi

