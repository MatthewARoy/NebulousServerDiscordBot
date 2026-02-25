# Oracle Cloud Setup Checklist

**Complete checklist for setting up Oracle Cloud Infrastructure before database transfer**

---

## 📋 Pre-Setup Requirements

- [ ] Oracle Cloud account created (https://www.oracle.com/cloud/free/)
- [ ] Account verified and active
- [ ] $300 free credits available (optional, for testing)
- [ ] SSH key pair generated (`ssh-keygen -t rsa -b 4096`)

---

## 🖥️ Step 1: Create Compute Instance

### Via OCI Console

- [ ] Navigate to: Compute → Instances → Create Instance
- [ ] **Name**: `nebulous-bot-vm`
- [ ] **Image**: Ubuntu 22.04 (ARM64) - **CRITICAL: Must be ARM64**
- [ ] **Shape**: VM.Standard.A1.Flex (Always Free Eligible)
- [ ] **OCPUs**: 1 (or 2 for more power)
- [ ] **Memory**: 2GB (or 4GB if using 2 OCPUs)
- [ ] **Network**: 
  - [ ] Use default VCN or create new
  - [ ] Assign public IP address
- [ ] **SSH Keys**: 
  - [ ] Upload your public SSH key (`~/.ssh/id_rsa.pub`)
- [ ] **Create Instance**
- [ ] **Wait for instance to be running** (2-5 minutes)
- [ ] **Note the public IP address**

### Verify Instance

- [ ] SSH connection works: `ssh ubuntu@<public-ip>`
- [ ] Can run commands: `uname -a` (should show ARM64/aarch64)
- [ ] System is up to date: `sudo apt-get update`

---

## 💾 Step 2: Create Block Storage Volume

**This is CRITICAL for database persistence!**

### Create Volume

- [ ] Navigate to: Block Storage → Block Volumes → Create Block Volume
- [ ] **Name**: `nebulous-bot-data`
- [ ] **Size**: 50GB (free tier includes 200GB total)
- [ ] **Backup Policy**: None (free tier)
- [ ] **Create Volume**

### Attach to Instance

- [ ] Go to your compute instance
- [ ] Click "Attach Block Volume"
- [ ] Select `nebulous-bot-data`
- [ ] **Attachment Type**: Paravirtualized (default)
- [ ] **Access Type**: Read/Write
- [ ] **Attach**

### Format and Mount (On VM)

SSH into your VM and run:

```bash
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
# Should show the mounted volume with ~50GB available
```

**Verification:**
- [ ] Volume is mounted: `df -h | grep bot-data`
- [ ] Permissions correct: `ls -ld /mnt/bot-data` (should show ubuntu:ubuntu)
- [ ] Can write: `touch /mnt/bot-data/test && rm /mnt/bot-data/test`

---

## 🐳 Step 3: Install Docker and Tools

### Install Docker

```bash
# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
rm get-docker.sh

# Add user to docker group
sudo usermod -aG docker ubuntu

# Verify installation
docker --version
```

**Verification:**
- [ ] Docker installed: `docker --version`
- [ ] User in docker group: `groups | grep docker`
- [ ] Can run Docker: `docker ps` (may need to log out/in first)

### Install Docker Compose

```bash
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
docker-compose --version
```

**Verification:**
- [ ] Docker Compose installed: `docker-compose --version`

### Install SQLite (for database operations)

```bash
sudo apt-get install -y sqlite3
sqlite3 --version
```

**Verification:**
- [ ] SQLite installed: `sqlite3 --version`

### Install Git (for cloning repo, optional)

```bash
sudo apt-get install -y git
```

---

## 🔥 Step 4: Configure Firewall

```bash
# Enable firewall
sudo ufw --force enable

# Set defaults
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow SSH
sudo ufw allow 22/tcp

# Allow health check port (optional, for external monitoring)
sudo ufw allow 8000/tcp

# Check status
sudo ufw status
```

**Verification:**
- [ ] Firewall enabled: `sudo ufw status | grep Status`
- [ ] SSH allowed: `sudo ufw status | grep 22`
- [ ] Can still SSH: Test from another terminal

---

## 📁 Step 5: Create Application Directory

```bash
# Create directory
mkdir -p ~/nebulous-bot/logs

# Set permissions
chmod 755 ~/nebulous-bot
```

**Verification:**
- [ ] Directory exists: `ls -ld ~/nebulous-bot`
- [ ] Logs directory exists: `ls -d ~/nebulous-bot/logs`

---

## 🔐 Step 6: Security Hardening (Recommended)

### Disable Password Authentication

```bash
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication no
sudo systemctl restart sshd
```

**Verification:**
- [ ] Password auth disabled: `sudo grep PasswordAuthentication /etc/ssh/sshd_config`

### Set Up Automatic Security Updates

```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## ✅ Final Verification

Run these checks to ensure everything is ready:

```bash
# 1. Check system info
uname -a
# Should show: aarch64 (ARM64)

# 2. Check disk space
df -h
# Should show /mnt/bot-data with ~50GB

# 3. Check Docker
docker --version
docker-compose --version
docker ps

# 4. Check SQLite
sqlite3 --version

# 5. Check firewall
sudo ufw status

# 6. Check network
ping -c 1 8.8.8.8

# 7. Check disk write permissions
touch /mnt/bot-data/test-write && rm /mnt/bot-data/test-write && echo "✅ Write test passed"
```

**All checks should pass before proceeding to database transfer!**

---

## 📊 Resource Summary

After setup, you should have:

| Resource | Status | Notes |
|----------|--------|-------|
| Compute Instance | ✅ Running | ARM64, 1-2 OCPU, 2-4GB RAM |
| Block Storage | ✅ Mounted | 50GB at /mnt/bot-data |
| Docker | ✅ Installed | Version 24+ |
| Docker Compose | ✅ Installed | Latest version |
| SQLite | ✅ Installed | For database operations |
| Firewall | ✅ Configured | SSH + port 8000 allowed |
| Application Dir | ✅ Created | ~/nebulous-bot |

---

## 🚀 Next Steps

Once all items are checked:

1. **Transfer Database**: Use `transfer-database.sh` or follow `DATABASE_TRANSFER_GUIDE.md`
2. **Configure Bot**: Create `.env` file with `DB_PATH=/mnt/bot-data/db.sqlite3`
3. **Deploy Bot**: Use `deploy-to-oracle.sh` or manual deployment
4. **Verify**: Test bot and verify database is being used

---

## 🐛 Troubleshooting

### Block Storage Not Showing

```bash
# Check if volume is attached
sudo lsblk

# If not showing, check in OCI Console:
# - Volume is attached to instance
# - Instance is running
# - Try detaching and reattaching
```

### Docker Permission Denied

```bash
# Log out and back in
exit
ssh ubuntu@<vm-ip>

# Or use newgrp
newgrp docker
```

### Mount Not Persisting After Reboot

```bash
# Check /etc/fstab
cat /etc/fstab | grep bot-data

# Test mount
sudo mount -a

# Check if device name changed (use UUID instead)
sudo blkid /dev/sdb
# Use UUID in /etc/fstab instead of /dev/sdb
```

---

## 📚 Related Documentation

- **Full Migration Guide**: `ORACLE_CLOUD_MIGRATION_GUIDE.md`
- **Database Transfer**: `DATABASE_TRANSFER_GUIDE.md`
- **Deployment Scripts**: `deployment/oracle/README.md`

---

**Ready for database transfer?** Proceed to `DATABASE_TRANSFER_GUIDE.md`! 🚀

