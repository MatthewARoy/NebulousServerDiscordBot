# Database Transfer Guide: Azure to Oracle Cloud

**Complete guide for transferring your game database from Azure to Oracle Cloud**

---

## 📊 Database Overview

Your bot uses **SQLite** to store:

1. **GameSession** - Individual game sessions with:
   - Server information (ID, name, address)
   - Game details (map, mode, region)
   - Timing (lobby_start, game_start, game_end)
   - Player counts (at start, at end, max during game)
   - Game attributes (competitive, autobalance, password, etc.)
   - Status (ongoing, valid_game, duration)

2. **PlayerSnapshot** - Historical player count snapshots
3. **BotStatus** - Bot status metrics over time
4. **NotificationLog** - Player threshold notification logs

**Database File**: `db.sqlite3` (or custom path via `DB_PATH`)

---

## 🔍 Step 1: Locate Your Database on Azure

### Option A: Using Azure Files (Persistent Storage)

If you set up persistent storage, your database is at:
```
/mnt/data/db.sqlite3
```

**Download it:**
```bash
# From Azure Container App logs or via Azure CLI
az containerapp exec \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --command "cat /mnt/data/db.sqlite3" > db.sqlite3.backup

# Or download via Azure Storage (if using Azure Files)
az storage file download \
  --account-name <storage-account> \
  --share-name <file-share> \
  --path db.sqlite3 \
  --dest ./db.sqlite3.backup
```

### Option B: Ephemeral Storage (No Persistence)

If you didn't set up persistent storage, the database is in the container's filesystem:
```
/app/db.sqlite3
```

**Download it:**
```bash
# Copy from running container
az containerapp exec \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --command "cat /app/db.sqlite3" > db.sqlite3.backup

# Or download logs and extract (if database was logged - not recommended)
```

### Option C: Local Backup (If You Have One)

If you have a local backup:
```bash
# Use your existing backup
cp ~/backups/db.sqlite3.backup ./db.sqlite3.backup
```

---

## ✅ Step 2: Verify Database Integrity

Before transferring, verify your database is valid:

```bash
# Check if SQLite file is valid
sqlite3 db.sqlite3.backup "PRAGMA integrity_check;"

# Check table structure
sqlite3 db.sqlite3.backup ".tables"

# Count records in key tables
sqlite3 db.sqlite3.backup "SELECT COUNT(*) FROM nebulous_bot_gamesession;"
sqlite3 db.sqlite3.backup "SELECT COUNT(*) FROM nebulous_bot_playersnapshot;"
sqlite3 db.sqlite3.backup "SELECT COUNT(*) FROM nebulous_bot_botstatus;"
sqlite3 db.sqlite3.backup "SELECT COUNT(*) FROM nebulous_bot_notificationlog;"

# Check date range of games
sqlite3 db.sqlite3.backup "SELECT MIN(game_start), MAX(game_start) FROM nebulous_bot_gamesession;"
```

**Expected output:**
- Integrity check should return `ok`
- Tables should include: `nebulous_bot_gamesession`, `nebulous_bot_playersnapshot`, etc.
- Record counts should match your expectations

---

## 🚀 Step 3: Oracle Cloud Setup (Before Transfer)

### 3.1 Create Compute Instance

1. **Navigate**: OCI Console → Compute → Instances
2. **Create Instance**:
   - **Name**: `nebulous-bot-vm`
   - **Image**: Ubuntu 22.04 ARM64
   - **Shape**: VM.Standard.A1.Flex (Always Free)
   - **OCPUs**: 1 (or 2 for more power)
   - **Memory**: 2GB (or 4GB)
   - **SSH Keys**: Upload your public key

### 3.2 Create and Attach Block Storage

**This is critical for database persistence!**

1. **Create Block Volume**:
   - **Name**: `nebulous-bot-data`
   - **Size**: 50GB (free tier includes 200GB total)
   - **Backup Policy**: None (free tier)

