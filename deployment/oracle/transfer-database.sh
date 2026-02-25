#!/bin/bash
# Database transfer script for Azure to Oracle Cloud migration
# This script helps transfer the SQLite database from Azure to Oracle Cloud

set -e

echo "📦 Database Transfer: Azure to Oracle Cloud"
echo "==========================================="

# Configuration
ORACLE_VM_USER="${OCI_VM_USER:-ubuntu}"
ORACLE_VM_HOST="${OCI_VM_HOST}"
ORACLE_SSH_KEY="${OCI_SSH_KEY:-~/.ssh/id_rsa}"
AZURE_RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-nebulous-bot-rg}"
AZURE_CONTAINER_APP="${AZURE_CONTAINER_APP:-nebulous-discord-bot}"
BACKUP_DIR="./database-backups"
BACKUP_FILE="$BACKUP_DIR/db-$(date +%Y%m%d-%H%M%S).sqlite3"

echo ""
echo "📋 Configuration:"
echo "   Oracle VM: $ORACLE_VM_USER@$ORACLE_VM_HOST"
echo "   Azure Resource Group: $AZURE_RESOURCE_GROUP"
echo "   Azure Container App: $AZURE_CONTAINER_APP"
echo ""

# Validate inputs
if [ -z "$ORACLE_VM_HOST" ]; then
    echo "❌ Error: OCI_VM_HOST not set"
    echo "   Usage: OCI_VM_HOST=your-vm-ip ./transfer-database.sh"
    exit 1
fi

# Check Azure CLI
if ! command -v az &> /dev/null; then
    echo "⚠️  Warning: Azure CLI not found. You'll need to manually download the database."
    AZURE_AVAILABLE=false
else
    AZURE_AVAILABLE=true
    # Check if logged in
    if ! az account show &> /dev/null; then
        echo "⚠️  Warning: Not logged into Azure. Run 'az login' first."
        AZURE_AVAILABLE=false
    fi
fi

# Create backup directory
mkdir -p "$BACKUP_DIR"

echo "Step 1: Downloading database from Azure..."
echo "-------------------------------------------"

if [ "$AZURE_AVAILABLE" = true ]; then
    # Try to download from Azure Container App
    echo "Attempting to download from Azure Container App..."
    
    # Check if container app exists
    if az containerapp show --name "$AZURE_CONTAINER_APP" --resource-group "$AZURE_RESOURCE_GROUP" &> /dev/null; then
        echo "✅ Found Azure Container App"
        
        # Try to get database from /mnt/data (persistent storage)
        echo "Checking for database at /mnt/data/db.sqlite3..."
        if az containerapp exec \
            --name "$AZURE_CONTAINER_APP" \
            --resource-group "$AZURE_RESOURCE_GROUP" \
            --command "test -f /mnt/data/db.sqlite3 && echo 'EXISTS'" 2>/dev/null | grep -q "EXISTS"; then
            echo "✅ Found database at /mnt/data/db.sqlite3"
            echo "Downloading..."
            az containerapp exec \
                --name "$AZURE_CONTAINER_APP" \
                --resource-group "$AZURE_RESOURCE_GROUP" \
                --command "cat /mnt/data/db.sqlite3" > "$BACKUP_FILE" 2>/dev/null || {
                echo "⚠️  Failed to download via exec, trying alternative method..."
                AZURE_AVAILABLE=false
            }
        # Try /app/db.sqlite3 (ephemeral)
        elif az containerapp exec \
            --name "$AZURE_CONTAINER_APP" \
            --resource-group "$AZURE_RESOURCE_GROUP" \
            --command "test -f /app/db.sqlite3 && echo 'EXISTS'" 2>/dev/null | grep -q "EXISTS"; then
            echo "✅ Found database at /app/db.sqlite3"
            echo "Downloading..."
            az containerapp exec \
                --name "$AZURE_CONTAINER_APP" \
                --resource-group "$AZURE_RESOURCE_GROUP" \
                --command "cat /app/db.sqlite3" > "$BACKUP_FILE" 2>/dev/null || {
                echo "⚠️  Failed to download via exec"
                AZURE_AVAILABLE=false
            }
        else
            echo "⚠️  Database not found in container. Checking Azure Files..."
            AZURE_AVAILABLE=false
        fi
    else
        echo "⚠️  Azure Container App not found"
        AZURE_AVAILABLE=false
    fi
