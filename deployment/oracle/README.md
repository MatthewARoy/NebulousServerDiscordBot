# Oracle Cloud Deployment

This directory contains scripts and configurations for deploying the Nebulous Discord Bot to Oracle Cloud Infrastructure (OCI) Free Tier.

## 📋 Prerequisites

1. **Oracle Cloud Account** with Always Free tier access
2. **Compute Instance** (VM.Standard.A1.Flex) running Ubuntu 22.04 ARM64
3. **SSH Access** to your VM
4. **Block Storage Volume** (optional, for database persistence)

## 🚀 Quick Start

### Step 1: Set Up VM

SSH into your Oracle Cloud VM and run:

```bash
# Download and run setup script
curl -fsSL https://raw.githubusercontent.com/your-repo/NebulousServerDiscordBot/main/deployment/oracle/setup-oracle-vm.sh -o setup-oracle-vm.sh
chmod +x setup-oracle-vm.sh
./setup-oracle-vm.sh

# Log out and back in for Docker group changes
exit
# SSH back in
```

Or copy the script manually:

```bash
# On your local machine
scp deployment/oracle/setup-oracle-vm.sh ubuntu@<your-vm-ip>:~/
ssh ubuntu@<your-vm-ip>
chmod +x setup-oracle-vm.sh
./setup-oracle-vm.sh
```

### Step 2: Configure Environment

On the VM, create `.env` file:

```bash
cd ~/nebulous-bot
nano .env
```

Add your configuration (see `ORACLE_CLOUD_MIGRATION_GUIDE.md` for details).

### Step 3: Deploy

**Option A: Automated Deployment (from local machine)**

```bash
# Set your VM details
export OCI_VM_HOST=your-vm-public-ip
export OCI_VM_USER=ubuntu
export OCI_SSH_KEY=~/.ssh/id_rsa

# Run deployment script
cd deployment/oracle
chmod +x deploy-to-oracle.sh
./deploy-to-oracle.sh
```

**Option B: Manual Deployment (on VM)**

```bash
# On the VM
cd ~/nebulous-bot

# Copy docker-compose.yml
cp deployment/oracle/docker-compose.oracle.yml docker-compose.yml

# Edit docker-compose.yml to set your Docker Hub username
nano docker-compose.yml

# Pull image (if using Docker Hub)
docker-compose pull

# Or build locally
docker-compose build

# Start
docker-compose up -d

# Check logs
docker-compose logs -f
```

## 📁 Files

- **`setup-oracle-vm.sh`**: Initial VM setup script (installs Docker, configures firewall)
- **`docker-compose.oracle.yml`**: Docker Compose configuration for OCI
- **`deploy-to-oracle.sh`**: Automated deployment script from local machine
- **`README.md`**: This file

## 🔧 Configuration

### Docker Image

You have two options for the Docker image:

1. **Docker Hub** (recommended): Build and push ARM64 image to Docker Hub
2. **Build on VM**: Clone repo and build directly on the ARM64 VM

### Database Persistence

If you've attached block storage:

1. Format and mount the volume to `/mnt/bot-data`
2. Set `DB_PATH=/mnt/bot-data/db.sqlite3` in `.env`
3. The docker-compose.yml already mounts this volume

### Resource Limits

The docker-compose.yml includes resource limits suitable for free tier:
- CPU: 0.25-1.0 cores
- Memory: 512MB-1.5GB

Adjust based on your VM size (1/8 OCPU = 0.125, 1/4 OCPU = 0.25, etc.)

## 🔍 Monitoring

### View Logs

```bash
# On VM
cd ~/nebulous-bot
docker-compose logs -f

# Or from local machine
ssh ubuntu@<vm-ip> "cd ~/nebulous-bot && docker-compose logs -f"
```

### Check Status

```bash
docker-compose ps
docker stats
```

### Health Check

```bash
curl http://localhost:8000/health/
```

## 🔄 Updating

### Method 1: Using Deployment Script

```bash
# From local machine
./deployment/oracle/deploy-to-oracle.sh
```

### Method 2: Manual Update

```bash
# On VM
cd ~/nebulous-bot

# Pull latest image
docker-compose pull

# Restart
docker-compose up -d
```

## 🐛 Troubleshooting

See `ORACLE_CLOUD_MIGRATION_GUIDE.md` for detailed troubleshooting steps.

Common issues:
- **Docker permission denied**: Log out and back in after adding user to docker group
- **Port already in use**: Check with `sudo netstat -tulpn | grep 8000`
- **Out of memory**: Reduce resource limits in docker-compose.yml
- **Database errors**: Check `/mnt/bot-data` permissions

## 📚 Additional Resources

- **Full Migration Guide**: `ORACLE_CLOUD_MIGRATION_GUIDE.md`
- **OCI Documentation**: https://docs.oracle.com/en-us/iaas/Content/home.htm
- **Docker Compose Docs**: https://docs.docker.com/compose/

