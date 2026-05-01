#!/bin/bash
# Deployment script for Oracle Cloud Infrastructure
# This script helps deploy your bot to an existing OCI VM
# Prerequisites: 
#   - OCI VM already set up with Docker
#   - SSH access configured
#   - .env file ready
#
# Usage:
#   Option 1: Source config file first
#     source deployment/oracle/oci-config.sh
#     ./deployment/oracle/deploy-to-oracle.sh
#
#   Option 2: Set environment variables manually
#     export OCI_VM_HOST=your-vm-ip
#     export OCI_VM_USER=opc
#     export OCI_SSH_KEY=~/.ssh/id_ed25519
#     ./deployment/oracle/deploy-to-oracle.sh
#
#   Option 3: Non-interactive mode
#     BUILD_ON_VM=y ./deployment/oracle/deploy-to-oracle.sh
#     or
#     BUILD_ON_VM=n ./deployment/oracle/deploy-to-oracle.sh

set -e

# Try to load config file if it exists
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
if [ -f "$SCRIPT_DIR/oci-config.sh" ]; then
    source "$SCRIPT_DIR/oci-config.sh"
fi

# Configuration (can be overridden by oci-config.sh or environment variables)
VM_USER="${OCI_VM_USER:-opc}"
VM_HOST="${OCI_VM_HOST}"
VM_SSH_KEY="${OCI_SSH_KEY:-~/.ssh/id_ed25519}"
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"
REMOTE_DIR="${REMOTE_DIR:-~/NebulousServerDiscordBot}"
CONTAINER_NAME="${CONTAINER_NAME:-nebulous-discord-bot}"
BACKUP_KEEP="${BACKUP_KEEP:-2}"  # Keep last 2 deployment backups
REMOTE_BACKUP_DIR="${REMOTE_BACKUP_DIR:-/home/opc/nebulous-data/backups}"
PERSISTENT_DB_PATH="/home/opc/nebulous-data/db.sqlite3"

echo "🚀 Deploying Nebulous Discord Bot to Oracle Cloud"
echo "=================================================="

# Validate inputs
if [ -z "$VM_HOST" ]; then
    echo "❌ Error: OCI_VM_HOST not set"
    echo "   Usage: OCI_VM_HOST=your-vm-ip ./deploy-to-oracle.sh"
    exit 1
fi

# Check if .env exists
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "❌ Error: .env file not found in project root"
    echo "   Please create .env file with your configuration"
    exit 1
fi

echo "📋 Configuration:"
echo "   VM Host: $VM_HOST"
echo "   VM User: $VM_USER"
echo "   SSH Key: $VM_SSH_KEY"
echo "   Container: $CONTAINER_NAME"
echo "   Database: $PERSISTENT_DB_PATH"
echo "   Backup dir: $REMOTE_BACKUP_DIR (keep last $BACKUP_KEEP deployment backups)"
echo ""

# Test SSH connection
echo "🔌 Testing SSH connection..."
if ! ssh -i "$VM_SSH_KEY" -o ConnectTimeout=5 "$VM_USER@$VM_HOST" "echo 'Connection successful'" &> /dev/null; then
    echo "❌ Error: Cannot connect to VM via SSH"
    echo "   Please check:"
    echo "   - VM is running"
    echo "   - SSH key is correct"
    echo "   - Security list allows SSH (port 22)"
    exit 1
fi
echo "✅ SSH connection successful"

# Check Docker on remote
echo "🐳 Checking Docker installation..."
if ! ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "command -v docker" &> /dev/null; then
    echo "❌ Error: Docker not installed on VM"
    echo "   Please run setup-oracle-vm.sh on the VM first"
    exit 1
fi
echo "✅ Docker is installed"

# Detect Docker Compose command on remote (v2 uses 'docker compose', v1 uses 'docker-compose')
echo "🔍 Detecting Docker Compose version..."
DOCKER_COMPOSE_CMD=$(ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "if docker compose version &>/dev/null; then echo 'docker compose'; elif docker-compose version &>/dev/null; then echo 'docker-compose'; else echo 'NOT_FOUND'; fi")
if [ "$DOCKER_COMPOSE_CMD" = "NOT_FOUND" ]; then
    echo "❌ Error: Docker Compose not found on VM"
    echo "   Please install Docker Compose on the VM:"
    echo "   sudo curl -L \"https://github.com/docker/compose/releases/latest/download/docker-compose-\$(uname -s)-\$(uname -m)\" -o /usr/local/bin/docker-compose"
    echo "   sudo chmod +x /usr/local/bin/docker-compose"
    exit 1
