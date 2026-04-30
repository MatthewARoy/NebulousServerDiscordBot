# Migration Guide: Standalone → Django + Azure

This guide helps you migrate from the standalone Python bot to the Django + containerized Azure deployment.

## What Changed?

### File Structure

**Before (Standalone)**:
```
├── main.py              # Main bot file
├── config.py           # Configuration
├── server_monitor.py   # Monitoring logic
├── requirements.txt    # Dependencies
└── .env               # Environment variables
```

**After (Django)**:
```
├── nebulous_project/           # Django project
│   ├── settings.py
│   └── urls.py
├── nebulous_bot/              # Django app
│   ├── management/commands/
│   │   └── runbot.py         # Bot management command
│   ├── config.py
│   ├── server_monitor.py
│   └── models.py             # NEW: Database models
├── Dockerfile                 # NEW: Container config
├── docker-compose.yml         # NEW: Local deployment
├── deploy-azure.sh           # NEW: Azure deployment
├── manage.py                 # NEW: Django management
└── .env                      # Environment variables
```

## Migration Steps

### Step 1: Backup Your Current Setup

```bash
# Backup your .env file
cp .env .env.backup

# Stop your current bot
# (Ctrl+C if running in terminal)
```

### Step 2: Install New Dependencies

```bash
pip install -r requirements.txt
```

This now includes Django and other new dependencies.

### Step 3: Update Environment Variables

Your `.env` file should still work, but optionally add:

```env
# Django-specific (optional)
DJANGO_SECRET_KEY=your-generated-secret-key
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Step 4: Initialize Django Database

```bash
python manage.py migrate
```

This creates the database for logging and admin features.

### Step 5: Run the Bot

**Standalone mode still works**:
```bash
python main.py  # Old way still works!
```

**Django mode (recommended)**:
```bash
python manage.py runbot  # New way
```

**Docker mode**:
```bash
docker-compose up
```

## Key Differences

### Running the Bot

| Aspect | Standalone | Django |
|--------|-----------|--------|
| Command | `python main.py` | `python manage.py runbot` |
| Database | None | SQLite or PostgreSQL |
| Admin Interface | None | `/admin/` endpoint |
| Health Checks | None | `/health/` endpoint |
| Logging | File only | File + Database |

### New Features with Django

1. **Database Logging**: Bot status and notifications are logged to database
2. **Admin Interface**: View logs and metrics at `/admin/`
3. **Health Monitoring**: Health check endpoint for container orchestration
4. **Better Structure**: Django app structure for easier maintenance

### Configuration Changes

**No breaking changes!** Your existing `.env` configuration works as-is.

Optional additions:
- `DJANGO_SECRET_KEY` - for Django security (auto-generated if not set)
- `DEBUG` - set to False for production
- Database configuration for PostgreSQL

## Deployment Options

### Local Development (No Change)

```bash
# Still works exactly the same
python main.py
```

### Local with Django

```bash
python manage.py runbot
```

### Docker (Local)

```bash
docker-compose up
```

### Azure (Production)

```bash
./deploy-azure.sh
```

## Rollback Plan

If you need to rollback to standalone:

1. Stop the Django/Docker bot
2. Use your backed-up `.env`
3. Run the original command:
   ```bash
   python main.py
   ```

All original files (`main.py`, `config.py`, etc.) are still present and functional!

## FAQ

### Q: Do I have to use Django?
**A:** No! The standalone `python main.py` still works. Django is optional for production features.

### Q: Will my bot settings change?
**A:** No, all your configuration stays the same.

### Q: Do I need Azure?
**A:** No, you can run locally with or without Docker.

### Q: What if I just want Docker locally?
**A:** Just use `docker-compose up` - no Azure needed.

### Q: Can I use both versions?
**A:** Yes! You can run standalone locally and Django in production.

### Q: What about my Discord server configs?
**A:** No changes needed. `SERVER_CONFIGS` works exactly the same.

## Troubleshooting

### "Module not found" errors

```bash
# Reinstall dependencies
pip install -r requirements.txt
```

### Django database errors

```bash
# Reset database
rm db.sqlite3
python manage.py migrate
```

### Import errors

Make sure you're in the project root directory when running commands.

### Docker build fails

```bash
# Clean and rebuild
docker-compose down
docker-compose build --no-cache
docker-compose up
```

## Need Help?

- **Standalone issues**: See [README.md](README.md)
- **Django/Azure issues**: See [README_DJANGO.md](README_DJANGO.md)
- **Quick comparison**: See [QUICKSTART.md](QUICKSTART.md)

## Summary

✅ **No breaking changes** - standalone mode still works  
✅ **Backward compatible** - existing config works  
✅ **Optional upgrade** - use Django features when ready  
✅ **Flexible deployment** - local, Docker, or Azure  
✅ **Easy rollback** - original files still present

