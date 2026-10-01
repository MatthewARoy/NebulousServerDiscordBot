# Commands

New to slash commands? Run `/guide` to read the quick guide directly in Discord.

### `/guide`

Shows a self-contained guide to commands, options, fleet uploads, mention/DM
fallbacks, next-game subscriptions, and troubleshooting. Slash responses are
visible only to the person asking. Mention the bot followed by `guide`, or DM
`!guide`, for the same content. No website or external document is required.

Production 2.10.0 uses Discord's `/` command picker with all privileged intents
off. Plain `!commands` in server channels are no longer the supported command
surface. Legacy commands and aliases work in DMs or after a direct bot mention,
for example `!ng` in a DM or `@NebulousServerBot ng` in a server.

Slash aliases are not registered: use `/nextgame`, not `/ng`, and `/listservers`,
not `/ls`. Prefix examples below apply to DMs; in servers, replace `!` with a
direct bot mention. Server-only commands still require a server.

## Help

Discord's command picker is the primary menu. The legacy/mention command
`!help [command|category]` (alias `!commands`) provides an embed reference:

- `!help` — every command you can run, one line each, grouped by category
  (Servers, Statistics, Next Game, Formation, Advice, Fleet Design, Setup, Admin).
- `!help <command>` — summary, usage, examples, aliases and cooldown, e.g.
  `!help nextgame`. Also accepts the prefix (`!help !nextgame`).
- `!help <category>` — every command in one group, e.g. `!help servers`.
  Category names are matched case- and space-insensitively (`next game`,
  `nextgame`, `Next Game`).

The pages are generated from each command's docstring
(`nebulous_bot/help_command.py`), so a command's `Usage:`/`Examples:` lines
are what users see — there is no separate help table to keep in sync.

Visibility rules:

- Commands whose checks you fail are left out (a non-admin never sees the
  `!setstatuschannel` family).
- Commands marked `hidden=True` — the maintenance ones, `!commandlogs`,
  `!restartmonitor`, `!debugmonitor` — are shown **only to the bot owner**,
  marked 🔒. For anyone else `!help commandlogs` answers exactly like an
  unknown name, so the help menu never confirms they exist, and typo
  suggestions never mention them. `hidden` controls help visibility only;
  who may *run* a command is still its own check (`is_owner`,
  `has_permissions`).

## Server discovery

### `/listservers [filters]`
Lists active Nebulous servers. Filters can be combined.
The slash surface rejects unknown filter words instead of silently returning an
unfiltered list; legacy prefix parsing retains its historical behavior.

| Filter | Effect |
|---|---|
| `ptb` | Only test-branch servers (🧪) |
| `open` | Only servers with available slots |
| `lobby` | Only servers in lobby state |
| `ingame` | Only servers currently in-game |
| `us` / `eu` | Filter by region |
| `competitive` / `casual` | Filter by game mode |
| `all` | Include empty, password-protected, and bot-populated servers |

Examples: `/listservers`, `/listservers filters:ptb open`. Legacy aliases:
`!ls`, `!servers`.

### `/openlobbies`
Shows servers with at least one open slot, sorted by most open first.
Legacy aliases: `!open`, `!available`.

### `/refresh`
Force-fetches fresh data from Steam, bypassing the 30-second poll interval.
Legacy alias: `!update`.

## Notifications

### `/nextgame [filters]`
Pings you once when a game looks ready. Triggers on:

- a lobby reaching 3+ players (and not full), or
- a game entering debrief (about to roll over).

Modifiers (stackable — each one you add narrows the queue further):

- `ptb` — only notify for test-branch servers.
- `modded` (also `mod`, `mfc`) — only notify for servers running mods.
- `newplayer` (also `np`, `beginner`) — only notify for new-player servers
  (detected from the server name, e.g. "New Player" / "Beginner").
- `lobby` — only ping when a lobby is ready; suppress debrief alerts.
- `--skip` (also `-skip`, `skip`) — ignore lobbies that were already active
  when you opted in.

Each modifier combination is its own queue: you can wait for a modded game
and a new-player game at the same time. `/cancelnextgame` clears all of them.
Enter modifiers together in the `filters` option. Legacy aliases: `!notify`,
`!notifyme`, `!ng`. The slash surface rejects misspelled filters so it cannot
silently enroll you in a broader queue.

### `/cancelnextgame`
Removes you from the waitlist.

## Statistics

### `/stats [timeframe]`
Game statistics overview. `timeframe` ∈ {`all`, `today`, `week`, `month`}
(default `all`).

### `/mapstats [limit]`
Most-played maps with averages. Default `limit` = 10; valid range 1–25.

### `/serverstats [limit]`
Most-active servers ranked by games hosted. Default `limit` = 10; valid range
1–25.

### `/graph [metric]`
Renders a 7-day graph of the requested metric. Metrics:
`players online` (default), `servers`, `lobbies`, `games in progress`.

## Fleet tools

### `/shipbuilding [options]`

Returns ship design principles and the complete attached guide for standard
3,000-point team PvP. Optional `options` accepts a role and `--lean`, for
example `frontline --lean`. Roles: `frontline`, `skirmish`, `denial`,
`capture`, `scouting`, `missile-support`, `carrier-support`. Lean investment
does not remove essential weapon requirements. Slash replies are private.

### `/fleetcheck attachment:<fleet-or-ship> [options]`