fi
echo "✅ Using Docker Compose: $DOCKER_COMPOSE_CMD"

# Create remote directory
echo "📁 Creating remote directory..."
ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "mkdir -p $REMOTE_DIR/logs"

# Backup existing database BEFORE deployment (critical: happens before container stops)
echo "💾 Creating database backup before deployment..."
echo "   ⚠️  This backup protects your data - do not skip!"
ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "BACKUP_KEEP=$BACKUP_KEEP REMOTE_BACKUP_DIR=$REMOTE_BACKUP_DIR PERSISTENT_DB=$PERSISTENT_DB_PATH bash -s" <<'EOF'
set -euo pipefail  # Strict error handling
KEEP="${BACKUP_KEEP:-2}"
BACKUP_DIR="${REMOTE_BACKUP_DIR:-/home/opc/nebulous-data/backups}"
DB_FILE="${PERSISTENT_DB_PATH:-/home/opc/nebulous-data/db.sqlite3}"
TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)

echo "   - Backup dir: $BACKUP_DIR"
echo "   - Keep last: $KEEP backups"
echo "   - Source DB: $DB_FILE"

# Verify source database exists and is readable
if [ ! -f "$DB_FILE" ]; then
    echo "   ⚠️  Warning: Database file not found at $DB_FILE"
    echo "   ⚠️  Skipping backup (this may be a new deployment)"
    exit 0  # Don't fail deployment if no DB exists yet
fi

# Verify database is not empty (basic sanity check)
DB_SIZE=$(stat -f%z "$DB_FILE" 2>/dev/null || stat -c%s "$DB_FILE" 2>/dev/null || echo "0")
if [ "$DB_SIZE" -lt 1000 ]; then
    echo "   ⚠️  Warning: Database file is very small ($DB_SIZE bytes) - may be empty or corrupted"
    echo "   ⚠️  Proceeding with backup anyway..."
fi

# Create backup directory
mkdir -p "$BACKUP_DIR" || {
    echo "   ❌ Error: Cannot create backup directory $BACKUP_DIR"
    exit 1
}

# Create backup with timestamp
BACKUP_FILE="$BACKUP_DIR/db-deploy-$TIMESTAMP.sqlite3"
cp "$DB_FILE" "$BACKUP_FILE" || {
    echo "   ❌ Error: Failed to copy database to $BACKUP_FILE"
    exit 1
}

# Verify backup was created successfully
if [ ! -f "$BACKUP_FILE" ]; then
    echo "   ❌ Error: Backup file was not created"
    exit 1
fi

BACKUP_SIZE=$(stat -f%z "$BACKUP_FILE" 2>/dev/null || stat -c%s "$BACKUP_FILE" 2>/dev/null || echo "0")
if [ "$BACKUP_SIZE" -ne "$DB_SIZE" ]; then
    echo "   ⚠️  Warning: Backup size ($BACKUP_SIZE) differs from source ($DB_SIZE)"
fi

echo "   ✅ Backup created: $BACKUP_FILE ($(numfmt --to=iec-i --suffix=B $BACKUP_SIZE 2>/dev/null || echo ${BACKUP_SIZE}B))"

# Clean up old backups - keep only the last KEEP backups
# Only delete files matching the deploy backup pattern to avoid accidental deletion
OLD_BACKUPS=$(ls -1t "$BACKUP_DIR"/db-deploy-*.sqlite3 2>/dev/null | tail -n +$((KEEP + 1)) || true)
if [ -n "$OLD_BACKUPS" ]; then
    echo "   🗑️  Removing old backups (keeping last $KEEP):"
    echo "$OLD_BACKUPS" | while read -r old_backup; do
        if [ -f "$old_backup" ]; then
            echo "      - Removing: $(basename "$old_backup")"
            rm -f "$old_backup" || echo "      ⚠️  Warning: Failed to remove $old_backup"
        fi
    done
else
    echo "   ℹ️  No old backups to remove"
fi

# Final verification: list remaining backups
REMAINING=$(ls -1t "$BACKUP_DIR"/db-deploy-*.sqlite3 2>/dev/null | wc -l || echo "0")
echo "   📊 Total deployment backups remaining: $REMAINING"
EOF

