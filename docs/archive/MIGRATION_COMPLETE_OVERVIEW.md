# Complete Migration Overview: Azure to Oracle Cloud

**Everything you need to know about migrating your Discord bot and database**

---

## 📚 Documentation Index

### Main Guides

1. **[ORACLE_CLOUD_MIGRATION_GUIDE.md](ORACLE_CLOUD_MIGRATION_GUIDE.md)**
   - Complete step-by-step migration guide
   - Covers all aspects of the migration
   - **Start here for the full process**

2. **[DATABASE_TRANSFER_GUIDE.md](DATABASE_TRANSFER_GUIDE.md)**
   - Detailed database transfer instructions
   - How to locate, download, and transfer your SQLite database
   - Verification and troubleshooting steps
   - **Essential if you have game data to preserve**

3. **[MIGRATION_SUMMARY.md](MIGRATION_SUMMARY.md)**
   - Quick reference and comparison
   - Cost savings overview
   - Key differences between Azure and Oracle

### Setup Checklists

4. **[deployment/oracle/ORACLE_SETUP_CHECKLIST.md](deployment/oracle/ORACLE_SETUP_CHECKLIST.md)**
   - Step-by-step checklist for Oracle Cloud setup
   - Verification steps for each component
   - **Use this to ensure everything is configured correctly**

### Deployment Scripts

5. **[deployment/oracle/README.md](deployment/oracle/README.md)**
   - Quick start guide for deployment scripts
   - Usage instructions for all scripts

6. **[deployment/oracle/setup-oracle-vm.sh](deployment/oracle/setup-oracle-vm.sh)**
   - Automated VM setup script
   - Installs Docker, configures firewall, etc.

7. **[deployment/oracle/deploy-to-oracle.sh](deployment/oracle/deploy-to-oracle.sh)**
   - Automated deployment script
   - Deploys bot from local machine to Oracle VM

8. **[deployment/oracle/transfer-database.sh](deployment/oracle/transfer-database.sh)**
   - Automated database transfer script
   - Downloads from Azure and uploads to Oracle

---

## 🎯 Migration Paths

### Path 1: Fresh Start (No Database to Transfer)

**Use this if:**
- You don't have important game data to preserve
- You're okay starting with a fresh database
- You want the simplest migration

**Steps:**
1. Follow **[ORACLE_CLOUD_MIGRATION_GUIDE.md](ORACLE_CLOUD_MIGRATION_GUIDE.md)** Steps 1-10
2. Skip database transfer steps
3. Bot will create a new database on first run

**Time**: ~30-60 minutes

---

### Path 2: Preserve Database (Recommended)

**Use this if:**
- You have game statistics you want to keep
- You have historical data (games, player snapshots, etc.)
- You want a seamless transition

**Steps:**
1. Follow **[ORACLE_SETUP_CHECKLIST.md](deployment/oracle/ORACLE_SETUP_CHECKLIST.md)** to set up Oracle Cloud
2. Follow **[DATABASE_TRANSFER_GUIDE.md](DATABASE_TRANSFER_GUIDE.md)** to transfer database
3. Follow **[ORACLE_CLOUD_MIGRATION_GUIDE.md](ORACLE_CLOUD_MIGRATION_GUIDE.md)** Steps 6-10 for bot deployment
4. Verify database is being used correctly

**Time**: ~1-2 hours (depending on database size)

---

### Path 3: Automated Scripts

**Use this if:**
- You're comfortable with command-line tools
- You want to automate as much as possible
- You have SSH access configured

**Steps:**
1. Set up Oracle Cloud manually (Steps 1-3 of migration guide)
2. Run `deployment/oracle/setup-oracle-vm.sh` on the VM
3. Run `deployment/oracle/transfer-database.sh` from local machine
4. Run `deployment/oracle/deploy-to-oracle.sh` from local machine

**Time**: ~45-90 minutes

---

## 📊 What Gets Migrated

### ✅ Application Code
- **Status**: No changes needed
- **Location**: Already in your repository
- **Action**: Build Docker image for ARM64

### ✅ Configuration
- **Status**: Same `.env` file
- **Changes**: Update `DB_PATH` to point to Oracle storage
- **Action**: Copy `.env` to Oracle VM

### ✅ Database (If Transferring)
- **Status**: SQLite database file
- **Location**: Azure Container App or Azure Files
- **Action**: Download and transfer to Oracle block storage
- **Size**: Typically 1-200 MB depending on history

### ✅ Docker Image
- **Status**: Needs ARM64 build
- **Current**: Built for AMD64 (Azure)
- **Action**: Rebuild for ARM64 or use Docker Hub

---

## 🔄 Migration Workflow

```
┌─────────────────────────────────────────────────────────┐
│ 1. PREPARE ORACLE CLOUD                                 │
│    - Create account                                     │
│    - Create compute instance (ARM64)                    │
│    - Create and attach block storage                    │
│    - Install Docker and tools                          │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 2. TRANSFER DATABASE (If Preserving Data)              │
│    - Locate database on Azure                          │
│    - Download database backup                          │
│    - Verify integrity                                  │
│    - Transfer to Oracle block storage                  │
│    - Verify on Oracle VM                               │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 3. DEPLOY BOT                                           │
│    - Build/pull ARM64 Docker image                     │
│    - Create .env file                                   │
│    - Create docker-compose.yml                         │
│    - Start container                                    │
│    - Verify bot is running                             │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 4. VERIFY AND MONITOR                                   │
│    - Test Discord commands                              │
│    - Verify database is being used                     │
│    - Check logs for errors                             │
│    - Monitor for 24-48 hours                          │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 5. DECOMMISSION AZURE (After Verification)            │
│    - Export final database backup                      │
│    - Delete Azure resources                            │
│    - Update documentation                              │
└─────────────────────────────────────────────────────────┘
```

