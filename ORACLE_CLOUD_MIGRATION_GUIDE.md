# Oracle Cloud Free Tier Migration Guide

**Complete guide for migrating from Azure Container Apps to Oracle Cloud Infrastructure (OCI) Free Tier**

> **📦 Database Transfer**: For detailed database transfer instructions, see **[DATABASE_TRANSFER_GUIDE.md](DATABASE_TRANSFER_GUIDE.md)**  
> **✅ Setup Checklist**: For a quick setup checklist, see **[deployment/oracle/ORACLE_SETUP_CHECKLIST.md](deployment/oracle/ORACLE_SETUP_CHECKLIST.md)**

---

## 📋 Overview

This guide covers migrating your Discord bot from Azure Container Apps to Oracle Cloud's Always Free tier, which provides:
- **2 Compute VMs** (ARM-based Ampere A1): 1/8 OCPU, 1GB RAM each (or combine for 1/4 OCPU, 2GB RAM)
- **200GB Block Storage** (free)
- **10TB egress data transfer** per month
- **No time limits** (truly free forever)

**Estimated Cost**: $0/month (completely free)

---

## 🔍 What Needs to Change

### Current Azure Setup
- ✅ Azure Container Apps (serverless containers)
- ✅ Azure Container Registry (Docker images)
- ✅ Azure Files (optional persistent storage)
- ✅ Azure Log Analytics
- ✅ Health check endpoints on port 8000

### Oracle Cloud Setup
- ✅ Compute VM (Ubuntu 22.04 ARM64)
- ✅ Docker installed on VM
- ✅ Local Docker registry or Docker Hub
- ✅ Block Storage volume for database persistence
- ✅ Systemd service for auto-restart
- ✅ Firewall rules for health checks

---

## 🚀 Migration Steps

### Step 1: Create Oracle Cloud Account

1. **Sign up**: https://www.oracle.com/cloud/free/
2. **Verify email** and complete account setup
3. **Access OCI Console**: https://cloud.oracle.com/

**Note**: You'll get $300 in free credits for 30 days, but the Always Free tier continues after credits expire.

---

### Step 2: Create Compute Instance

#### Via OCI Console:

1. **Navigate**: Compute → Instances → Create Instance
2. **Configure**:
   - **Name**: `nebulous-bot-vm`
   - **Image**: Ubuntu 22.04 (ARM64) - **Important: Must be ARM64 for free tier**
   - **Shape**: VM.Standard.A1.Flex (Always Free Eligible)
   - **OCPUs**: 1 (or 2 if you want more power)
   - **Memory**: 2 GB (or 4 GB if using 2 OCPUs)
   - **Network**: Use default VCN or create new
   - **SSH Keys**: Upload your public SSH key
3. **Create Instance**

#### Via OCI CLI (Alternative):

```bash
# Install OCI CLI first
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"

# Configure OCI CLI
oci setup config

# Create compute instance
oci compute instance launch \
  --availability-domain AD-1 \
  --compartment-id <your-compartment-id> \
  --shape VM.Standard.A1.Flex \
  --display-name nebulous-bot-vm \
  --image-id <ubuntu-22.04-arm64-image-id> \
  --subnet-id <your-subnet-id> \
  --assign-public-ip true \
  --shape-config '{"ocpus": 1, "memoryInGBs": 2}' \
  --ssh-authorized-keys-file ~/.ssh/id_rsa.pub
```

---

### Step 3: Set Up Block Storage for Database Persistence

**⚠️ CRITICAL**: Block storage is required for database persistence. Without it, your game data will be lost on container restart.

1. **Navigate**: Block Storage → Block Volumes → Create Block Volume
2. **Configure**:
   - **Name**: `nebulous-bot-data`
   - **Size**: 50 GB (free tier includes 200GB total)
   - **Backup Policy**: None (free tier)
3. **Attach to Instance**:
   - Go to your compute instance
   - Click "Attach Block Volume"
   - Select the volume and attach

4. **Format and Mount** (on the VM):

```bash
# SSH into your VM
ssh ubuntu@<your-vm-public-ip>

# Find the attached volume
sudo lsblk

# Format (replace /dev/sdb with your device)
# WARNING: This erases data on the volume!
sudo mkfs.ext4 /dev/sdb

# Create mount point
sudo mkdir -p /mnt/bot-data

# Mount
sudo mount /dev/sdb /mnt/bot-data

# Make it permanent
echo '/dev/sdb /mnt/bot-data ext4 defaults 0 2' | sudo tee -a /etc/fstab

# Set permissions
sudo chown ubuntu:ubuntu /mnt/bot-data
```

**📦 Database Transfer**: After setting up block storage, transfer your database from Azure. See **[DATABASE_TRANSFER_GUIDE.md](DATABASE_TRANSFER_GUIDE.md)** for complete instructions.

---

### Step 4: Install Docker on VM

```bash
# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker ubuntu

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker --version
docker-compose --version

# Log out and back in for group changes to take effect
exit
# SSH back in
```

