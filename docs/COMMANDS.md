# Commands

All commands use the `!` prefix. Most are usable in DMs as well as guilds.
Run `!status` to see a summary in Discord.

## Server discovery

### `!listservers [filters]` — aliases `!ls`, `!servers`
Lists active Nebulous servers. Filters can be combined.

| Filter | Effect |
|---|---|
| `ptb` | Only test-branch servers (🧪) |
| `open` | Only servers with available slots |
| `lobby` | Only servers in lobby state |
| `ingame` | Only servers currently in-game |
| `us` / `eu` | Filter by region |
| `competitive` / `casual` | Filter by game mode |
| `all` | Include empty, password-protected, and bot-populated servers |

Examples: `!listservers`, `!listservers ptb open`, `!ls lobby us`.

### `!openlobbies` — aliases `!open`, `!available`
Shows servers with at least one open slot, sorted by most open first.

### `!refresh` — alias `!update`
Force-fetches fresh data from Steam, bypassing the 30-second poll interval.

## Notifications

### `!nextgame [ptb] [--skip]` — aliases `!notify`, `!notifyme`, `!ng`
Pings you once when a game looks ready. Triggers on:

- a lobby reaching 3+ players (and not full), or
- a game entering debrief (about to roll over).

Modifiers:

- `ptb` — only notify for test-branch servers.
- `--skip` — ignore lobbies that were already active when you opted in.

### `!cancelnextgame` — alias `!nextgamecancel`
Removes you from the waitlist.

## Statistics

### `!stats [timeframe]` — alias `!statistics`
Game statistics overview. `timeframe` ∈ {`all`, `today`, `week`, `month`}
(default `all`).

### `!mapstats [limit]` — alias `!maps`
Most-played maps with averages. Default `limit` = 10.

### `!serverstats [limit]` — alias `!serverinfo`
Most-active servers ranked by games hosted. Default `limit` = 10.

### `!graph [metric]`
Renders a 7-day graph of the requested metric. Metrics:
`players online` (default), `servers`, `lobbies`, `games in progress`.

## Fleet tools

### `!formation [min_radius] [-skip] [-planar] [-symmetrical] [-arcs]` — aliases `!form`, `!optimize`
Optimize a `.fleet` XML file. Attach the file to your message.

- `min_radius` — minimum spacing in meters (default `350`).
- `-skip` — skip animation generation (faster).
- `-planar` — flat formation facing forward.
- `-symmetrical` — symmetrize the result.
- `-arcs` — preserve forward firing arcs for armed ships.

The bot replies with the optimized fleet file and (unless `-skip`) a GIF of
the optimization process.

## Bot status

### `!status` — alias `!info`
Bot health, deployment time, monitoring task state, and a command summary.

### `!version` — aliases `!v`, `!changelog`
Current version and recent changelog entries (mirrors `nebulous_bot/config.py`).

## Per-guild setup (admin)

These let an admin in any guild the bot has joined point it at the right
channels. Settings are stored per-guild in the database and override the
maintainer's bootstrap config (see [CONFIGURATION.md](CONFIGURATION.md)).

### `!setstatuschannel [#channel]` — alias `!setstatus`
Sets the channel where the bot posts the live, auto-updating server
status embed. With no argument, defaults to the channel the command is
run in. Admin-only.

### `!setnotificationchannel [#channel]` — alias `!setnotifchannel`
Sets the channel for player-threshold pings. Optional — without it, no
threshold pings are sent for this guild. Admin-only.

### `!setnotificationrole @role` — alias `!setnotifrole`
Sets which role the bot pings on threshold notifications. Admin-only.

### `!removestatus` — alias `!unsetstatus`
Stops the live status embed in this guild. Admin-only.

### `!showsetup` — aliases `!mysetup`, `!guildconfig`
Shows the current setup for this guild and indicates whether it's coming
from a `!set...` command, the bootstrap config, or unset.

## Admin (operations)

### `!restartmonitor` — alias `!restart`
Restart the server-monitoring loop (administrator only).

### `!debugmonitor`
Detailed monitoring-loop diagnostics (administrator only).
