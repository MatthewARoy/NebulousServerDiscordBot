# Enable Database Persistence

Your game statistics currently reset on each deployment. This guide shows you how to enable **persistent storage** so your database survives redeployments.

## Cost
**~$0.06 per month** (1GB Azure Files storage)

## Quick Setup (Recommended)

Run this one-time setup command:

```bash
cd deployment/scripts
./setup-persistent-storage.sh
```

Then follow the simple manual steps shown in the output (takes 2 minutes in Azure Portal).

## What This Does

1. Creates an Azure Storage Account (~$0.06/month)
2. Creates a file share for your database
3. Configures the storage in your Container App Environment
4. Shows you how to mount it to `/mnt/data` (manual step via Portal)

Once complete:
- Database file: `/mnt/data/db.sqlite3`
- Persists across all deployments
- Automatic backups via Azure Storage

## Alternative: Automated Setup (Advanced)

If you have Python 3 with PyYAML installed:

```bash
pip install pyyaml  # If not already installed
cd deployment/scripts
./enable-persistence.sh
```

This fully automates the setup using YAML configuration.

## Verifying It Works

After setup, deploy again:

```bash
./deployment/scripts/deploy-azure.sh
```

Your bot will now use the persistent database. Check with `!stats` to see your historical data is preserved!

## Troubleshooting

**"Storage account creation failed"**
- Make sure you're logged into Azure: `az login`
- Check your subscription is active: `az account show`

**"Database still resetting"**
- Verify the volume mount in Azure Portal:
  - Go to Container App → Containers → Volume mounts
  - Should see: `botdata-storage` mounted to `/mnt/data`
- Check environment variable is set: `DB_PATH=/mnt/data/db.sqlite3`

## Backup Your Database

Even with persistence, backups are good practice:

```bash
# Download current database
az storage file download \
  --account-name nebulousbotstorage \
  --share-name botdata \
  --path db.sqlite3 \
  --dest ./db.sqlite3.backup
```

## Future: Upgrade to PostgreSQL

For production at scale, consider Azure PostgreSQL (~$40/month):
- Better performance
- Concurrent access
- Automatic backups
- Point-in-time restore

Let me know if you want help setting that up!