2. **Attach to Instance**:
   - Go to your compute instance
   - Click "Attach Block Volume"
   - Select `nebulous-bot-data`
   - Attachment type: "Paravirtualized" (default)

3. **Format and Mount** (on VM):

```bash
# SSH into your VM
ssh ubuntu@<your-vm-ip>

# Find the attached volume
sudo lsblk
# Should show /dev/sdb or similar

# Format the volume (WARNING: This erases data!)
sudo mkfs.ext4 /dev/sdb

# Create mount point
sudo mkdir -p /mnt/bot-data

# Mount the volume
sudo mount /dev/sdb /mnt/bot-data

# Make it permanent (survives reboots)
echo '/dev/sdb /mnt/bot-data ext4 defaults 0 2' | sudo tee -a /etc/fstab

# Set permissions
sudo chown ubuntu:ubuntu /mnt/bot-data
sudo chmod 755 /mnt/bot-data

# Verify
df -h | grep bot-data
# Should show the mounted volume
```

### 3.3 Install Required Tools

```bash
# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install SQLite (for database operations)
sudo apt-get install -y sqlite3

# Install Docker (for running the bot)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker ubuntu

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Log out and back in for Docker group changes
exit
# SSH back in
```

---

## 📤 Step 4: Transfer Database to Oracle Cloud

### Method A: Direct Transfer (Recommended)

```bash
# On your local machine (with database backup)
scp db.sqlite3.backup ubuntu@<oracle-vm-ip>:~/db.sqlite3.backup

# On Oracle VM
ssh ubuntu@<oracle-vm-ip>

# Copy to mounted volume
cp ~/db.sqlite3.backup /mnt/bot-data/db.sqlite3

# Set permissions
chmod 644 /mnt/bot-data/db.sqlite3

# Verify
sqlite3 /mnt/bot-data/db.sqlite3 "PRAGMA integrity_check;"
sqlite3 /mnt/bot-data/db.sqlite3 "SELECT COUNT(*) FROM nebulous_bot_gamesession;"
```

### Method B: Using rsync (For Large Databases)

```bash
# On your local machine
rsync -avz --progress db.sqlite3.backup ubuntu@<oracle-vm-ip>:~/db.sqlite3.backup

# Then on VM, copy to mounted volume (same as Method A)
```

### Method C: Via Azure Storage (If Using Azure Files)

```bash
# Download from Azure Storage to local machine
az storage file download \
  --account-name <storage-account> \
  --share-name <file-share> \
  --path db.sqlite3 \
  --dest ./db.sqlite3.backup

# Then transfer to Oracle (use Method A or B)
```

---

## ✅ Step 5: Verify Database on Oracle Cloud

```bash
# SSH into Oracle VM
ssh ubuntu@<oracle-vm-ip>

# Check database integrity
sqlite3 /mnt/bot-data/db.sqlite3 "PRAGMA integrity_check;"

# Verify table structure
sqlite3 /mnt/bot-data/db.sqlite3 ".schema"

# Check record counts
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

# Check date range
sqlite3 /mnt/bot-data/db.sqlite3 "SELECT MIN(game_start), MAX(game_start) FROM nebulous_bot_gamesession;"

# Check ongoing games (if any)
sqlite3 /mnt/bot-data/db.sqlite3 "SELECT COUNT(*) FROM nebulous_bot_gamesession WHERE is_ongoing = 1;"
```

**All checks should match your Azure database!**

---

## 🔧 Step 6: Configure Bot to Use Transferred Database

### Update Environment Variables

On Oracle VM, create/update `.env` file:

```bash
cd ~/nebulous-bot
nano .env
```

**Critical setting:**
```env
# Database path - MUST point to mounted volume
DB_PATH=/mnt/bot-data/db.sqlite3
```

