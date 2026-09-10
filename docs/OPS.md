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

## The second trigger: PCP + mlocate nightly cluster (2026-09-10)

Same class as `dnf-makecache`, different unit, and no OOM kill this time —
just sustained swap thrash. Reported as "the bot is taking a long time to
update server lists".

Four timers fire in a ten-minute window every night, all in GMT:

| Time (GMT) | Unit |
|---|---|
| 00:00 | `logrotate.timer`, `mlocate-updatedb.timer` |
| 00:08 | `pmie_daily.timer` |
| 00:10 | `pmlogger_daily.timer` |

Plus the permanently resident Performance Co-Pilot stack (`pmcd`, `pmie`,
`pmie_farm`, `pmlogger`, `pmlogger_farm`, `pmdaproc`) and four
`*_check.timer`s re-firing every 30 minutes.

Measured on 2026-09-10 inside the window: `pmlogger_daily.service` ran
**33m32s**, consumed **7m59s CPU**, and exited 1. `vmstat` showed
`si`/`so` at 1200-3500 KB/s sustained, `wa` 35-59%, steal 30-51%, 10 MiB
free. The bot container itself was 27 MiB RSS at 10% CPU throughout — it
is the victim, not the cause. Since-boot averages over 132 days are
`id 94, st 3`, so this is strictly episodic.

What it looks like from the bot side (all timestamps PST, window is 17:00):

```
gateway Can't keep up, shard ID None websocket is 49.7s behind
server_monitor Error updating tracked message ...: Server disconnected
steam_api Server rules queries timed out, using basic server data
http We are being rate limited. PATCH .../messages/... responded with 429
```

Bucket them by hour to confirm it's this and not a chronic problem:

```bash
docker logs --since 96h nebulous-discord-bot 2>&1 |
  grep -E "Can't keep up|behind|Server disconnected|Broken pipe|rules queries timed out" |
  grep -oE "[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}" | sort | uniq -c
```

On 2026-09-09 that gave 1 / 7 / 12 hits on three consecutive days, every
one of them in the 17:00 PST hour, and rising.

### The fix

```bash
sudo systemctl disable --now pmlogger_daily.timer pmie_daily.timer mlocate-updatedb.timer
```

**Status: proposed, not yet applied.** Verify with `systemctl is-enabled`
on each (should say `disabled`), then re-run the hourly bucket after a
night and confirm the 17:00 cluster is gone.

Deliberately *not* done: disabling the resident PCP collectors as well.
They cost ~40-60 MiB, but killing them removes the instrumentation needed
to prove the fix worked. Revisit once a couple of clean nights are on
record — and only if PCP is genuinely unused here.

Note this incident is a correlation, not a smoking gun: unlike
`dnf-makecache` there is no OOM line naming the culprit. If the 17:00
cluster survives disabling these three, the timers were not the driver and
the answer is the shape bump below.

### Fallout in the data

The stall also corrupted statistics until 2.9.3. An expired A2S rules
sweep rebuilt every server with `rules=None`, whose `status` defaults to
`lobby`, which the game-session state machine reads as "the game ended" —
so one real game became two rows, both long enough to pass the 5-minute
validity gate. 2.9.3 added `status_known` to gate that, but the rows
already written are still there. A cleanup pass wants to look for pairs on
the same `server_name` where one session ends and the next starts within
about two minutes, on stall nights.

## When this isn't enough

If wedges return despite all of the above and the journal shows OOM kills
from new sources you can't easily disable, the next move is the shape bump
to A1.Flex (still Always Free, ARM64, 1 OCPU / 6 GB RAM). That's a
stop → edit-shape → start, plus rebuilding the Docker image for
`linux/arm64`. See `deployment/oracle/README.md`.
