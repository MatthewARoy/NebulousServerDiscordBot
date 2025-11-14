# 📚 Nebulous Discord Bot - Complete Documentation Index

## 🎯 Start Here

**New User?** → [QUICKSTART.md](QUICKSTART.md)  
**Existing User?** → [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)  
**Deploying to Azure?** → [README_DJANGO.md](README_DJANGO.md)

## 📖 Documentation

### Quick References

1. **[QUICKSTART.md](QUICKSTART.md)** - Choose your deployment method
   - Standalone Python
   - Django Framework
   - Docker Container
   - Azure Cloud

2. **[DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md)** - What changed in the conversion
   - Complete conversion overview
   - File structure changes
   - Feature comparison
   - Testing checklist

3. **[MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)** - Upgrade from standalone to Django
   - Step-by-step migration
   - No breaking changes
   - Rollback instructions
   - FAQ

### Detailed Guides

4. **[README.md](README.md)** - Standalone Python version
   - Original bot documentation
   - Feature list
   - Command reference
   - Troubleshooting

5. **[README_DJANGO.md](README_DJANGO.md)** - Django + Azure version
   - Django setup
   - Docker configuration
   - Azure deployment
   - Production best practices

## 🚀 Deployment Methods

### Local Development (Simplest)
```bash
# Standalone
python main.py

# Django
python manage.py runbot
```
**Documentation**: [README.md](README.md)

### Docker (Containerized)
```bash
docker-compose up
```
**Documentation**: [README_DJANGO.md](README_DJANGO.md) → Docker section

### Azure (Production Cloud)
```bash
./deploy-azure.sh
```
**Documentation**: [README_DJANGO.md](README_DJANGO.md) → Azure Deployment

## 🛠️ Setup & Configuration

### First Time Setup
1. Read [QUICKSTART.md](QUICKSTART.md)
2. Copy `env_example.txt` to `.env`
3. Configure your Discord and Steam tokens
4. Choose deployment method

### Migrating from Standalone
1. Read [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)
2. Run `python verify-setup.py`
3. Test with `python manage.py runbot`
4. Deploy to Azure if needed

### Verification
```bash
python verify-setup.py
```
This checks:
- Python version
- Required files
- Dependencies
- Configuration
- Docker (optional)
- Azure CLI (optional)

## 📁 Important Files

### Configuration
- `.env` - Environment variables (create from `env_example.txt`)
- `nebulous_project/settings.py` - Django settings
- `config.py` - Bot configuration (standalone)
- `nebulous_bot/config.py` - Bot configuration (Django)

### Deployment
- `Dockerfile` - Container image definition
- `docker-compose.yml` - Local Docker setup
- `deploy-azure.sh` - Azure deployment script
- `azure-container-app.yaml` - Azure configuration

### Entry Points
- `main.py` - Standalone bot entry
- `manage.py` - Django management
- `nebulous_bot/management/commands/runbot.py` - Django bot command

## 🎮 Bot Features

### Core Features
- ✅ Real-time server monitoring (30s updates)
- ✅ Discord commands (!listservers, !openlobbies, etc.)
- ✅ Auto-updating status messages
- ✅ Multi-server Discord support
- ✅ Player threshold notifications
- ✅ Role-based opt-in notifications

### Django-Specific Features
- ✅ Database logging (BotStatus, NotificationLog)
- ✅ Django Admin interface
- ✅ Health check endpoint
- ✅ Production-ready logging
- ✅ Better error handling

### Azure-Specific Features
- ✅ Container orchestration
- ✅ Auto-scaling (configurable)
- ✅ Azure Monitor integration
- ✅ Secrets management
- ✅ 99.9% SLA uptime

## 🔧 Common Tasks

### Running the Bot
```bash
# Standalone
python main.py

# Django
python manage.py runbot

# Docker
docker-compose up

# Azure
./deploy-azure.sh
```

### Database Management
```bash
# Create tables
python manage.py migrate

# Create admin user
python manage.py createsuperuser

# Access admin
# Open browser: http://localhost:8000/admin/
```

### Updating Configuration
```bash
# Edit .env file
nano .env

# Restart bot
# Standalone: Ctrl+C then python main.py
# Docker: docker-compose restart
# Azure: az containerapp restart
```

### Viewing Logs
```bash
# Standalone: Check nebulous_bot.log
tail -f nebulous_bot.log

# Docker
docker-compose logs -f

# Azure
az containerapp logs show --name nebulous-discord-bot --resource-group nebulous-bot-rg --follow
```

## 🆘 Troubleshooting

### Bot won't start
1. Check `.env` configuration
2. Verify Discord token
3. Check logs: `nebulous_bot.log`
4. Run: `python verify-setup.py`

### Docker issues
1. Check Docker is running
2. Rebuild: `docker-compose build --no-cache`
3. Check logs: `docker-compose logs`

### Azure deployment issues
1. Check Azure CLI: `az login`
2. Verify resource group exists
3. Check container logs
4. Verify secrets are set

### Import errors
```bash
# Reinstall dependencies
pip install -r requirements.txt

# Check Python version
python --version  # Need 3.8+
```

## 📊 Comparison Matrix

| Feature | Standalone | Django | Docker | Azure |
|---------|-----------|--------|--------|-------|
| **Setup Time** | 5 min | 10 min | 15 min | 30 min |
| **Complexity** | ⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ |
| **Cost** | Free | Free | Free | ~$15/mo |
| **Uptime** | Manual | Manual | Manual | 99.9% |
| **Database** | ❌ | ✅ | ✅ | ✅ |
| **Admin UI** | ❌ | ✅ | ✅ | ✅ |
| **Health Checks** | ❌ | ✅ | ✅ | ✅ |
| **Auto-Scaling** | ❌ | ❌ | ❌ | ✅ |
| **Monitoring** | Logs | Logs+DB | Logs+DB | Full |
| **Best For** | Testing | Production | Testing | Production |

## 🎓 Learning Path

### Beginner
1. Start with standalone: `python main.py`
2. Read [README.md](README.md)
3. Test bot commands in Discord

### Intermediate
1. Try Django: `python manage.py runbot`
2. Explore Admin UI: `/admin/`
3. Test Docker: `docker-compose up`

### Advanced
1. Deploy to Azure: `./deploy-azure.sh`
2. Set up monitoring
3. Configure auto-scaling
4. Implement CI/CD pipeline

## 🔗 External Resources

- [Django Documentation](https://docs.djangoproject.com/)
- [discord.py Documentation](https://discordpy.readthedocs.io/)
- [Docker Documentation](https://docs.docker.com/)
- [Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/)
- [Steam Web API](https://steamcommunity.com/dev)

## ✅ Quick Checklist

Before deploying, ensure:
- [ ] `.env` file created and configured
- [ ] Discord bot token obtained
- [ ] Steam API key obtained
- [ ] Discord server IDs configured
- [ ] Dependencies installed: `pip install -r requirements.txt`
- [ ] Verification passed: `python verify-setup.py`
- [ ] Tested locally first

## 📞 Support

**Setup Issues** → [QUICKSTART.md](QUICKSTART.md)  
**Migration Issues** → [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)  
**Django Issues** → [README_DJANGO.md](README_DJANGO.md)  
**Standalone Issues** → [README.md](README.md)

---

**Current Version**: Django + Azure Containerized  
**Backward Compatible**: Yes (standalone still works)  
**Production Ready**: Yes  
**Last Updated**: 2025