**Full .env example:**
```env
# Discord Configuration
DISCORD_TOKEN=your_discord_bot_token_here
APPLICATION_ID=your_application_id_here

# Server Configuration
SERVER_CONFIGS=[{"guild_id": 1234567890, "status_channel_id": 0987654321}]

# Steam API
STEAM_API_KEY=your_steam_api_key_here

# Django
DJANGO_SECRET_KEY=your_django_secret_here
DJANGO_SETTINGS_MODULE=nebulous_project.settings

# Database - CRITICAL: Points to transferred database
DB_PATH=/mnt/bot-data/db.sqlite3

# Optional
PLAYER_THRESHOLD=40
NOTIFICATION_INTERVAL=3600
DEBUG=False
PYTHONUNBUFFERED=1
```

### Update Docker Compose

Ensure `docker-compose.yml` mounts the volume:

```yaml
volumes:
  # Mount persistent storage for database
  - /mnt/bot-data:/mnt/data
```

**Note**: The bot expects the database at `/mnt/data/db.sqlite3` inside the container, but we mounted `/mnt/bot-data` to `/mnt/data`, so the path `/mnt/data/db.sqlite3` will work.

---

## 🚀 Step 7: Run Migrations (If Needed)

Django migrations should already be applied (they're in the database), but verify:

```bash
# On Oracle VM
cd ~/nebulous-bot

# Check migration status
docker-compose run --rm bot python manage.py showmigrations

# If any migrations are missing, apply them
docker-compose run --rm bot python manage.py migrate --noinput
```

**Important**: Migrations should show as already applied since the database schema is already in the transferred database.

---

## ✅ Step 8: Start Bot and Verify

```bash
# Start the bot
cd ~/nebulous-bot
docker-compose up -d

# Check logs
docker-compose logs -f

# Verify database is being used
docker-compose exec bot sqlite3 /mnt/data/db.sqlite3 "SELECT COUNT(*) FROM nebulous_bot_gamesession;"

# Test a command in Discord
# Use !stats to verify historical data is present
```

**Expected behavior:**
- Bot should start normally
- Logs should show no database errors
- `!stats` command should show your historical game data
- New games should be added to the existing database

---

## 🔄 Step 9: Handle Ongoing Games

If you have ongoing games in the database (`is_ongoing = 1`), they may need special handling:

```bash
# Check for ongoing games
sqlite3 /mnt/bot-data/db.sqlite3 "SELECT id, server_name, game_start, is_ongoing FROM nebulous_bot_gamesession WHERE is_ongoing = 1;"

# Option 1: Let them expire naturally (recommended)
# The bot will detect when games end and update them

# Option 2: Mark them as ended (if you know they're finished)
# sqlite3 /mnt/bot-data/db.sqlite3 "UPDATE nebulous_bot_gamesession SET is_ongoing = 0 WHERE is_ongoing = 1 AND game_start < datetime('now', '-1 hour');"
```

**Recommendation**: Let ongoing games expire naturally. The bot will detect when servers transition to debrief and update the records.

---

## 🛡️ Step 10: Backup Strategy

After successful transfer, set up regular backups:

```bash
# Create backup script on Oracle VM
cat > ~/backup-database.sh <<'EOF'
#!/bin/bash
BACKUP_DIR=~/backups
mkdir -p $BACKUP_DIR
BACKUP_FILE=$BACKUP_DIR/db-$(date +%Y%m%d-%H%M%S).sqlite3
cp /mnt/bot-data/db.sqlite3 $BACKUP_FILE
echo "Backup created: $BACKUP_FILE"
# Keep only last 7 days of backups
find $BACKUP_DIR -name "db-*.sqlite3" -mtime +7 -delete
EOF

chmod +x ~/backup-database.sh

# Test backup
~/backup-database.sh

# Add to crontab for daily backups at 2 AM
(crontab -l 2>/dev/null; echo "0 2 * * * $HOME/backup-database.sh") | crontab -
```

---

## 🐛 Troubleshooting

### Database Not Found

```bash
# Check if volume is mounted
df -h | grep bot-data

# Check file exists
ls -la /mnt/bot-data/db.sqlite3

# Check permissions
sudo chown ubuntu:ubuntu /mnt/bot-data/db.sqlite3
sudo chmod 644 /mnt/bot-data/db.sqlite3
```

### Permission Denied

```bash
# Fix ownership
sudo chown -R ubuntu:ubuntu /mnt/bot-data

# Fix permissions
sudo chmod 755 /mnt/bot-data
sudo chmod 644 /mnt/bot-data/db.sqlite3
```

### Database Locked

```bash
# Check if bot is running
docker-compose ps

# Stop bot temporarily
docker-compose down

# Verify database
sqlite3 /mnt/bot-data/db.sqlite3 "PRAGMA integrity_check;"

# Restart bot
docker-compose up -d
```

### Migration Errors

```bash
# Check migration status
docker-compose run --rm bot python manage.py showmigrations

# If migrations are out of sync, you may need to fake them
# (Only if database schema is already correct)
docker-compose run --rm bot python manage.py migrate --fake
```

### Data Mismatch

If record counts don't match:

```bash
# Compare databases side-by-side
# On Azure (before shutdown)
sqlite3 azure-db.sqlite3 "SELECT COUNT(*) FROM nebulous_bot_gamesession;" > azure-count.txt

# On Oracle
sqlite3 /mnt/bot-data/db.sqlite3 "SELECT COUNT(*) FROM nebulous_bot_gamesession;" > oracle-count.txt

# Compare
diff azure-count.txt oracle-count.txt
```

---

## 📋 Transfer Checklist

- [ ] Locate database on Azure
- [ ] Download database backup
- [ ] Verify database integrity
- [ ] Create Oracle Cloud compute instance
- [ ] Create and attach block storage volume
- [ ] Format and mount block storage
- [ ] Install SQLite and Docker on Oracle VM
- [ ] Transfer database file to Oracle VM
- [ ] Copy database to mounted volume (`/mnt/bot-data`)
- [ ] Verify database on Oracle VM
- [ ] Update `.env` with `DB_PATH=/mnt/bot-data/db.sqlite3`
- [ ] Update `docker-compose.yml` volume mounts
- [ ] Run migrations (verify they're already applied)
- [ ] Start bot and verify it uses transferred database
- [ ] Test Discord commands (`!stats`, `!mapstats`, etc.)
- [ ] Verify historical data is present
- [ ] Set up automated backups
- [ ] Monitor for 24-48 hours
- [ ] Decommission Azure resources (after verification)

---

## 📊 Database Size Considerations

**Typical sizes:**
- Small database (< 1 month): 1-10 MB
- Medium database (1-6 months): 10-50 MB
- Large database (6+ months): 50-200 MB

**Oracle Free Tier Block Storage:**
- 200GB total free
- 50GB recommended for database volume
- Plenty of room for growth

**Transfer time:**
- Small (< 10 MB): < 1 minute
- Medium (10-50 MB): 1-5 minutes
- Large (50+ MB): 5-15 minutes

---

## 🔐 Security Best Practices

1. **Encrypt during transfer:**
   ```bash
   # Use scp (encrypted by default)
   scp db.sqlite3.backup ubuntu@<vm-ip>:~/
   ```

2. **Secure on Oracle VM:**
   ```bash
   # Set proper permissions
   chmod 600 /mnt/bot-data/db.sqlite3
   ```

3. **Backup encryption** (optional):
   ```bash
   # Encrypt backup before storing
   gpg -c db.sqlite3.backup
   ```

---

## ✅ Success Criteria

Your transfer is successful when:

1. ✅ Database file exists at `/mnt/bot-data/db.sqlite3`
2. ✅ Integrity check passes: `PRAGMA integrity_check;` returns `ok`
3. ✅ Record counts match Azure database
4. ✅ Bot starts without database errors
5. ✅ `!stats` command shows historical data
6. ✅ New games are being added to the database
7. ✅ Database persists after container restart

---

**Ready to transfer?** Follow each step methodically, and verify at each stage! 🚀

