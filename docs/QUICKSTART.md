# Quickstart

Get the bot running on your machine in about five minutes.

## Prerequisites

- Python 3.11+ (the production container uses 3.11-slim)
- A Discord bot token and Application ID
  ([Discord Developer Portal](https://discord.com/developers/applications))
- A Steam Web API key
  ([Steam Web API Key page](https://steamcommunity.com/dev/apikey))
- A Discord server you can install the bot into, plus the channel ID where
  you want the live status message to live (enable Developer Mode in Discord,
  right-click → Copy ID)

## 1. Install

```bash
git clone https://github.com/MatthewARoy/NebulousServerDiscordBot.git
cd NebulousServerDiscordBot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Configure

```bash
cp env_example.txt .env
```

Edit `.env` and fill in at minimum:

- `DISCORD_TOKEN`
- `APPLICATION_ID`
- `STEAM_API_KEY`

`SERVER_CONFIGS` is optional. You can either pre-seed it with the guilds
you're deploying for (see [CONFIGURATION.md](CONFIGURATION.md)), or leave
it unset and let admins of each guild set themselves up at runtime with
`!setstatuschannel` — see [COMMANDS.md](COMMANDS.md#per-guild-setup-admin).

See [CONFIGURATION.md](CONFIGURATION.md) for the full set of variables.

## 3. Initialize the database

```bash
python manage.py migrate
```

This creates `db.sqlite3` in the project root with all the tables the bot
needs (sessions, snapshots, command logs, etc.).

## 4. Invite the bot to your Discord server

In the Developer Portal, build an OAuth2 URL with the `bot` scope and these
permissions: Read Messages, Send Messages, Embed Links, Use External Emojis,
Read Message History, and (optionally) Mention Roles. Open the URL and add
the bot to your server.

## 5. Run

```bash
python manage.py runbot
```

You should see `✅ Bot connected as ...` and `✅ Server monitoring started`
in the console. The configured channel will get a live-updating status
embed within ~30 seconds.

## Try it out

In your Discord server:

```
!help
!status
!listservers
!openlobbies
!stats
```

See [COMMANDS.md](COMMANDS.md) for the full command reference.

## Running with Docker

```bash
docker compose -f deployment/docker/docker-compose.yml up --build
```

## Going to production

The bot is designed for Oracle Cloud Infrastructure (Always Free tier). See
[`../deployment/oracle/README.md`](../deployment/oracle/README.md).
