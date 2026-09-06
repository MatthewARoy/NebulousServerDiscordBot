# Discord migration test harness

The migration has two complementary test lanes. A human tester validates the
real application-command UI on a separate Discord application. The existing
puppet bot continues automated smoke checks through mention-prefixed commands.
Discord bots cannot invoke another application's slash commands, so the puppet
lane is useful but is not slash-command acceptance testing.

## Test application and test guild

Use a separate Discord application and token for migration testing. Do not
change the production application's intents or synchronize its global command
tree during this phase.

1. Invite the test application to a guild listed in
   `TEST_COMMAND_GUILD_IDS`, with the `bot` and `applications.commands`
   scopes.
2. In that test application's Bot settings, disable Message Content before
   the intent-off acceptance pass.
3. Run the migration branch against the test token and database/configuration
   intended for testing with `python manage.py runbot --without-message-content`.
   The compatibility default remains enabled for production until the later
   cutoff release.
4. As the bot owner, directly mention the bot:
   `@Bot synccommands guild <test-guild-id>`. Mention content remains available
   without the privileged intent. The command rejects guilds outside
   `TEST_COMMAND_GUILD_IDS`.
5. Never use `synccommands global` during test-guild validation. Global sync
   requires the exact confirmation token `CONFIRM_GLOBAL_COMMAND_SYNC` and is
   reserved for the separately approved production release step.

Command synchronization is deliberately manual. Startup and reconnect paths
do not synchronize the tree.

## Human slash-command acceptance pass

With Message Content disabled on the test application, use Discord's command
picker and verify:

- Every intended public command and advice subcommand appears with clear
  descriptions and option names.
- Administrative maintenance commands do not appear.
- `/version`, `/status`, `/listservers`, `/openlobbies`, and `/refresh`
  complete successfully.
- `/stats` and `/graph` acknowledge within three seconds and eventually
  return their result.
- `/formation` accepts an uploaded fleet attachment, acknowledges promptly,
  and returns a result; invalid XML, excessive size/depth, and invalid radius
  produce a bounded user-facing error.
- `/advice search`, `/advice search query:tags`, `/advice add`, `/advice remove`,
  `/advice pending`, and `/advice list` preserve their permissions, voting
  behavior, and useful error messages.
- `/nextgame` and its related commands preserve waitlist behavior.
- Server-list/status messages still update after the original interaction
  token has expired; tracked messages must be edited through the bot-authenticated
  channel message.
- Cooldowns, permission failures, and malformed options return a private,
  actionable error rather than timing out.

Record the application ID, guild ID, branch commit, Python version, command
count, and pass/fail evidence. This is the gate before any production global
sync or Message Content change.

## Automated puppet smoke lane

A Codex session can use the community `mcp-discord` server with a dedicated
puppet bot in test guilds. The puppet needs View Channels, Send Messages, Read
Message History, and Add Reactions. Keep its token in the user-level
`DISCORD_TEST_BOT_TOKEN` environment variable and never commit or reuse the
production token.

Project-scoped `.mcp.json` example:

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

discord.py normally ignores bot-authored messages. The harness bypass is
enabled only when both fail-closed allowlists are populated:

- `TEST_COMMAND_BOT_IDS`: explicit puppet bot user IDs.
- `TEST_COMMAND_GUILD_IDS`: explicit test guild IDs.

DMs never qualify, the bot never processes its own messages, and the bypass is
covered by tests. After Message Content is disabled, use the production/test
bot mention rather than `!`, because Discord continues to deliver messages
that directly mention the application:

1. `<@BOT_ID> version`
2. `<@BOT_ID> advice fpa`
3. `<@BOT_ID> status`

This lane proves the fallback and response surface remain alive. It cannot
prove slash registration, option transformation, interaction deferral, or
ephemeral errors; those remain part of the human acceptance pass.