---

## ⏱️ Time Estimates

| Task | Time | Notes |
|------|------|-------|
| Oracle account setup | 10-15 min | One-time |
| Compute instance creation | 5-10 min | Wait for provisioning |
| Block storage setup | 10-15 min | Format and mount |
| Docker installation | 5-10 min | Automated with script |
| Database transfer | 5-30 min | Depends on size and method |
| Bot deployment | 10-15 min | Image build/pull + start |
| Verification | 15-30 min | Testing and monitoring |
| **Total** | **1-2 hours** | For complete migration |

---

## 💰 Cost Comparison

| Resource | Azure (Current) | Oracle (Target) | Savings |
|----------|----------------|-----------------|---------|
| Compute | $15-20/mo | $0 | $15-20/mo |
| Container Registry | $5/mo | $0 (Docker Hub) | $5/mo |
| Storage | $0.06/mo | $0 | $0.06/mo |
| **Total** | **$20-25/mo** | **$0/mo** | **$20-25/mo** |
| **Annual** | **$240-300** | **$0** | **$240-300** |

---

## ⚠️ Important Considerations

### Architecture Differences

- **Azure**: x86_64 (AMD64) architecture
- **Oracle**: ARM64 (Ampere) architecture
- **Impact**: Docker images must be built for ARM64
- **Solution**: Use `docker buildx` or build on Oracle VM

### Resource Limits

- **Oracle Free Tier**: 1/8 to 1/4 OCPU, 1-2GB RAM
- **Azure**: 0.5 CPU, 1GB RAM (paid tier)
- **Impact**: Similar performance, but monitor usage
- **Solution**: Optimize if needed, Oracle provides more storage

### Database Persistence

- **Azure**: Optional Azure Files mount
- **Oracle**: Block storage volume (required for persistence)
- **Impact**: Must set up block storage before deployment
- **Solution**: Follow setup checklist carefully

### Single VM vs Serverless

- **Azure**: Container Apps (serverless, auto-scaling)
- **Oracle**: Single VM (manual management)
- **Impact**: No auto-scaling, but full control
- **Solution**: Monitor and scale manually if needed

---

## 🚨 Critical Steps

These steps are **essential** and must be done correctly:

1. ✅ **Block Storage Setup** - Without this, database will be lost
2. ✅ **Database Transfer** - If you have data to preserve
3. ✅ **ARM64 Docker Image** - Required for Oracle free tier
4. ✅ **DB_PATH Configuration** - Must point to mounted volume
5. ✅ **Volume Mount in Docker** - Must mount `/mnt/bot-data` to `/mnt/data`

---

## 📋 Quick Reference Checklist

### Before Starting
- [ ] Read this overview
- [ ] Choose your migration path
- [ ] Have Oracle Cloud account ready
- [ ] Have SSH keys ready
- [ ] Backup Azure database (if preserving data)

### Oracle Setup
- [ ] Create compute instance (ARM64)
- [ ] Create and attach block storage
- [ ] Format and mount block storage
- [ ] Install Docker and tools
- [ ] Configure firewall

### Database Transfer (If Applicable)
- [ ] Locate database on Azure
- [ ] Download database backup
- [ ] Verify database integrity
- [ ] Transfer to Oracle VM
- [ ] Copy to mounted volume
- [ ] Verify on Oracle VM

### Bot Deployment
- [ ] Build/pull ARM64 Docker image
- [ ] Create `.env` file with `DB_PATH`
- [ ] Create `docker-compose.yml`
- [ ] Start container
- [ ] Verify bot is running

### Verification
- [ ] Test Discord commands
- [ ] Verify database is being used
- [ ] Check logs for errors
- [ ] Monitor for 24-48 hours

### Cleanup
- [ ] Export final Azure database backup
- [ ] Decommission Azure resources
- [ ] Update documentation

---

## 🆘 Getting Help

### Documentation
1. **General Migration**: `ORACLE_CLOUD_MIGRATION_GUIDE.md`
2. **Database Transfer**: `DATABASE_TRANSFER_GUIDE.md`
3. **Setup Checklist**: `deployment/oracle/ORACLE_SETUP_CHECKLIST.md`

### Troubleshooting
- Check the troubleshooting sections in each guide
- Verify each step was completed correctly
- Check logs: `docker-compose logs -f`
- Test database: `sqlite3 /mnt/bot-data/db.sqlite3 "PRAGMA integrity_check;"`

### Common Issues
- **Database not found**: Check volume mount and `DB_PATH`
- **Permission denied**: Check file permissions on mounted volume
- **Bot won't start**: Check logs and environment variables
- **ARM64 issues**: Ensure Docker image supports ARM64

---

## ✅ Success Criteria

Your migration is successful when:

1. ✅ Bot is running on Oracle Cloud
2. ✅ Bot connects to Discord successfully
3. ✅ Database is being used (if transferred)
4. ✅ Historical data is accessible (if transferred)
5. ✅ New games are being tracked
6. ✅ Discord commands work correctly
7. ✅ No errors in logs
8. ✅ Database persists after container restart

---

## 🚀 Ready to Start?

1. **Choose your path** (see Migration Paths above)
2. **Follow the appropriate guides** in order
3. **Verify at each step** before proceeding
4. **Test thoroughly** before decommissioning Azure

**Recommended starting point**: **[ORACLE_CLOUD_MIGRATION_GUIDE.md](ORACLE_CLOUD_MIGRATION_GUIDE.md)**

Good luck with your migration! 🎉

