# Operations notes

Production runs on a single OCI Always Free E2.1.Micro VM (1 OCPU, ~503 MiB
usable RAM, 3.5 GiB swap). The shape is generous enough at idle but a single
`!graph` invocation plus a Discord rate-limit retry burst can push the working
set into swap, where reading swap-backed pages stalls every other process —
including sshd. Below are the host-side mitigations that keep the VM
responsive on this shape without spending money. Apply them once after
provisioning.

## Why this matters

When the bot's RSS grows past free RAM, the kernel pages cold memory to swap.
On the small SSD-backed swapfile, paging in is slow enough that the system
spends most of its time servicing page faults. `sshd`'s pages get evicted too,
so even logging in to recover stops working. From the outside it looks like
"the VM is dead"; from a console it looks like everything is in `D` (disk
wait) state. The fix is a defense in depth that (a) keeps the working set
small, (b) caps the container so it gets killed cleanly before swap thrash
can spiral, and (c) installs an OOM killer that fires *before* the kernel's
slow path.

## 1. Lower swappiness

Default `vm.swappiness=60` is too aggressive for this shape. Drop it so the
kernel only reaches for swap when it has no choice.

```bash
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-low-swap.conf
sudo sysctl --system
sysctl vm.swappiness   # confirm: 10
```

## 2. Install earlyoom

`earlyoom` watches free memory and free swap, kills the heaviest process
when either drops below a threshold, and exits in milliseconds — far faster
than the kernel's OOM killer, which is what wedges the system.

```bash
sudo dnf install -y earlyoom
sudo systemctl edit earlyoom    # opens an override file
```

In the editor, paste:

```
[Service]
ExecStart=
ExecStart=/usr/bin/earlyoom -m 10 -s 50 --avoid '^(sshd|systemd|systemd-.*)$' --prefer '^(python|gunicorn)$'
```

Then:

```bash
sudo systemctl enable --now earlyoom
sudo systemctl status earlyoom   # should be active (running)
```

Thresholds:

- `-m 10`: kill when free RAM drops below 10 %.
- `-s 50`: also kill when free swap drops below 50 %.
- `--avoid`: never kill ssh, systemd.
- `--prefer`: target the bot's processes first when over the threshold.

## 3. Cap the container memory

Already done in `deployment/oracle/docker-compose.oracle.yml` via `mem_limit:
350m`. After the next deploy, verify with:

```bash
docker stats --no-stream nebulous-discord-bot
# MEM USAGE / LIMIT should show .../350MiB
```

If the bot tries to grow past 350 MiB the cgroup OOM fires, the container
dies, and `restart: unless-stopped` brings it back. The host stays
responsive throughout.

## 4. External health watchdog

A minute-cron that hits the local health endpoint and restarts the compose
stack on repeated failure. Backstop for the case where the in-container
healthcheck-driven restart isn't enough.

Save this script as `/home/opc/bin/bot-watchdog.sh`:

```bash
#!/bin/bash
# Restart the bot if /health/ has failed 2 minutes in a row.
set -u
STATE_FILE=/tmp/bot-watchdog.state
COMPOSE_DIR=/home/opc/NebulousServerDiscordBot

if curl -sf -m 5 http://localhost:8000/health/ > /dev/null; then
    : > "$STATE_FILE"
    exit 0
fi

# Failure: increment counter
fails=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
fails=$((fails + 1))
echo "$fails" > "$STATE_FILE"

if [ "$fails" -ge 2 ]; then
    logger -t bot-watchdog "health endpoint failed ${fails} consecutive checks; restarting"
    cd "$COMPOSE_DIR" && /usr/bin/docker compose restart bot
    : > "$STATE_FILE"
fi
```

Install it:

```bash
mkdir -p /home/opc/bin
chmod +x /home/opc/bin/bot-watchdog.sh

# Add to crontab
( crontab -l 2>/dev/null; echo "* * * * * /home/opc/bin/bot-watchdog.sh" ) | crontab -
crontab -l   # confirm the line is there
```

`logger` writes to the system journal, so any restarts will show up in
`journalctl -t bot-watchdog`.

## Verification after applying everything

```bash
# Memory and swap headroom
free -h

# earlyoom alive
systemctl is-active earlyoom

# Container limit honoured
docker stats --no-stream | grep nebulous-discord-bot

# Watchdog runs (wait one minute, then)
journalctl -t bot-watchdog -n 5

# Confirm the bot is healthy
curl -s http://localhost:8000/health/
```

## When this isn't enough

If you keep seeing wedges or restarts despite all of the above, the next move
is the shape bump to A1.Flex (still Always Free, ARM64, 1 OCPU / 6 GB RAM).
That requires a stop → edit-shape → start, plus rebuilding the Docker image
for `linux/arm64` if the current image is x86_64. See
`deployment/oracle/README.md`.
