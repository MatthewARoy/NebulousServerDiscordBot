#!/bin/bash
# Oracle Cloud Infrastructure Configuration
# Source this file before running deployment scripts:
#   source deployment/oracle/oci-config.sh

# VM Connection Details (from docs/ORACLE_CONNECT.md)
export OCI_VM_HOST="REDACTED_VM_IP"
export OCI_VM_USER="opc"
export OCI_SSH_KEY="${OCI_SSH_KEY:-$HOME/.ssh/id_ed25519}"

# Deployment Configuration
export CONTAINER_NAME="${CONTAINER_NAME:-nebulous-discord-bot}"
export REMOTE_DIR="${REMOTE_DIR:-~/NebulousServerDiscordBot}"
export REMOTE_BACKUP_DIR="${REMOTE_BACKUP_DIR:-/home/opc/nebulous-data/backups}"
export BACKUP_KEEP="${BACKUP_KEEP:-2}"  # Keep last 2 deployment backups

# Paths on Oracle VM (from docs/ORACLE_CONNECT.md)
export OCI_REPO_PATH="/home/opc/NebulousServerDiscordBot"
export OCI_COMPOSE_FILE="/home/opc/NebulousServerDiscordBot/docker-compose.yml"
export OCI_ENV_FILE="/home/opc/nebulous-bot/.env"
export OCI_DATA_PATH="/home/opc/nebulous-data"
export OCI_DB_PATH="/home/opc/nebulous-data/db.sqlite3"
export OCI_LOGS_DIR="/home/opc/nebulous-bot/logs"

echo "✅ Oracle Cloud configuration loaded:"
echo "   VM Host: $OCI_VM_HOST"
echo "   VM User: $OCI_VM_USER"
echo "   SSH Key: $OCI_SSH_KEY"
echo "   Remote Dir: $REMOTE_DIR"
echo "   DB Path: $OCI_DB_PATH"
