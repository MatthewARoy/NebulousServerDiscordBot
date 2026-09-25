# NebulousServerBot: using slash commands

Guide for the 2.10.0 rollout. During rollout, use `/version` to check which
version your server is running.

## Getting started

1. In the channel where you use the bot, type `/`.
2. Choose a command belonging to **NebulousServerBot**.
3. Fill in any options Discord shows, then send the command.

For example, choose `/listservers`, select its `filters` option, and enter
`us open`. The option labels below show what to fill in; you do not need to
paste an entire example as a normal chat message.

| What you want | Command | Example option |
|---|---|---|
| Browse active servers | `/listservers` | `filters`: `us open` |
| Find a lobby with room | `/openlobbies` | No options needed |
| Get a one-time game-ready ping | `/nextgame` | `filters`: `modded lobby` |
| Cancel your game-ready pings | `/cancelnextgame` | No options needed |
| See game statistics | `/stats` | `timeframe`: `week` |
| Browse popular maps or servers | `/mapstats`, `/serverstats` | `limit`: `10` |
| Show a player-count graph | `/graph` | Default metric: players online |
| Search gameplay tips | `/advice search` | `query`: `missile defense` |
| Propose a tip for a community vote | `/advice add` | `text`: your advice |
| Optimize a fleet | `/formation` | `attachment`: your `.fleet` file |
| Check the bot or read release notes | `/status`, `/version` | No options needed |

## Uploading a fleet

Choose `/formation`, select **attachment**, and upload your `.fleet` file.
Send the command to use the default spacing of 350 meters. The bot returns
an optimized fleet and an animation.

For different settings, use **options**, for example `500 -planar`.
Add `-skip` to omit the animation. Keep files at or below 2 MiB. If another
fleet is being processed, wait for it to finish and try again.

## What happens to the old commands?

During the initial rollout, ordinary `!commands` continue working in server
channels. Once the switch is complete, use slash commands there instead.
Short aliases such as `!ls` become `/listservers` in the slash menu.

You can still use familiar commands by directly mentioning the bot, followed
by the command: **@NebulousServerBot help** or **@NebulousServerBot listservers**.
Select the actual bot from Discord's mention picker. You can also send the bot
a direct message such as `!help` or `!version`; server-only commands still need
to be run in a server.

Live status updates, game history, and advice remain part of the bot.
**If you were waiting for a next-game ping before the update, run `/nextgame`
again afterward.** Pending one-time subscriptions reset when the bot restarts.

## If a command is missing

Check that you selected NebulousServerBot rather than another app. Reopen the
command picker after the update. If its commands are still missing, ask a
server admin to check the channel's **Use Application Commands** permission
and the bot's command permissions under **Server Settings → Integrations**.
Discord documents these controls in its [command permissions guide](https://support-apps.discord.com/hc/en-us/articles/26501869403159-Command-Permissions).

For help, mention the bot followed by `help`. For a failed command, tell the
maintainer which command you used, when it happened, and what error appeared.

Admins can use `/showsetup` to inspect the existing channel configuration.
The migration does not require everyone to reconfigure the bot.

See the [full command reference](COMMANDS.md) for filters, advice voting,
formation options, and admin commands.
