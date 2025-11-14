# Nebulous Discord Bot - Django + Azure Deployment

This is a Django-based Discord bot for monitoring Nebulous: Fleet Command servers, optimized for containerized deployment on Azure.

## 🏗️ Architecture

- **Framework**: Django 4.2+
- **Container**: Docker
- **Deployment**: Azure Container Apps / Azure Container Instances
- **Database**: SQLite (local) or PostgreSQL (Azure)
- **Bot Framework**: discord.py

## 🚀 Quick Start

### Local Development

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment variables**:
   ```bash
   cp env_example.txt .env
   # Edit .env with your configuration
   ```

3. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

4. **Start the bot**:
   ```bash
   python manage.py runbot
   ```

### Docker Local Testing

1. **Build the container**:
   ```bash
   # For Azure deployment (AMD64)
   docker build --platform linux/amd64 -t nebulous-bot .
   
   # For local testing only (native architecture)
   docker build -t nebulous-bot .
   ```

2. **Run with docker-compose**:
   ```bash
   docker-compose up
   ```

**Note for Apple Silicon (M1/M2/M3) users:** Always use `--platform linux/amd64` when building for Azure. The deployment scripts handle this automatically.

3. **View logs**:
   ```bash
   docker-compose logs -f bot
   ```

## ☁️ Azure Deployment

### Prerequisites

- Azure CLI installed (`az`)
- Azure subscription with Container Apps enabled
- Docker installed (for building images)

### First-Time Azure Setup

**Important:** Before deploying for the first time, register required Azure resource providers:

```bash
./setup-azure-providers.sh
```

This registers:
- `Microsoft.ContainerRegistry` (for container images)
- `Microsoft.App` (for Container Apps)
- `Microsoft.OperationalInsights` (for logging)

Registration takes 2-5 minutes. You only need to do this once per Azure subscription.

**Troubleshooting:** If you get "subscription not registered" errors, see [AZURE_TROUBLESHOOTING.md](AZURE_TROUBLESHOOTING.md)

### Option 1: Automated Deployment Script

```bash
# Set your Azure configuration
export AZURE_RESOURCE_GROUP="nebulous-bot-rg"
export AZURE_LOCATION="eastus"
export ACR_NAME="nebulousbot"

# Run deployment script
./deploy-azure.sh
```

### Option 2: Manual Azure Container Apps

1. **Create Resource Group**:
   ```bash
   az group create --name nebulous-bot-rg --location eastus
   ```

2. **Create Azure Container Registry**:
   ```bash
   az acr create \
     --resource-group nebulous-bot-rg \
     --name nebulousbot \
     --sku Basic \
     --admin-enabled true
   ```

3. **Build and push image**:
   ```bash
   az acr build \
     --registry nebulousbot \
     --image nebulous-bot:latest \
     --file Dockerfile \
     .
   ```

4. **Create Container App Environment**:
   ```bash
   az containerapp env create \
     --name nebulous-bot-env \
     --resource-group nebulous-bot-rg \
     --location eastus
   ```

5. **Deploy Container App**:
   ```bash
   az containerapp create \
     --name nebulous-discord-bot \
     --resource-group nebulous-bot-rg \
     --environment nebulous-bot-env \
     --image nebulousbot.azurecr.io/nebulous-bot:latest \
     --registry-server nebulousbot.azurecr.io \
     --target-port 8000 \
     --ingress internal \
     --cpu 0.5 \
     --memory 1.0Gi \
     --min-replicas 1 \
     --max-replicas 1 \
     --secrets \
       discord-token="YOUR_DISCORD_TOKEN" \
       steam-api-key="YOUR_STEAM_API_KEY" \
       django-secret-key="YOUR_DJANGO_SECRET_KEY" \
     --env-vars \
       DISCORD_TOKEN=secretref:discord-token \
       STEAM_API_KEY=secretref:steam-api-key \
       DJANGO_SECRET_KEY=secretref:django-secret-key \
       APPLICATION_ID="YOUR_APPLICATION_ID" \
       SERVER_CONFIGS='[{"guild_id": 1234567890, "status_channel_id": 0987654321}]'
   ```

### Option 3: Azure DevOps Pipeline

Use the included `azure-pipelines.yml` for CI/CD:

1. Import the repository into Azure DevOps
2. Create a new pipeline using `azure-pipelines.yml`
3. Configure service connections for Azure and ACR
4. Run the pipeline

### Managing Secrets in Azure

#### Using Azure Key Vault

```bash
# Create Key Vault
az keyvault create \
  --name nebulous-bot-kv \
  --resource-group nebulous-bot-rg \
  --location eastus

# Add secrets
az keyvault secret set --vault-name nebulous-bot-kv --name discord-token --value "YOUR_TOKEN"
az keyvault secret set --vault-name nebulous-bot-kv --name steam-api-key --value "YOUR_KEY"
az keyvault secret set --vault-name nebulous-bot-kv --name django-secret-key --value "YOUR_SECRET"

# Grant Container App access to Key Vault
# (Configure managed identity and access policies)
```

## 📊 Monitoring

### Health Checks

The bot exposes a health check endpoint at `/health/`:

```bash
curl http://localhost:8000/health/
# Response: {"status": "healthy"}
```

### Azure Monitoring

```bash
# View logs
az containerapp logs show \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --follow

# View metrics
az monitor metrics list \
  --resource <container-app-resource-id> \
  --metric "CpuUsage,MemoryUsage"
```

