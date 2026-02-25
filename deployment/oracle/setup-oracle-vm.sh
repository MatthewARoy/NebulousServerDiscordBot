#!/bin/bash
# Setup script for Oracle Cloud Infrastructure VM
# Run this script on your Oracle Cloud VM after initial setup
# Prerequisites: Ubuntu 22.04 ARM64 instance with SSH access

set -e

echo "🚀 Setting up Nebulous Discord Bot on Oracle Cloud VM"
echo "===================================================="

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
   echo "❌ Please do not run as root. Run as 'ubuntu' user."
   exit 1
fi

# Update system
echo "📦 Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
echo "🐳 Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh
    
    # Add user to docker group
    sudo usermod -aG docker $USER
    echo "✅ Docker installed. You may need to log out and back in for group changes."
else
    echo "✅ Docker already installed"
fi

# Install Docker Compose
echo "🐳 Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "✅ Docker Compose installed"
else
    echo "✅ Docker Compose already installed"
fi

# Install git if not present
if ! command -v git &> /dev/null; then
    echo "📦 Installing git..."
    sudo apt-get install -y git
fi

# Create application directory
echo "📁 Creating application directory..."
mkdir -p ~/nebulous-bot
cd ~/nebulous-bot

# Create logs directory
mkdir -p logs

# Setup firewall
echo "🔥 Configuring firewall..."
sudo ufw --force enable
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 8000/tcp
echo "✅ Firewall configured"

# Check for block storage
echo "💾 Checking for block storage..."
if [ -b /dev/sdb ]; then
    echo "📦 Block storage device found: /dev/sdb"
    echo "   To format and mount, run:"
    echo "   sudo mkfs.ext4 /dev/sdb"
    echo "   sudo mkdir -p /mnt/bot-data"
    echo "   sudo mount /dev/sdb /mnt/bot-data"
    echo "   echo '/dev/sdb /mnt/bot-data ext4 defaults 0 2' | sudo tee -a /etc/fstab"
    echo "   sudo chown $USER:$USER /mnt/bot-data"
else
    echo "⚠️  No block storage device found. You may want to create and attach one for database persistence."
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Log out and back in (or run: newgrp docker) for Docker group changes"
echo "2. Create .env file in ~/nebulous-bot/ with your configuration"
echo "3. Create docker-compose.yml in ~/nebulous-bot/"
echo "4. Pull/build your Docker image"
echo "5. Run: docker-compose up -d"
echo ""
echo "See ORACLE_CLOUD_MIGRATION_GUIDE.md for detailed instructions."

