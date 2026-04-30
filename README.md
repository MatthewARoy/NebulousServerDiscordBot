# Nebulous: Fleet Command — Discord Bot

A Discord bot that surfaces live multiplayer server activity for
[**Nebulous: Fleet Command**](https://store.steampowered.com/app/887570/),
the indie space-RTS by Eridanus Industries. The bot polls the Steam Web API,
maintains a live-updating status embed in any number of Discord servers, and
provides a small set of commands for finding open lobbies, tracking game
statistics over time, getting pinged when the next game is ready, and even
optimizing fleet `.fleet` files.

It runs the production deployment for the Nebulous community on Oracle
Cloud's Always Free tier.

> **Status:** active. Source-available as a portfolio / showcase project.

## Highlights

- **Live multi-server status.** A pinned embed updates every 30 seconds with
  active servers, player counts, maps, and game modes — across as many
  Discord guilds as you configure.
- **Self-refreshing command output.** When someone runs `!listservers` or
  `!openlobbies`, the response message keeps refreshing in place. The last
  10 messages per channel stay current so people don't spam the command.
- **`!nextgame` waitlist.** Opt in to a one-shot ping when a lobby reaches
  3+ players or a game enters debrief. Supports PTB-only mode and "skip
  current lobbies".
- **Real statistics.** Every detected game (lobby → in-game ≥5 min →
  debrief) is persisted with map, duration, server, and player count.
  `!stats`, `!mapstats`, `!serverstats`, and a 7-day `!graph` aggregate from
  that history.
- **Fleet formation optimizer.** `!formation` accepts a `.fleet` XML file
  and returns a compacted version (with planar / symmetrical / clear-arcs
  variants) plus an optional GIF of the optimization run.
- **Production-ready.** Django for ORM/migrations/admin, Gunicorn for a
  health endpoint, Docker for packaging, and an Oracle Cloud deploy script
  for the ARM64 free tier.

## Tech stack

Python 3.11 · Django 5 · discord.py · SQLite · Docker · Oracle Cloud (OCI
Always Free, ARM64).

## Repo layout

```
nebulous_bot/            Django app: the bot itself
  └── management/commands/runbot.py   entry point
nebulous_project/        Django project (settings, urls, wsgi)
formation_optimizer/     Standalone fleet-formation library + tests
deployment/
  ├── docker/            Dockerfile, docker-compose
  ├── oracle/            OCI VM setup + deploy scripts
  └── scripts/           env helpers
docs/                    Documentation (start at docs/QUICKSTART.md)
start-server.sh          Container entrypoint
manage.py                Django CLI
requirements.txt
CHANGELOG.md
```

## Quickstart

```bash
git clone https://github.com/MatthewARoy/NebulousServerDiscordBot.git
cd NebulousServerDiscordBot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp env_example.txt .env       # then fill in tokens
python manage.py migrate
python manage.py runbot
```

Full walkthrough: [`docs/QUICKSTART.md`](docs/QUICKSTART.md).

## Documentation

- [`docs/QUICKSTART.md`](docs/QUICKSTART.md) — local setup
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) — environment variables
- [`docs/COMMANDS.md`](docs/COMMANDS.md) — every Discord command
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the pieces fit together
- [`deployment/oracle/README.md`](deployment/oracle/README.md) — production
  deploy on Oracle Cloud

## Contributing

This is primarily a personal / showcase project, but issues and PRs are
welcome. For larger changes, please open an issue first to discuss the
direction.

## Acknowledgements

Not affiliated with Eridanus Industries (the developers of Nebulous: Fleet
Command) or Valve. Built on publicly available APIs.

## License

[MIT](LICENSE).