fi

# If Azure download failed, prompt for manual file
if [ ! -f "$BACKUP_FILE" ] || [ ! -s "$BACKUP_FILE" ]; then
    echo ""
    echo "⚠️  Could not download from Azure automatically."
    echo ""
    echo "Please provide the database file manually:"
    echo "  1. Download it from Azure using one of these methods:"
    echo "     - Azure Portal → Container App → Connect → Download file"
    echo "     - Azure Storage (if using Azure Files)"
    echo "     - Local backup if you have one"
    echo ""
    read -p "Enter path to database file (or press Enter to skip): " MANUAL_FILE
    
    if [ -n "$MANUAL_FILE" ] && [ -f "$MANUAL_FILE" ]; then
        cp "$MANUAL_FILE" "$BACKUP_FILE"
        echo "✅ Using provided database file"
    else
        echo "❌ No database file provided. Exiting."
        exit 1
    fi
fi

# Verify database
echo ""
echo "Step 2: Verifying database integrity..."
echo "----------------------------------------"

if ! command -v sqlite3 &> /dev/null; then
    echo "⚠️  Warning: sqlite3 not installed. Skipping verification."
    echo "   Install with: brew install sqlite3 (macOS) or apt-get install sqlite3 (Linux)"
else
    # Check integrity
    INTEGRITY=$(sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" 2>/dev/null)
    if [ "$INTEGRITY" = "ok" ]; then
        echo "✅ Database integrity check passed"
    else
        echo "❌ Database integrity check failed: $INTEGRITY"
        echo "   The database may be corrupted. Proceed with caution."
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    # Show record counts
    echo ""
    echo "📊 Database contents:"
    sqlite3 "$BACKUP_FILE" <<EOF
SELECT 
    'GameSession' as table_name, COUNT(*) as count FROM nebulous_bot_gamesession
UNION ALL
SELECT 'PlayerSnapshot', COUNT(*) FROM nebulous_bot_playersnapshot
UNION ALL
SELECT 'BotStatus', COUNT(*) FROM nebulous_bot_botstatus
UNION ALL
SELECT 'NotificationLog', COUNT(*) FROM nebulous_bot_notificationlog;
EOF
    
    # Show date range
    echo ""
    echo "📅 Game date range:"
    sqlite3 "$BACKUP_FILE" "SELECT MIN(game_start) as earliest, MAX(game_start) as latest FROM nebulous_bot_gamesession WHERE game_start IS NOT NULL;"
    
    # Show ongoing games
    ONGOING=$(sqlite3 "$BACKUP_FILE" "SELECT COUNT(*) FROM nebulous_bot_gamesession WHERE is_ongoing = 1;" 2>/dev/null || echo "0")
    if [ "$ONGOING" -gt 0 ]; then
        echo ""
        echo "⚠️  Warning: $ONGOING ongoing game(s) found. These will be handled by the bot."
    fi
fi

# Get file size
FILE_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo ""
echo "✅ Database file ready: $BACKUP_FILE ($FILE_SIZE)"

# Test SSH connection
echo ""
echo "Step 3: Testing Oracle Cloud VM connection..."
echo "-----------------------------------------------"

if ! ssh -i "$ORACLE_SSH_KEY" -o ConnectTimeout=5 "$ORACLE_VM_USER@$ORACLE_VM_HOST" "echo 'Connection successful'" &> /dev/null; then
    echo "❌ Error: Cannot connect to Oracle VM via SSH"
    echo "   Please check:"
    echo "   - VM is running"
    echo "   - SSH key is correct"
    echo "   - Security list allows SSH (port 22)"
    exit 1
fi
echo "✅ SSH connection successful"

# Check if block storage is mounted
echo ""
echo "Step 4: Checking Oracle VM setup..."
echo "------------------------------------"

MOUNT_CHECK=$(ssh -i "$ORACLE_SSH_KEY" "$ORACLE_VM_USER@$ORACLE_VM_HOST" "test -d /mnt/bot-data && echo 'MOUNTED' || echo 'NOT_MOUNTED'")
if [ "$MOUNT_CHECK" != "MOUNTED" ]; then
    echo "⚠️  Warning: /mnt/bot-data not found or not mounted"
    echo ""
    echo "Please set up block storage first:"
    echo "  1. Create block volume in OCI Console"
    echo "  2. Attach to compute instance"
    echo "  3. Format and mount:"
    echo "     sudo mkfs.ext4 /dev/sdb"
    echo "     sudo mkdir -p /mnt/bot-data"
    echo "     sudo mount /dev/sdb /mnt/bot-data"
    echo "     echo '/dev/sdb /mnt/bot-data ext4 defaults 0 2' | sudo tee -a /etc/fstab"
    echo "     sudo chown $ORACLE_VM_USER:$ORACLE_VM_USER /mnt/bot-data"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✅ Block storage is mounted at /mnt/bot-data"
fi

# Transfer database
echo ""
echo "Step 5: Transferring database to Oracle Cloud..."
echo "------------------------------------------------"

echo "Uploading database file..."
scp -i "$ORACLE_SSH_KEY" "$BACKUP_FILE" "$ORACLE_VM_USER@$ORACLE_VM_HOST:~/db.sqlite3.backup"

echo "Copying to mounted volume..."
ssh -i "$ORACLE_SSH_KEY" "$ORACLE_VM_USER@$ORACLE_VM_HOST" <<'ENDSSH'
# Create backup of existing database if it exists
if [ -f /mnt/bot-data/db.sqlite3 ]; then
    echo "⚠️  Existing database found, creating backup..."
    cp /mnt/bot-data/db.sqlite3 /mnt/bot-data/db.sqlite3.backup-$(date +%Y%m%d-%H%M%S)
fi

# Copy new database
cp ~/db.sqlite3.backup /mnt/bot-data/db.sqlite3

# Set permissions
chmod 644 /mnt/bot-data/db.sqlite3

# Verify
if [ -f /mnt/bot-data/db.sqlite3 ]; then
    echo "✅ Database copied successfully"
    ls -lh /mnt/bot-data/db.sqlite3
else
    echo "❌ Error: Database file not found after copy"
    exit 1
fi
ENDSSH

# Verify on remote
echo ""
echo "Step 6: Verifying database on Oracle VM..."
echo "------------------------------------------"

ssh -i "$ORACLE_SSH_KEY" "$ORACLE_VM_USER@$ORACLE_VM_HOST" <<'ENDSSH'
if command -v sqlite3 &> /dev/null; then
    echo "Running integrity check..."
    INTEGRITY=$(sqlite3 /mnt/bot-data/db.sqlite3 "PRAGMA integrity_check;" 2>/dev/null)
    if [ "$INTEGRITY" = "ok" ]; then
        echo "✅ Database integrity check passed"
    else
        echo "⚠️  Integrity check result: $INTEGRITY"
    fi
    
    echo ""
    echo "Record counts:"
    sqlite3 /mnt/bot-data/db.sqlite3 <<EOF
SELECT 
    'GameSession' as table_name, COUNT(*) as count FROM nebulous_bot_gamesession
UNION ALL
SELECT 'PlayerSnapshot', COUNT(*) FROM nebulous_bot_playersnapshot
UNION ALL
SELECT 'BotStatus', COUNT(*) FROM nebulous_bot_botstatus
UNION ALL
SELECT 'NotificationLog', COUNT(*) FROM nebulous_bot_notificationlog;
EOF
else
    echo "⚠️  sqlite3 not installed on VM. Install with: sudo apt-get install sqlite3"
fi
ENDSSH

echo ""
echo "✅ Database transfer complete!"
echo ""
echo "Next steps:"
echo "1. Ensure .env file has: DB_PATH=/mnt/bot-data/db.sqlite3"
echo "2. Ensure docker-compose.yml mounts: /mnt/bot-data:/mnt/data"
echo "3. Start the bot: docker-compose up -d"
echo "4. Verify with: docker-compose logs -f"
echo "5. Test in Discord: !stats (should show historical data)"
echo ""
echo "Backup saved locally at: $BACKUP_FILE"

