# 🚨 Database Wiped? Set Up Persistence Now!

Your database was wiped because persistent storage isn't configured. Here's how to fix it **right now** so it never happens again.

## Quick Fix (Choose One)

### Option 1: Automated Setup (Recommended - if you have Python)

```bash
# Install PyYAML if needed
pip3 install pyyaml

# Run the automated setup
./deployment/scripts/enable-persistence.sh
```

This fully automates everything - no manual steps needed!

### Option 2: Semi-Automated Setup (Manual step in Azure Portal)

```bash
# Run the setup script
./deployment/scripts/setup-persistent-storage.sh

# Then follow the instructions it prints
# (Just 2 minutes in Azure Portal)
```

## What This Does

1. ✅ Creates Azure Storage Account (~$0.06/month)
2. ✅ Creates file share for your database
3. ✅ Configures storage in Container App Environment
4. ✅ Mounts storage to `/mnt/data` in your container
5. ✅ Sets `DB_PATH=/mnt/data/db.sqlite3` environment variable

**Result**: Your database will survive all future deployments! 🎉

## After Setup

1. Redeploy to apply the changes:
   ```bash
   ./deployment/scripts/deploy-azure.sh
   ```

2. Verify it worked:
   ```bash
   # Check logs - should see database at /mnt/data/db.sqlite3
   az containerapp logs show \
     --name nebulous-discord-bot \
     --resource-group nebulous-bot-rg \
     --tail 20
   ```

3. Test in Discord - your stats should now persist!

## Cost

**~$0.06/month** for 1GB storage (very cheap!)

## Why This Happened

By default, Azure Container Apps use ephemeral storage that gets wiped on each deployment. This is normal for containerized apps, but we need to explicitly set up persistent storage for the database.

The deployment script now **warns you** if persistence isn't configured, so you'll know before deploying.

## Need Help?

- Full guide: `deployment/ENABLE_PERSISTENCE.md`
- Troubleshooting: See the guide above