Accepts exactly one `.fleet` or `.ship` file, up to 2 MiB, and returns a
private summary plus a complete text report. The file is preserved. Optional
role and `--lean` flags set a review lens, not a role assigned to every ship.
The five source-linked fitting checks cover beam support/fire control,
plotting support and supported 450 mm ammunition loads. Removed community
advice is excluded; unavailable moderation state withholds advice while
independent mechanics checks remain available. Zero findings is not a
quality verdict.

Regional protection defaults to `--threat hei --direction bow`. For example,
`options:--threat 450-ap --direction port` selects a different ray profile
and direction. Directions: `bow`, `stern`, `port`, `starboard`, `top`,
`bottom`. A matching private geometry dataset must be configured by the
operator. The current cache supports conditional HEI/450 AP ray samples;
other automatic profiles or unavailable geometry yield unknown coverage.
In particular, HE explosion overlap completeness is not established by this
cache, so automatic 120/250/450 HE results are unknown.

Reports show individual DT margins, tested/unknown probes, supporting
recipients and their vulnerabilities, plus bounded candidates for adding
one empty Reinforced Magazine to a vacant compatible socket. These are
five-sample, hypothetical internal paths; armor entry, penetration,
overpenetration, subsequent damage and full attack coverage are not solved.
Queries reaching 20 raw collider hits, including structural hits before
recipient filtering, are unknown. Candidate additions are withheld if their
own or improved targets' probes depend on vulnerable or unknown support.
Candidate cost, mass, crew/resources and capacity need checking in the
editor. No fleet changes are applied.

The optional diagnostic mode accepts
`options:--stack SHIP_KEY:SOCKET,SOCKET --threat hei --dr 0.2`, using exact
keys from a first report. Supply all three flags together and omit
`--direction` for this mode. The ordered hit collection and DR are explicit
assumptions, not inferred geometry. Its eight profiles are `hei`, `120-he`,
`250-he`, `450-he`, `450-ap`, `300-rail`, `600-hesh`, `500-fracturing`.

For manual scenarios, blue means all selected recipients are within DT
under the assumptions; amber means DT exceeded; grey means unknown. Regional
results additionally retain supporting-part vulnerabilities. Overlay
projections use amber for vulnerable support and grey for unknown support
even when the target's own status remains within DT. HP loss and disabled functions remain
possible below DT. No calibre-wide or combat-immunity verdict is produced.
All usage and limits are also provided inside `/shipbuilding`, `/guide`,
command help and the report; users do not need external documentation.

Mention/DM equivalents retain `!shipbuilding`, `!fleetcheck`, and the
`!shipcheck` alias. Attach the file to the message and put the same options
in its text. The slash alias `/shipcheck` is not registered. These new
commands require a separate deployment and deliberate owner sync before
appearing on the production command picker; startup never syncs them.

### `/formation attachment:<fleet> [options]`
Optimize a `.fleet` XML file using the typed attachment option.

- radius — minimum spacing in meters (default `350`), entered first in the
  optional `options` string.
- `-skip` — skip animation generation (faster).
- `-planar` — flat formation facing forward.
- `-symmetrical` — symmetrize the result.
- `-arcs` — preserve forward firing arcs for armed ships.

The bot replies with the optimized fleet file and (unless `-skip`) a GIF of
the optimization process. Legacy aliases: `!form`, `!optimize`; for a prefix
invocation, attach the fleet to the message and put the options in its text.
Only one fleet is processed at a time; additional requests fail fast and can be
retried shortly rather than queuing large files in memory.

## Bot status

### `/status`
Bot health, deployment time, monitoring task state, and a command summary.

### `/version`
Current version and recent changelog entries (mirrors `nebulous_bot/config.py`).

## Per-guild setup (admin)

These let an admin in any guild the bot has joined point it at the right
channels. Settings are stored per-guild in the database and override the
maintainer's bootstrap config (see [CONFIGURATION.md](CONFIGURATION.md)).

### `/setstatuschannel [channel]`
Sets the channel where the bot posts the live, auto-updating server
status embed. With no argument, defaults to the channel the command is
run in. Admin-only.

### `/setnotificationchannel [channel]`
Sets the channel for player-threshold pings. Optional — without it, no
threshold pings are sent for this guild. Admin-only.

### `/setnotificationrole role`
Sets which role the bot pings on threshold notifications. Admin-only.

### `/removestatus`
Stops the live status embed in this guild. Admin-only.

### `/showsetup`
Shows the current setup for this guild and indicates whether it's coming
from a setup command, the bootstrap config, or unset.

Legacy aliases for setup remain available only on the prefix/mention surface:
`!setstatus`, `!setnotifchannel`, `!setnotifrole`, `!unsetstatus`, `!mysetup`,
and `!guildconfig`.

## Community advice

### `/advice search [query]`
Search the curated and community knowledge pool. Omitting the query shows the
available topics and search guidance.

### `/advice add [text]`
Propose advice for a community vote. Guild-only; the existing user cooldown
and reaction-ballot flow apply.

### `/advice remove [entry_id]`
Propose removing an incorrect entry by its displayed ID. Guild-only; the
existing user cooldown and reaction-ballot flow apply.

### `/advice pending`
Show advice votes currently open.

### `/advice list [section] [page]`
Audit the pool by category or with `community`, `incorrect`, or `all`.

The owner-only `advice restore` operation remains prefix/mention-only and is
not published in the application-command picker.

## Admin (operations)

These are prefix/mention-only and hidden from `!help` for everyone but the bot owner (see
[Help](#help)); the permission checks below are what gate running them.

### `!restartmonitor` — alias `!restart`
Restart the server-monitoring loop (administrator only).

### `!debugmonitor`
Detailed monitoring-loop diagnostics (administrator only).