---

### Step 5: Build and Push Docker Image

You have two options:

#### Option A: Use Docker Hub (Recommended)

```bash
# On your local machine
cd path/to/NebulousServerDiscordBot

# Build for ARM64 (Oracle uses ARM)
docker buildx build --platform linux/arm64 \
  -f deployment/docker/Dockerfile \
  -t <your-dockerhub-username>/nebulous-bot:latest \
  --push .

# Or tag existing image
docker tag nebulous-bot:latest <your-dockerhub-username>/nebulous-bot:latest
docker push <your-dockerhub-username>/nebulous-bot:latest
```

#### Option B: Build on the VM

```bash
# On the VM, clone your repo
git clone <your-repo-url>
cd NebulousServerDiscordBot

# Build directly on ARM64 VM
docker build -f deployment/docker/Dockerfile -t nebulous-bot:latest .
```

---

### Step 6: Configure Environment Variables

On the VM, create `.env` file:

```bash
cd /home/ubuntu
mkdir -p nebulous-bot
cd nebulous-bot

# Create .env file
nano .env
```

Add your configuration:

```env
# Discord Configuration
DISCORD_TOKEN=your_discord_bot_token_here
APPLICATION_ID=your_application_id_here

# Server Configuration (JSON format, single line!)
SERVER_CONFIGS=[{"guild_id": 1234567890, "status_channel_id": 0987654321}]

# Steam API
STEAM_API_KEY=your_steam_api_key_here

# Django
DJANGO_SECRET_KEY=your_django_secret_here
DJANGO_SETTINGS_MODULE=nebulous_project.settings

# Database (use mounted volume)
DB_PATH=/mnt/bot-data/db.sqlite3

# Optional
PLAYER_THRESHOLD=40
NOTIFICATION_INTERVAL=3600
DEBUG=False
PYTHONUNBUFFERED=1
```

---

### Step 7: Create Docker Compose File

On the VM, create `docker-compose.yml`:

```bash
nano docker-compose.yml
```

```yaml
version: '3.8'

services:
  bot:
    image: <your-dockerhub-username>/nebulous-bot:latest
    # Or use local image: image: nebulous-bot:latest
    container_name: nebulous-discord-bot
    env_file:
      - .env
    environment:
      - DJANGO_SETTINGS_MODULE=nebulous_project.settings
      - PYTHONUNBUFFERED=1
    volumes:
      # Mount persistent storage for database
      - /mnt/bot-data:/mnt/data
      # Mount logs
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
```

---

### Step 8: Configure Firewall

```bash
# Allow SSH
sudo ufw allow 22/tcp

# Allow health check port (if needed externally)
sudo ufw allow 8000/tcp

# Enable firewall
sudo ufw enable

# Check status
sudo ufw status
```

**Note**: For security, you may want to only allow port 8000 from specific IPs or use OCI Security Lists instead.

---

### Step 9: Create Systemd Service (Optional but Recommended)

Create a systemd service for automatic startup:

```bash
sudo nano /etc/systemd/system/nebulous-bot.service
```

```ini
[Unit]
Description=Nebulous Discord Bot
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/nebulous-bot
ExecStart=/usr/local/bin/docker-compose up -d
ExecStop=/usr/local/bin/docker-compose down
User=ubuntu
Group=ubuntu

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable nebulous-bot
sudo systemctl start nebulous-bot
sudo systemctl status nebulous-bot
```

---

### Step 10: Start the Bot

```bash
cd /home/ubuntu/nebulous-bot
docker-compose up -d

# Check logs
docker-compose logs -f

# Check status
docker-compose ps
```

---

## 🔧 Configuration Changes Required

### 1. Update `nebulous_project/settings.py`

The settings file already supports `DB_PATH` environment variable, so no changes needed if you set `DB_PATH=/mnt/bot-data/db.sqlite3` in your `.env`.

However, you may want to remove Azure-specific comments:

```python
# Remove or update this section (lines 87-102)
# The network storage configuration is still useful for mounted volumes
```

### 2. Update Dockerfile (if needed)

The Dockerfile should work as-is, but ensure it supports ARM64. The current Dockerfile uses `python:3.11-slim` which supports multi-arch.

### 3. Remove Azure-Specific Code

No code changes required - the application is already cloud-agnostic!

---

## 📊 Monitoring and Logs

### View Logs

```bash
# Docker Compose logs
cd /home/ubuntu/nebulous-bot
docker-compose logs -f

# Systemd service logs
sudo journalctl -u nebulous-bot -f

# Application logs
tail -f /home/ubuntu/nebulous-bot/logs/nebulous_bot.log
```

### Check Status

```bash
# Container status
docker ps

# Health check
curl http://localhost:8000/health/

# Bot process
docker exec nebulous-discord-bot ps aux | grep python
```

---

## 🔄 Updating the Bot

### Method 1: Pull New Image and Restart

