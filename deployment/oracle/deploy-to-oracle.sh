#!/usr/bin/env bash
# Deploy the bot to the Oracle VM the way 2.10/2.11 were released: a verified
# CI image (or the image already running), pinned in the live compose file and
# started with --no-build. It never rsyncs source and never builds on the VM.
#
#   OCI_VM_HOST=<ip> deployment/oracle/deploy-to-oracle.sh                  # dry run (default)
#   OCI_VM_HOST=<ip> deployment/oracle/deploy-to-oracle.sh --live           # re-apply config, same image
#   OCI_VM_HOST=<ip> deployment/oracle/deploy-to-oracle.sh --live --image-dir DIR
#   OCI_VM_HOST=<ip> deployment/oracle/deploy-to-oracle.sh --rollback /home/opc/bot-release-<stamp>
#
# DIR holds CI's "nebulous-bot-image" artifact for a commit on origin/main:
#   gh run download <run-id> -n nebulous-bot-image -D DIR
#
# Runs from Git Bash on Windows, macOS or Linux. It needs bash, ssh, scp, git and
# sha256sum or shasum. Each remote step runs deployment/oracle/remote_deploy.py
# on the VM. See docs/releases/ for the acceptance testing a new image needs first.
set -euo pipefail
# Git Bash: never rewrite /home/opc/... arguments into Windows paths.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_PY="$SCRIPT_DIR/remote_deploy.py"
VM_HOST="${OCI_VM_HOST:-}"
VM_USER="${OCI_VM_USER:-opc}"
SSH_KEY="${OCI_SSH_KEY:-$HOME/.ssh/id_ed25519}"
REMOTE_DIR="${REMOTE_DIR:-/home/opc/NebulousServerDiscordBot}"
DATA_DIR="${DATA_DIR:-/home/opc/nebulous-data}"
CONTAINER_NAME="${CONTAINER_NAME:-nebulous-discord-bot}"
RELEASE_ROOT="${RELEASE_ROOT:-/home/opc}"

MODE=dry-run
IMAGE_DIR=""
ROLLBACK_DIR=""
ASSUME_YES=n
while [ $# -gt 0 ]; do
    case "$1" in
        --live) MODE=live ;;
        --image-dir) IMAGE_DIR="${2:?--image-dir needs a directory}"; shift ;;
        --rollback) MODE=rollback; ROLLBACK_DIR="${2:?--rollback needs a release directory}"; shift ;;
        --yes) ASSUME_YES=y ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "Unknown argument: $1 (see --help)" >&2; exit 64 ;;
    esac
    shift
done

die() { echo "❌ $*" >&2; exit 1; }
confirm() {
    [ "$ASSUME_YES" = y ] && return 0
    local reply
    read -r -p "$1 [y/N] " reply
    [ "$reply" = y ] || [ "$reply" = Y ] || die "aborted; nothing changed by this step"
}

# A CRLF checkout breaks the shebang and the program piped to the VM.
if grep -q $'\r' "$0"; then die "$0 has CRLF line endings; re-checkout with LF (see .gitattributes)"; fi
[ -n "$VM_HOST" ] || die "OCI_VM_HOST is not set (the VM address lives in ORACLE_CONNECT.md)"
[ -f "$REMOTE_PY" ] || die "missing $REMOTE_PY"
[ -f "$SSH_KEY" ] || die "SSH key not found: $SSH_KEY (set OCI_SSH_KEY)"

SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30)
TARGET="$VM_USER@$VM_HOST"
COMMON=(--repo "$REMOTE_DIR" --data "$DATA_DIR" --container "$CONTAINER_NAME" --release-root "$RELEASE_ROOT")

# remote <phase> [args...]: run one remote_deploy.py phase on the VM.
remote() {
    local cmd="python3 -" arg
    for arg in "$@" "${COMMON[@]}"; do cmd="$cmd $(printf '%q' "$arg")"; done
    tr -d '\r' < "$REMOTE_PY" | ssh "${SSH_OPTS[@]}" "$TARGET" "$cmd"
}

if [ "$MODE" = rollback ]; then
    confirm "Restore $ROLLBACK_DIR on the VM and recreate the production container?"
    remote rollback --release "$ROLLBACK_DIR"
    exit $?
fi

if [ -n "$IMAGE_DIR" ]; then
    for f in nebulous-bot.tar.gz SHA256SUMS source-revision.txt; do
        [ -f "$IMAGE_DIR/$f" ] || die "$IMAGE_DIR/$f is missing (download the CI artifact)"
    done
    if command -v sha256sum >/dev/null 2>&1; then
        (cd "$IMAGE_DIR" && sha256sum -c --quiet SHA256SUMS) || die "checksum mismatch in $IMAGE_DIR"
    else
        (cd "$IMAGE_DIR" && shasum -a 256 -c --quiet SHA256SUMS) || die "checksum mismatch in $IMAGE_DIR"
    fi
    REVISION="$(tr -d '\r\n ' < "$IMAGE_DIR/source-revision.txt")"
    git -C "$SCRIPT_DIR" fetch -q origin main || die "git fetch failed"
    git -C "$SCRIPT_DIR" merge-base --is-ancestor "$REVISION" origin/main \
        || die "image revision $REVISION is not on origin/main"
    echo "✅ Image archive checksum ok; revision $REVISION is on origin/main"
fi

echo "== Preflight (read-only) on $CONTAINER_NAME"
if [ -n "$IMAGE_DIR" ]; then remote preflight --new-image; else remote preflight; fi

if [ "$MODE" = dry-run ]; then
    echo "Dry run complete; nothing changed. Re-run with --live to deploy."
    exit 0
fi

confirm "Recreate the production container now? The bot is offline for 1-2 minutes and in-memory /nextgame waiters are lost."

STAMP="$(date -u +%Y%m%d-%H%M%S)"
RELEASE="$RELEASE_ROOT/bot-release-$STAMP"
echo "== Backup into $RELEASE"
remote backup --release "$RELEASE" --stamp "$STAMP"

IMAGE_ARGS=()
if [ -n "$IMAGE_DIR" ]; then
    echo "== Upload and load the image archive"
    scp "${SSH_OPTS[@]}" "$IMAGE_DIR/nebulous-bot.tar.gz" "$IMAGE_DIR/SHA256SUMS" \
        "$IMAGE_DIR/source-revision.txt" "$TARGET:$RELEASE/"
    remote load --release "$RELEASE"
    IMAGE_ARGS=(--accepted)
fi

echo "== Apply"
if ! remote apply --release "$RELEASE" ${IMAGE_ARGS[@]+"${IMAGE_ARGS[@]}"}; then
    echo "Apply failed; restoring the backup." >&2
    remote rollback --release "$RELEASE" || die "ROLLBACK FAILED: run $0 --rollback $RELEASE"
    exit 2
fi

echo "== Verify"
set +e
remote status --release "$RELEASE" ${IMAGE_ARGS[@]+"${IMAGE_ARGS[@]}"}
rc=$?
set -e
case $rc in
    0) echo "✅ Deployed and verified. Release record: $RELEASE" ;;
    2) echo "Hard failure; restoring the backup." >&2
       remote rollback --release "$RELEASE" || die "ROLLBACK FAILED: run $0 --rollback $RELEASE"
       exit 2 ;;
    3) echo "⚠️  Soft failure: production left as deployed. To undo: $0 --rollback $RELEASE" >&2
       exit 3 ;;
    *) echo "Status check could not run (exit $rc). To undo: $0 --rollback $RELEASE" >&2
       exit "$rc" ;;
esac
