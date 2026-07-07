---
name: verify
description: Verify a change to the Nebulous Discord bot — lint, tests, Django checks, and (when commands/monitoring changed) an import smoke test. Run before committing any nontrivial change.
---

# Verifying changes in this repo

The bot runs unattended in production on a tiny VM, so the bar is: every
change passes this loop before it's committed. All commands run from the repo
root using the project venv (`.venv`, Python 3.11 — create with
`py -3.11 -m venv .venv` + `pip install -r requirements.txt pytest ruff`
if missing).

On Windows the venv python is `.venv/Scripts/python`; on Linux/macOS it's
`.venv/bin/python`. Substitute accordingly.

## The loop (run all, in order)

```
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m pytest -q
```

**Never pipe pytest through `tail`/`grep` inside a `&&` chain that gates a
commit** — the pipe replaces pytest's exit code with the filter's, so a
collection error can slip straight into a commit (this happened once).
Run pytest bare; read the last line yourself.

Then the Django system check (needs stub env vars — tests set these via
`nebulous_bot/tests/conftest.py`, but `manage.py` does not):

PowerShell:
```
$env:DISCORD_TOKEN='x'; $env:APPLICATION_ID='0'; $env:STEAM_API_KEY='x'; .venv/Scripts/python manage.py check
```
bash:
```
DISCORD_TOKEN=x APPLICATION_ID=0 STEAM_API_KEY=x .venv/Scripts/python manage.py check
```

## When you touched runbot.py, server_monitor.py, or steam_api.py

`manage.py check` does NOT import management commands, and ruff can't see
cross-module attribute existence (a management command with imports of
deleted models passed CI for months). Add an import smoke test:

```
DISCORD_TOKEN=x APPLICATION_ID=0 STEAM_API_KEY=x .venv/Scripts/python -c "import django; django.setup(); from nebulous_bot.management.commands import runbot; from nebulous_bot import server_monitor, steam_api, server_formatter, statistics_tracker, command_logging, graph_generator" 
```
(set `DJANGO_SETTINGS_MODULE=nebulous_project.settings` in the env too).

## When you touched migrations or models

```
DISCORD_TOKEN=x APPLICATION_ID=0 STEAM_API_KEY=x .venv/Scripts/python manage.py makemigrations --check --dry-run
```
This fails if models drifted from migrations. Never edit an applied
migration; add a new one.

## What CANNOT be verified automatically

Live Discord behavior needs a real `DISCORD_TOKEN` + test guild
(`python manage.py runbot`). Don't attempt this without the user's `.env`;
instead state clearly in your report which paths were exercised by tests and
which need a manual smoke test in Discord. The user deploys with
`deployment/oracle/deploy-to-oracle.sh` and watches logs there.

## Test-writing rules (match the existing style)

- Bot tests live in `nebulous_bot/tests/` and are **pure-logic, DB-free**:
  they bypass `ServerMonitor.__init__` via `ServerMonitor.__new__` and set
  only the attributes under test (see `test_waiter_modes.py`). CI runs no
  migrations before pytest, so any test that hits the ORM will fail there.
- `conftest.py` calls `django.setup()` with stub env vars — keep new test
  modules importable under that setup.
- Formation optimizer tests live in `formation_optimizer/tests/` and may use
  the `.fleet` fixtures in `tests/data/`.
