# Operations notes

Production runs on a single OCI Always Free E2.1.Micro VM (1 OCPU, ~503 MiB
usable RAM, 3.5 GiB swap). The shape is small but adequate — the bot ran for
8 weeks unattended without incident before a single trigger took it down
five times in one day. This document is the post-mortem and the runbook.

## The actual trigger: `dnf-makecache`

`dnf-makecache.service` is a systemd timer that prebuilds Oracle Linux's dnf
metadata cache so subsequent `dnf install` calls are fast. Its working set
is large — on this shape, dnf wants ~295 MiB resident for a cache rebuild.
On a 503 MiB box, that plus the running bot plus the OS exceeds total RAM
under any kind of burst load. When that happens, the kernel OOM-kills dnf,
but on the way down sshd's pages get evicted to the small SSD-backed swap
and the host becomes unreachable. Soft reboot does **not** clear the
condition; only an OCI Console Stop → Start does (cold boot wipes swap).

Smoking-gun journal entries (recognise these):

```
kernel: dockerd invoked oom-killer ...
kernel: oom-kill: ... task=dnf, pid=11367
kernel: Out of memory: Killed process 11367 (dnf) ...
systemd: dnf-makecache.service: A process of this unit has been killed by the OOM killer.
systemd: dnf-makecache.service: Failed with result 'oom-kill'.
```

## The fix (already applied)

```bash
sudo systemctl disable --now dnf-makecache.timer
sudo systemctl mask dnf-makecache.service
```

The timer no longer fires; the service is symlinked to `/dev/null` and
cannot be reactivated. Manual `dnf install/update` still works — the cache
just rebuilds on demand instead of being preemptively prepared. On a bot VM
that gets touched once a quarter, that's a non-issue.

If you ever need to revert: `sudo systemctl unmask dnf-makecache.service &&
sudo systemctl enable --now dnf-makecache.timer`. Don't, unless the failure
mode is gone for unrelated reasons.

## Companion mitigations also applied

These don't address the trigger directly but reduce the chance that a
*different* OOM event ever produces the same SSH-wedge pattern.

```bash
# Lower kernel's eagerness to use swap (default 60 → 10).
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-low-swap.conf
sudo sysctl --system
```

Plus a code change: `nebulous_bot/graph_generator.py` lazy-imports
matplotlib + numpy on first `!graph` invocation rather than at bot startup,
which keeps idle RSS ~80–120 MiB lighter.

## When the bot is reported "down"

The first hypothesis should still be SSH-wedge from memory pressure. Triage:

```bash
# Is the VM reachable at all?
nc -zv 64.181.240.159 22         # tcp/22
nc -zv 64.181.240.159 8000       # bot port

# If 22 is reachable but ssh hangs at "Connection timed out during banner
# exchange", the VM is wedged. Recovery is OCI Console → Stop → Start.
# Soft Reboot does not clear it.
```

Once SSH responds, do a focused read-only audit before applying any new
mitigations. The cause is usually the journal:

```bash
sudo journalctl --since '24 hours ago' --no-pager | grep -iE 'oom|killed process|out of memory'
```

The `task=...` field on the OOM line names the killer. If it's `dnf`,
verify dnf-makecache hasn't crept back in (`systemctl is-enabled
dnf-makecache.timer` should say `disabled`, the service should be
`masked`). If it's something else, deal with that something else — don't
just add more mitigations.

## Optional defense-in-depth (not currently installed)

If you ever want belt-and-suspenders against a future unknown OOM trigger,
the most useful next step is `earlyoom` — a userspace OOM killer that fires
faster than the kernel's slow path (which is what wedges sshd). It's in
EPEL, not the default Oracle Linux 9 repos:

```bash
sudo dnf install -y oracle-epel-release-el9
sudo dnf install -y earlyoom
sudo mkdir -p /etc/systemd/system/earlyoom.service.d
sudo tee /etc/systemd/system/earlyoom.service.d/override.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/earlyoom -m 10 -s 50 --avoid '^(sshd|systemd|systemd-.*)$' --prefer '^(python|gunicorn)$'
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now earlyoom
```

Skipping this for now since the actual trigger is removed. Add only if a
new unrelated OOM vector shows up.

## Verification after applying everything

```bash
# Trigger removed
systemctl is-enabled dnf-makecache.timer    # disabled
systemctl is-active dnf-makecache.timer     # inactive

# Companion mitigations
sysctl vm.swappiness                        # 10

# Bot healthy
curl -s http://localhost:8000/health/

# Idle RSS sanity-check
docker stats --no-stream nebulous-discord-bot
```

## When this isn't enough

If wedges return despite all of the above and the journal shows OOM kills
from new sources you can't easily disable, the next move is the shape bump
to A1.Flex (still Always Free, ARM64, 1 OCPU / 6 GB RAM). That's a
stop → edit-shape → start, plus rebuilding the Docker image for
`linux/arm64`. See `deployment/oracle/README.md`.
