# Discord test harness: driving the bot from a Claude session

Lets a Claude Code session run deploy smoke tests end to end in the test
Discord servers: post `!advice fpa` as a puppet bot, read the production
bot's reply, assert on it. Two pieces make it work.

## Piece 1: a Discord MCP server (session side)

The session talks to Discord through the community `mcp-discord` MCP
server (https://github.com/barryyip0625/mcp-discord, runs via npx), using
a dedicated puppet bot account. One-time setup:

1. In the Discord developer portal (https://discord.com/developers/applications)
   create a new application, e.g. "Neb Test Puppet", and add a bot to it.
   This is a separate application from the production bot.
2. Under Bot, enable the Message Content intent (required to read command
   output; the MCP server also wants Server Members and Presence).
3. Invite it to the TEST servers only, never the main Nebulous server.
   Needed permissions: View Channels, Send Messages, Read Message
   History, Add Reactions.
4. Put the bot token in a user-level environment variable named
   `DISCORD_TEST_BOT_TOKEN` (do not commit it anywhere, and do not reuse
   the production token).
5. Create `.mcp.json` at the repo root with exactly:

   ```json
   {
     "mcpServers": {
       "discord-test": {
         "command": "npx",
         "args": ["-y", "mcp-discord"],
         "env": {
           "DISCORD_TOKEN": "${DISCORD_TEST_BOT_TOKEN}"
         }
       }
     }
   }
   ```

   `.mcp.json` is project-scoped; approve the server when Claude Code
   prompts. The token stays in your environment, the file only references
   it.

## Piece 2: the command allowlist (bot side)

discord.py ignores every bot-authored message before command processing,
so out of the box the production bot would never answer the puppet. The
bot now has a gated bypass driven by two `.env` values that must BOTH be
set (either one empty means the harness is fully off, fail closed):

- `TEST_COMMAND_BOT_IDS`: comma-separated puppet bot user ids.
- `TEST_COMMAND_GUILD_IDS`: the guilds where the bypass applies. The
  designated test guild is Davaned's server, `1400973312963645551`; the
  harness is deliberately scoped so bot-driven commands work there and
  nowhere else, even if the puppet ever ends up in another guild.

Get the puppet's user id from the developer portal, or right-click it in
Discord with developer mode on. The deploy script copies `.env` to the
VM, so the settings reach production on the next deploy.

Safety properties, in case this ever needs auditing: both allowlists are
empty by default, ids are explicit, DMs never qualify, the bot never
processes its own messages, and the puppet holds no command handlers of
its own, so a message loop cannot form. The guard is the pure function
`harness_command_allowed` in `nebulous_bot/config.py`, covered by tests.

## The smoke-test loop a session runs after a deploy

1. `!version` in a test channel, read the embed, assert the new version.
2. `!advice fpa` (or whatever the release changed), read the reply embed.
3. `!status` to confirm monitoring is up.

The production bot must be in the test guild too (it already is, that is
what the test servers are for).