### Application Insights (Optional)

Add to your `.env`:
```env
APPINSIGHTS_INSTRUMENTATIONKEY=your-key
```

Uncomment in `requirements.txt`:
```
applicationinsights>=0.11.10
```

## 🗄️ Database Options

### SQLite (Default - Local/Testing)

No additional configuration needed. Database file: `db.sqlite3`

### PostgreSQL (Azure Production)

1. **Create Azure PostgreSQL**:
   ```bash
   az postgres flexible-server create \
     --resource-group nebulous-bot-rg \
     --name nebulous-db \
     --location eastus \
     --admin-user botadmin \
     --admin-password YourSecurePassword \
     --sku-name Standard_B1ms \
     --tier Burstable \
     --version 14
   ```

2. **Update settings** in `.env`:
   ```env
   DB_NAME=nebulous_bot
   DB_USER=botadmin
   DB_PASSWORD=YourSecurePassword
   DB_HOST=nebulous-db.postgres.database.azure.com
   DB_PORT=5432
   ```

3. **Uncomment PostgreSQL settings** in `nebulous_project/settings.py`

4. **Add psycopg2** to requirements.txt:
   ```bash
   pip install psycopg2-binary
   ```

## 🔧 Django Management Commands

### Run the Bot
```bash
python manage.py runbot
```

### Run Migrations
```bash
python manage.py migrate
```

### Create Superuser (for Django Admin)
```bash
python manage.py createsuperuser
```

### Collect Static Files
```bash
python manage.py collectstatic
```

## 🌐 Django Admin

Access the admin interface at `/admin/` to view:
- Bot status logs
- Notification history
- Server metrics

Create an admin user:
```bash
python manage.py createsuperuser
```

## 🔐 Security Best Practices

1. **Always use secrets management** (Azure Key Vault, not environment variables)
2. **Enable HTTPS** for production deployments
3. **Use managed identities** instead of service principals
4. **Regularly rotate secrets** and API keys
5. **Enable Azure Monitor** for audit logs
6. **Use private endpoints** for database connections
7. **Set DEBUG=False** in production

## 🐛 Troubleshooting

### Bot not connecting to Discord

```bash
# Check logs
docker logs nebulous-discord-bot

# Verify token
python manage.py shell
>>> from nebulous_bot.config import Config
>>> Config.DISCORD_TOKEN  # Should show your token
```

### Container won't start

```bash
# Check health endpoint
curl http://localhost:8000/health/

# View container logs
az containerapp logs show --name nebulous-discord-bot --resource-group nebulous-bot-rg --follow
```

### Database connection issues

```bash
# Test database connection
python manage.py dbshell

# Run migrations
python manage.py migrate --fake-initial
```

## 📁 Project Structure

```
NebulousServerDiscordBot/
├── nebulous_project/          # Django project
│   ├── __init__.py
│   ├── settings.py           # Django settings
│   ├── urls.py               # URL configuration
│   ├── wsgi.py              # WSGI application
│   └── asgi.py              # ASGI application
├── nebulous_bot/             # Django app
│   ├── management/
│   │   └── commands/
│   │       └── runbot.py    # Bot management command
│   ├── models.py            # Database models
│   ├── admin.py             # Admin configuration
│   ├── config.py            # Bot configuration
│   ├── server_monitor.py    # Server monitoring
│   ├── server_formatter.py  # Message formatting
│   └── steam_api.py         # Steam API integration
├── Dockerfile               # Docker configuration
├── docker-compose.yml       # Local docker compose
├── docker-compose.azure.yml # Azure docker compose
├── deploy-azure.sh          # Azure deployment script
├── azure-container-app.yaml # Azure Container App config
├── azure-pipelines.yml      # Azure DevOps pipeline
├── requirements.txt         # Python dependencies
├── manage.py               # Django management script
└── README_DJANGO.md        # This file
```

## 🔄 Updating the Deployment

### Update code and redeploy:

```bash
# Rebuild and push new image
az acr build \
  --registry nebulousbot \
  --image nebulous-bot:v2 \
  --file Dockerfile \
  .

# Update container app
az containerapp update \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --image nebulousbot.azurecr.io/nebulous-bot:v2
```

### Rolling back:

```bash
# List revisions
az containerapp revision list \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg

# Activate previous revision
az containerapp revision activate \
  --name nebulous-discord-bot \
  --resource-group nebulous-bot-rg \
  --revision <revision-name>
```

## 💰 Cost Optimization

- Use **Azure Container Apps** consumption plan (pay-per-use)
- Set `minReplicas: 1` and `maxReplicas: 1` (bot doesn't need scaling)
- Use **Burstable** SKU for PostgreSQL if needed
- Enable **auto-shutdown** for development environments
- Use **Spot instances** for non-critical workloads

## 📚 Additional Resources

- [Django Documentation](https://docs.djangoproject.com/)
- [discord.py Documentation](https://discordpy.readthedocs.io/)
- [Azure Container Apps Documentation](https://learn.microsoft.com/en-us/azure/container-apps/)
- [Azure CLI Reference](https://learn.microsoft.com/en-us/cli/azure/)

## 🆘 Support

For issues and questions:
1. Check the bot logs: `az containerapp logs show --follow`
2. Verify environment variables and secrets
3. Test locally with Docker first
4. Check Azure Container Apps troubleshooting guide

## 📝 License

This project is open source. See the main README for license details.