BACKUP_EXIT_CODE=$?
if [ $BACKUP_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ ERROR: Database backup failed!"
    echo "   Deployment stopped to protect your data."
    echo "   Please check the backup directory and database file manually."
    exit 1
fi

# Copy .env file
echo "📝 Copying .env file..."
scp -i "$VM_SSH_KEY" "$PROJECT_ROOT/.env" "$VM_USER@$VM_HOST:$REMOTE_DIR/.env"

# Check if docker-compose.yml already exists on VM
echo "📝 Checking for existing docker-compose.yml..."
EXISTING_COMPOSE=$(ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "test -f $REMOTE_DIR/docker-compose.yml && echo 'EXISTS' || echo 'NOT_FOUND'")

# Build and push Docker image (if using Docker Hub)
echo ""
if [ -n "$BUILD_ON_VM" ]; then
    # Non-interactive mode - use environment variable
    echo "📦 Using BUILD_ON_VM=$BUILD_ON_VM (non-interactive mode)"
elif [ "$EXISTING_COMPOSE" = "EXISTS" ]; then
    echo "📦 Docker Image Options:"
    echo "   1. Build on VM (recommended for ARM64, will overwrite existing docker-compose.yml)"
    echo "   2. Use existing docker-compose.yml on VM"
    echo ""
    read -p "Build image on VM? (y/n) " -n 1 -r
    echo
    BUILD_ON_VM=$REPLY
else
    echo "📦 No docker-compose.yml found on VM"
    echo "   Building on VM to create docker-compose.yml..."
    echo ""
    BUILD_ON_VM="y"
fi

if [[ "$BUILD_ON_VM" =~ ^[Yy]$ ]]; then
    echo "🔨 Building Docker image on VM..."
    
    # Copy project files (excluding large directories)
    echo "📤 Copying project files..."
    rsync -avz --exclude '__pycache__' \
               --exclude '*.pyc' \
               --exclude '.git' \
               --exclude 'db.sqlite3' \
               --exclude '*.log' \
               --exclude 'node_modules' \
               --exclude '.env' \
               -e "ssh -i $VM_SSH_KEY" \
               "$PROJECT_ROOT/" "$VM_USER@$VM_HOST:$REMOTE_DIR/"
    
    # Create docker-compose.yml with build context
    echo "📝 Creating docker-compose.yml with build context..."
    ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "cat > $REMOTE_DIR/docker-compose.yml" <<'COMPOSE_EOF'
services:
  bot:
    build:
      context: .
      dockerfile: deployment/docker/Dockerfile
    container_name: nebulous-discord-bot
    env_file:
      - .env
    environment:
      - DJANGO_SETTINGS_MODULE=nebulous_project.settings
      - PYTHONUNBUFFERED=1
      - DB_PATH=/mnt/data/db.sqlite3
    volumes:
      - /home/opc/nebulous-data:/mnt/data
      - ./logs:/app/logs
    ports:
      - "8000:8000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/').read()"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
COMPOSE_EOF
    
    # Build on VM
    echo "🔨 Building Docker image..."
    ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "cd $REMOTE_DIR && $DOCKER_COMPOSE_CMD build" || {
        echo "⚠️  Build failed, trying with docker compose..."
        ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "cd $REMOTE_DIR && docker compose build"
    }
else
    # Use existing docker-compose.yml
    if [ "$EXISTING_COMPOSE" = "EXISTS" ]; then
        echo "✅ Using existing docker-compose.yml on VM"
        echo "⚠️  Make sure it has a valid image name or build configuration"
    else
        echo "❌ Error: No docker-compose.yml found on VM"
        echo ""
        echo "This shouldn't happen - the script should have auto-selected build option."
        exit 1
    fi
fi

# Stop existing container
echo "🛑 Stopping existing container..."
ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "cd $REMOTE_DIR && $DOCKER_COMPOSE_CMD down || true"

# Start new container
echo "🚀 Starting bot container..."
ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "cd $REMOTE_DIR && $DOCKER_COMPOSE_CMD up -d"

# Wait a moment
sleep 3

# Check status
echo "📊 Checking container status..."
ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "cd $REMOTE_DIR && $DOCKER_COMPOSE_CMD ps"

# Show logs
echo ""
echo "📋 Recent logs:"
ssh -i "$VM_SSH_KEY" "$VM_USER@$VM_HOST" "cd $REMOTE_DIR && $DOCKER_COMPOSE_CMD logs --tail=50"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📊 Useful commands:"
echo "   View logs: ssh $VM_USER@$VM_HOST 'cd $REMOTE_DIR && docker compose logs -f'"
echo "   Check status: ssh $VM_USER@$VM_HOST 'cd $REMOTE_DIR && docker compose ps'"
echo "   Restart: ssh $VM_USER@$VM_HOST 'cd $REMOTE_DIR && docker compose restart'"
echo "   Stop: ssh $VM_USER@$VM_HOST 'cd $REMOTE_DIR && docker compose down'"

