# Deployment Guide

This directory contains all deployment-related files for the Nebulous Server Discord Bot.

## Directory Structure

```
deployment/
├── azure/               # Azure-specific deployment files
│   ├── azure-container-app.yaml
│   ├── azure-pipelines.yml
│   └── TROUBLESHOOTING.md
├── docker/              # Docker configuration
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── docker-compose.azure.yml
└── scripts/             # Deployment helper scripts
    ├── deploy-azure.sh
    ├── deploy-azure-local-build.sh
    ├── check-azure-logs.sh
    ├── diagnose-azure-bot.sh
    ├── setup-azure-providers.sh
    ├── load-env.sh
    └── start-server.sh
```

## Quick Start

### Local Development
```bash
# From project root
python main.py
# or use the launcher
python run.py
```

### Docker (Local)
```bash
# From project root
cd deployment/docker
docker-compose up

# Or build and run from project root
docker-compose -f deployment/docker/docker-compose.yml up --build
```

### Azure Deployment
```bash
# From project root
cd deployment/scripts
./deploy-azure.sh
```

## Documentation

- **Azure Troubleshooting**: See `azure/TROUBLESHOOTING.md`
- **Main README**: See project root `README.md`
- **Django Setup**: See `../docs/README_DJANGO.md`

