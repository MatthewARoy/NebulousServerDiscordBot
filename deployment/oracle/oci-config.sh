#!/bin/bash
# Oracle Cloud Infrastructure Configuration
#
# Copy this file to a local-only override (e.g. `oci-config.local.sh`) and
# fill in the values for your VM, then source it before running the deploy
# scripts:
#
#   source deployment/oracle/oci-config.local.sh
#   ./deployment/oracle/deploy-to-oracle.sh
#
# Or set the same environment variables in your shell.

# --- VM connection details (REQUIRED — set these) ---
export OCI_VM_HOST="${OCI_VM_HOST:?Set OCI_VM_HOST to your Oracle VM's public IP}"
export OCI_VM_USER="${OCI_VM_USER:-opc}"
export OCI_SSH_KEY="${OCI_SSH_KEY:-$HOME/.ssh/id_ed25519}"

# --- Deployment configuration ---
export CONTAINER_NAME="${CONTAINER_NAME:-nebulous-discord-bot}"
export REMOTE_DIR="${REMOTE_DIR:-~/NebulousServerDiscordBot}"
export REMOTE_BACKUP_DIR="${REMOTE_BACKUP_DIR:-/home/opc/nebulous-data/backups}"
export BACKUP_KEEP="${BACKUP_KEEP:-2}"

# --- Paths on the Oracle VM (defaults match the OCI Always Free `opc` user) ---
export OCI_REPO_PATH="${OCI_REPO_PATH:-/home/opc/NebulousServerDiscordBot}"
export OCI_COMPOSE_FILE="${OCI_COMPOSE_FILE:-/home/opc/NebulousServerDiscordBot/docker-compose.yml}"
export OCI_ENV_FILE="${OCI_ENV_FILE:-/home/opc/nebulous-bot/.env}"
export OCI_DATA_PATH="${OCI_DATA_PATH:-/home/opc/nebulous-data}"
export OCI_DB_PATH="${OCI_DB_PATH:-/home/opc/nebulous-data/db.sqlite3}"
export OCI_LOGS_DIR="${OCI_LOGS_DIR:-/home/opc/nebulous-bot/logs}"

echo "✅ Oracle Cloud configuration loaded:"
echo "   VM Host: $OCI_VM_HOST"
echo "   VM User: $OCI_VM_USER"
echo "   SSH Key: $OCI_SSH_KEY"
echo "   Remote Dir: $REMOTE_DIR"
echo "   DB Path: $OCI_DB_PATH"
