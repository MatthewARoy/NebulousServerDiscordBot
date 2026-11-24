# Oracle Cloud Deployment

This directory contains scripts and configurations for deploying the Nebulous Discord Bot to Oracle Cloud Infrastructure (OCI) Free Tier.

## 📋 Prerequisites

1. **Oracle Cloud Account** with Always Free tier access
2. **Compute Instance** (VM.Standard.A1.Flex) running Ubuntu 22.04 ARM64
3. **SSH Access** to your VM
4. **Block Storage Volume** (optional, for database persistence)

## 🚀 Quick Start

### Step 1: Set Up VM

SSH into your Oracle Cloud VM and run:

```bash
# Download and run setup script
curl -fsSL https://raw.githubusercontent.com/your-repo/NebulousServerDiscordBot/main/deployment/oracle/setup-oracle-vm.sh -o setup-oracle-vm.sh
chmod +x setup-oracle-vm.sh
./setup-oracle-vm.sh

# Log out and back in for Docker group changes
exit
# SSH back in
```

Or copy the script manually:

```bash
# On your local machine
scp deployment/oracle/setup-oracle-vm.sh ubuntu@<your-vm-ip>:~/
ssh ubuntu@<your-vm-ip>
chmod +x setup-oracle-vm.sh
./setup-oracle-vm.sh
```

### Step 2: Configure Environment

On the VM, create `.env` file:

```bash
cd ~/nebulous-bot
nano .env
```

Add your configuration (see `ORACLE_CLOUD_MIGRATION_GUIDE.md` for details).

### Step 3: Deploy

