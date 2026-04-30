# Oracle Cloud Migration - Quick Start

**Get started migrating from Azure to Oracle Cloud in 5 minutes**

---

## 🎯 What You Need

1. **Oracle Cloud Account** - [Sign up free](https://www.oracle.com/cloud/free/)
2. **SSH Key Pair** - `ssh-keygen -t rsa -b 4096`
3. **Azure Database Backup** (if preserving data) - See database transfer guide

---

## 📚 Documentation Structure

```
📁 Migration Documentation
├── 📘 MIGRATION_COMPLETE_OVERVIEW.md      ← Start here! Overview of everything
├── 📗 ORACLE_CLOUD_MIGRATION_GUIDE.md     ← Complete step-by-step guide
├── 📙 DATABASE_TRANSFER_GUIDE.md           ← Database transfer instructions
├── 📕 MIGRATION_SUMMARY.md                 ← Quick reference
└── 📂 deployment/oracle/
    ├── ORACLE_SETUP_CHECKLIST.md          ← Setup checklist
    ├── setup-oracle-vm.sh                 ← Automated setup
    ├── deploy-to-oracle.sh                ← Automated deployment
    ├── transfer-database.sh              ← Automated database transfer
    └── README.md                          ← Script documentation
```

---

## 🚀 Quick Start (3 Steps)

### Step 1: Read the Overview
👉 **[MIGRATION_COMPLETE_OVERVIEW.md](MIGRATION_COMPLETE_OVERVIEW.md)**

This gives you the big picture and helps you choose your migration path.

### Step 2: Set Up Oracle Cloud
👉 **[deployment/oracle/ORACLE_SETUP_CHECKLIST.md](deployment/oracle/ORACLE_SETUP_CHECKLIST.md)**

Follow the checklist to set up your Oracle Cloud infrastructure.

### Step 3: Transfer & Deploy

**If you have database data to preserve:**
1. Follow **[DATABASE_TRANSFER_GUIDE.md](DATABASE_TRANSFER_GUIDE.md)**
2. Then follow **[ORACLE_CLOUD_MIGRATION_GUIDE.md](ORACLE_CLOUD_MIGRATION_GUIDE.md)** Steps 6-10

**If starting fresh:**
- Follow **[ORACLE_CLOUD_MIGRATION_GUIDE.md](ORACLE_CLOUD_MIGRATION_GUIDE.md)** Steps 1-10

---

## ⚡ Automated Scripts

Want to automate? Use these scripts:

```bash
# 1. Set up VM (run on Oracle VM)
./deployment/oracle/setup-oracle-vm.sh

# 2. Transfer database (run from local machine)
export OCI_VM_HOST=your-vm-ip
./deployment/oracle/transfer-database.sh

# 3. Deploy bot (run from local machine)
./deployment/oracle/deploy-to-oracle.sh
```

---

## 🎯 Choose Your Path

### Path A: I have game data to preserve
1. Read: `MIGRATION_COMPLETE_OVERVIEW.md`
2. Setup: `deployment/oracle/ORACLE_SETUP_CHECKLIST.md`
3. Transfer: `DATABASE_TRANSFER_GUIDE.md`
4. Deploy: `ORACLE_CLOUD_MIGRATION_GUIDE.md` (Steps 6-10)

### Path B: Starting fresh (no data to preserve)
1. Read: `MIGRATION_COMPLETE_OVERVIEW.md`
2. Follow: `ORACLE_CLOUD_MIGRATION_GUIDE.md` (all steps)

### Path C: I want automation
1. Setup Oracle Cloud manually (compute + storage)
2. Run: `setup-oracle-vm.sh` on VM
3. Run: `transfer-database.sh` (if needed)
4. Run: `deploy-to-oracle.sh`

---

## ⚠️ Critical Points

1. **Block Storage is REQUIRED** - Without it, database will be lost
2. **ARM64 Architecture** - Docker images must support ARM64
3. **DB_PATH Configuration** - Must point to `/mnt/bot-data/db.sqlite3`
4. **Volume Mount** - Docker must mount `/mnt/bot-data` to `/mnt/data`

---

## 💰 Cost Savings

- **Current (Azure)**: ~$20-25/month
- **Oracle Free Tier**: $0/month
- **Annual Savings**: ~$240-300/year

---

## 🆘 Need Help?

1. **Overview**: `MIGRATION_COMPLETE_OVERVIEW.md`
2. **Troubleshooting**: Check troubleshooting sections in each guide
3. **Setup Issues**: `deployment/oracle/ORACLE_SETUP_CHECKLIST.md`
4. **Database Issues**: `DATABASE_TRANSFER_GUIDE.md`

---

## ✅ Success Checklist

- [ ] Oracle Cloud account created
- [ ] Compute instance running (ARM64)
- [ ] Block storage created and mounted
- [ ] Database transferred (if applicable)
- [ ] Bot deployed and running
- [ ] Discord commands working
- [ ] Database persisting after restart
- [ ] Monitoring for 24-48 hours

---

**Ready?** Start with **[MIGRATION_COMPLETE_OVERVIEW.md](MIGRATION_COMPLETE_OVERVIEW.md)**! 🚀

