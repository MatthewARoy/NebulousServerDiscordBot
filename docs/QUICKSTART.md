# Quick Start Guide

## Choose Your Deployment Method

### Option 1: Standalone Python (Simple)
Best for: Local development, small-scale use

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp env_example.txt .env
# Edit .env with your tokens

# Run the bot
python main.py
```

### Option 2: Django Framework (Recommended for Production)
Best for: Production deployments, scaling, monitoring

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp env_example.txt .env
# Edit .env with your tokens

# Run migrations
python manage.py migrate

# Start the bot
python manage.py runbot
```

### Option 3: Docker (Local Container)
Best for: Testing containerized deployment locally

```bash
# Configure environment
cp env_example.txt .env
# Edit .env with your tokens

# Build and run
docker-compose up --build
```

### Option 4: Azure Container Apps (Cloud Production)
Best for: Cloud production deployment, auto-scaling, high availability

```bash
# Prerequisites: Azure CLI installed, logged in
az login

# Configure environment
cp env_example.txt .env
# Edit .env with your tokens

# Deploy to Azure
chmod +x deploy-azure.sh
./deploy-azure.sh
```

See [README_DJANGO.md](README_DJANGO.md) for detailed Azure deployment instructions.

## Required Configuration

All deployment methods require these environment variables:

```env
DISCORD_TOKEN=your_discord_bot_token
APPLICATION_ID=your_application_id
STEAM_API_KEY=your_steam_api_key
SERVER_CONFIGS=[{"guild_id": 1234567890, "status_channel_id": 0987654321}]
```

### Getting Your Tokens

1. **Discord Bot Token**: https://discord.com/developers/applications
2. **Steam API Key**: https://steamcommunity.com/dev/apikey
3. **Guild/Channel IDs**: Enable Developer Mode in Discord, right-click → Copy ID

## What's the Difference?

| Feature | Standalone | Django | Docker | Azure |
|---------|-----------|--------|--------|-------|
| Setup Complexity | ⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ |
| Production Ready | ✅ | ✅✅ | ✅✅ | ✅✅✅ |
| Database Logging | ❌ | ✅ | ✅ | ✅ |
| Admin Interface | ❌ | ✅ | ✅ | ✅ |
| Health Monitoring | ❌ | ✅ | ✅ | ✅✅ |
| Auto-Scaling | ❌ | ❌ | ❌ | ✅ |
| Cloud Hosting | ❌ | ❌ | ❌ | ✅ |

## Next Steps

- **Standalone**: See main [README.md](README.md)
- **Django/Docker/Azure**: See [README_DJANGO.md](README_DJANGO.md)