The first deploy on a fresh VM is manual (below). After that, update with
`deploy-to-oracle.sh` (see [Updating](#-updating)): it changes an existing
deployment and does not bootstrap one.

**Manual first deployment (on VM)**

```bash
# On the VM
cd ~/nebulous-bot

# Copy docker-compose.yml
cp deployment/oracle/docker-compose.oracle.yml docker-compose.yml

# Edit docker-compose.yml to set your Docker Hub username
nano docker-compose.yml

# Pull image (if using Docker Hub)
docker-compose pull

# Or build locally
docker-compose build

# Start
docker-compose up -d

# Check logs
docker-compose logs -f
```

## 📁 Files

- **`setup-oracle-vm.sh`**: Initial VM setup script (installs Docker, configures firewall)
- **`docker-compose.oracle.yml`**: Docker Compose configuration for OCI
- **`deploy-to-oracle.sh`**: image-based deploy, config re-apply and rollback (dry run by default)
- **`remote_deploy.py`**: the steps it runs on the VM (stdlib only, Python 3.9)
- **`README.md`**: This file

## 🔧 Configuration

### Docker Image

You have two options for the Docker image:

1. **Docker Hub** (recommended): Build and push ARM64 image to Docker Hub
2. **Build on VM**: Clone repo and build directly on the ARM64 VM

### Database Persistence

If you've attached block storage:

1. Format and mount the volume to `/mnt/bot-data`
2. Set `DB_PATH=/mnt/bot-data/db.sqlite3` in `.env`
3. The docker-compose.yml already mounts this volume

### Resource Limits

The docker-compose.yml includes resource limits suitable for free tier:
- CPU: 0.25-1.0 cores
- Memory: 512MB-1.5GB

Adjust based on your VM size (1/8 OCPU = 0.125, 1/4 OCPU = 0.25, etc.)

## 🔍 Monitoring

### View Logs

```bash
# On VM
cd ~/nebulous-bot
docker-compose logs -f

# Or from local machine
ssh ubuntu@<vm-ip> "cd ~/nebulous-bot && docker-compose logs -f"
```

### Check Status

```bash
docker-compose ps
docker stats
```

### Health Check

```bash
curl http://localhost:8000/health/
```

## 🔄 Updating

Production runs a verified CI image pinned by ID in
`/home/opc/NebulousServerDiscordBot/docker-compose.yml` and started with
`--no-build`. Never rsync source or build on the VM: the 1/8-OCPU, ~500 MiB host
can't afford it. `deploy-to-oracle.sh` runs the 2.10/2.11 procedure from Git
Bash on Windows, macOS or Linux. It **dry-runs by default**, which prints the
exact compose diff and the names of the `.env` keys it would set.

```bash
export OCI_VM_HOST=<vm address from ORACLE_CONNECT.md>   # OCI_SSH_KEY defaults to ~/.ssh/id_ed25519

# Re-apply config to the running image (port binding, DJANGO_SECRET_KEY):
./deployment/oracle/deploy-to-oracle.sh            # dry run
./deployment/oracle/deploy-to-oracle.sh --live

# Ship a new image: CI's "nebulous-bot-image" artifact for a commit on origin/main.
# Run the isolated acceptance in docs/releases/ first.
gh run download <run-id> -n nebulous-bot-image -D /tmp/nebulous-image
./deployment/oracle/deploy-to-oracle.sh --image-dir /tmp/nebulous-image          # dry run
./deployment/oracle/deploy-to-oracle.sh --image-dir /tmp/nebulous-image --live

# Undo a deploy (restores that release's .env + compose snapshot, then recreates):
./deployment/oracle/deploy-to-oracle.sh --rollback /home/opc/bot-release-<stamp>
```

A live run first writes `/home/opc/bot-release-<UTC stamp>/` containing the
`.env` and compose snapshot, a `nebulous-bot:rollback-<stamp>` image tag, and an
online SQLite backup proven by `integrity_check` and a restored copy. It then
pins the image, binds 8000 to `127.0.0.1`, keeps `DISCORD_MESSAGE_CONTENT=false`,
generates `DJANGO_SECRET_KEY` only if it is missing, and recreates the
container. `remote_deploy.py status` then checks the result. Hard failures
(wrong image, restarts, unhealthy, port not on loopback, no real secret) roll
back automatically. Soft ones (gateway or monitoring log lines, ERROR lines, DB
checks) leave production as deployed and print the rollback command. Recreating
the container drops in-memory `/nextgame` waiters.

On Windows, the repo's `.gitattributes` keeps both deploy files LF-only, and the
script refuses to run from a CRLF checkout.

### Discord command migration rollout (completed September 30, 2026)

Production 2.10.0 runs the verified immutable Linux image with all privileged
intents off and 19 global commands. See the
[execution record](../../docs/releases/2.10.0-rollout-result.md) and
[current release procedure](../../docs/releases/2.10.0-rollout-plan.md).

For future runtime updates, validate a separate test application, preserve a
tested intent-off image and consistent database backup, then deploy the exact
accepted artifact. Keep `DISCORD_MESSAGE_CONTENT=false` explicit and all Portal
privileged intents off. Recreate the container when its environment changes;
a restart alone does not reload it. Preserve the real production mounts/ports.

Command sync is a separate owner action only when required by an authorized
command-schema change. Never add synchronization to startup, reconnect or the
deployment script. Verify global commands without test-guild copies masking them.

The production host directory is a deployment context, not a Git checkout.
Compose pins the verified image and uses `--no-build`; generic source-build/pull
examples elsewhere on this page are not the immutable-artifact release procedure.
Documentation-only updates do not require rebuilding or restarting the bot.

The deploy script retains the running image and uses SQLite's online backup API
with an integrity check. An older intent-dependent image is not a working
post-cutoff rollback: use a tested intent-off image or repair forward. Never
restore the database merely for an application issue. Announcements require
separate approval of exact copy, channels and timing and are never automatic.

## 🐛 Troubleshooting

See `ORACLE_CLOUD_MIGRATION_GUIDE.md` for detailed troubleshooting steps.

Common issues:
- **Docker permission denied**: Log out and back in after adding user to docker group
- **Port already in use**: Check with `sudo netstat -tulpn | grep 8000`
- **Out of memory**: Reduce resource limits in docker-compose.yml
- **Database errors**: Check `/mnt/bot-data` permissions

## 📚 Additional Resources

- **Full Migration Guide**: `ORACLE_CLOUD_MIGRATION_GUIDE.md`
- **OCI Documentation**: https://docs.oracle.com/en-us/iaas/Content/home.htm
- **Docker Compose Docs**: https://docs.docker.com/compose/