```bash
cd /home/ubuntu/nebulous-bot

# Pull latest image
docker-compose pull

# Restart with new image
docker-compose up -d

# Or if using systemd
sudo systemctl restart nebulous-bot
```

### Method 2: Rebuild on VM

```bash
cd /home/ubuntu/nebulous-bot

# Pull latest code
git pull

# Rebuild
docker-compose build
docker-compose up -d
```

---

## 🗄️ Database Backup

### Backup Database

```bash
# Copy database from mounted volume
cp /mnt/bot-data/db.sqlite3 /home/ubuntu/backups/db-$(date +%Y%m%d).sqlite3

# Or use rsync for remote backup
rsync -avz /mnt/bot-data/db.sqlite3 user@backup-server:/backups/
```

### Restore Database

```bash
# Stop bot
docker-compose down

# Restore
cp /home/ubuntu/backups/db-20240101.sqlite3 /mnt/bot-data/db.sqlite3

# Start bot
docker-compose up -d
```

---

## 🔐 Security Best Practices

1. **SSH Keys Only**: Disable password authentication
   ```bash
   sudo nano /etc/ssh/sshd_config
   # Set: PasswordAuthentication no
   sudo systemctl restart sshd
   ```

2. **Firewall**: Only open necessary ports
   ```bash
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow 22/tcp
   ```

3. **Regular Updates**:
   ```bash
   sudo apt-get update && sudo apt-get upgrade -y
   ```

4. **Secrets Management**: Consider using OCI Vault (free tier) for secrets instead of `.env` file

5. **Backup Strategy**: Set up automated backups of `/mnt/bot-data`

---

## 💰 Cost Comparison

| Resource | Azure | Oracle Free Tier |
|----------|-------|------------------|
| Compute | ~$15-20/month | $0 (Always Free) |
| Container Registry | ~$5/month | $0 (Docker Hub free) |
| Storage | ~$0.06/month (1GB) | $0 (200GB free) |
| **Total** | **~$20-25/month** | **$0/month** |

---

## 🐛 Troubleshooting

### Bot Not Starting

```bash
# Check container logs
docker-compose logs bot

# Check if port is in use
sudo netstat -tulpn | grep 8000

# Check disk space
df -h

# Check memory
free -h
```

### Database Issues

```bash
# Check database file permissions
ls -la /mnt/bot-data/

# Fix permissions if needed
sudo chown ubuntu:ubuntu /mnt/bot-data/db.sqlite3
sudo chmod 644 /mnt/bot-data/db.sqlite3
```

### Connection Issues

```bash
# Test Discord connection
docker exec nebulous-discord-bot python -c "import discord; print('Discord library OK')"

# Check environment variables
docker exec nebulous-discord-bot env | grep DISCORD
```

### Out of Memory

Oracle free tier VMs have limited RAM (1-2GB). If you hit limits:

1. Reduce Docker memory usage
2. Use lighter base images
3. Upgrade to 2 OCPU instance (2GB RAM)

---

## 📝 Migration Checklist

- [ ] Create Oracle Cloud account
- [ ] Create compute instance (ARM64)
- [ ] Set up block storage volume
- [ ] Install Docker and Docker Compose
- [ ] Build/push Docker image (ARM64)
- [ ] Create `.env` file with credentials
- [ ] Create `docker-compose.yml`
- [ ] Configure firewall
- [ ] Set up systemd service (optional)
- [ ] Test bot startup
- [ ] Verify database persistence
- [ ] Set up backup strategy
- [ ] Test bot commands in Discord
- [ ] Monitor logs for 24 hours
- [ ] Decommission Azure resources (after verification)

---

## 🚨 Important Notes

1. **ARM64 Architecture**: Oracle free tier uses ARM processors. Ensure your Docker images support ARM64.

2. **Resource Limits**: Free tier has limited CPU/RAM. Monitor usage and optimize if needed.

3. **No Load Balancer**: Unlike Azure Container Apps, you'll have a single VM. Consider using OCI Load Balancer (paid) if you need high availability.

4. **IP Address**: Your VM gets a public IP. Consider using a reserved IP (free) to keep it static.

5. **Backup Strategy**: Set up automated backups - free tier doesn't include managed backup services.

---

## 📚 Additional Resources

- **OCI Documentation**: https://docs.oracle.com/en-us/iaas/Content/home.htm
- **OCI Free Tier Guide**: https://www.oracle.com/cloud/free/
- **Docker on ARM**: https://docs.docker.com/desktop/multi-arch/
- **OCI CLI Reference**: https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/

---

## ✅ Next Steps

1. **Test Locally**: Ensure your Docker image works on ARM64 (use Docker buildx)
2. **Create OCI Account**: Sign up and get familiar with the console
3. **Follow Steps**: Go through each step in this guide
4. **Monitor**: Watch logs for the first few days
5. **Optimize**: Adjust resources based on actual usage

---

**Ready to migrate?** Start with Step 1 and work through each section methodically. Good luck! 🚀

