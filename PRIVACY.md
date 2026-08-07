# NebulousServerBot Privacy Policy

_Last updated: August 1, 2026_

NebulousServerBot ("the bot") is an open-source Discord bot that shows live
multiplayer server activity for the game **Nebulous: Fleet Command**. This
document describes what data the bot processes and stores. The bot's full
source code is public: <https://github.com/MatthewARoy/NebulousServerDiscordBot>

## What the bot reads

- **Discord messages.** The bot receives message content through Discord's
  Message Content intent for the sole purpose of detecting and parsing its
  own text commands (messages starting with the `!` prefix). Messages that
  are not bot commands are ignored — they are never stored, analyzed, or
  shared.
- **Game server data.** Server names, maps, player counts, game modes, and
  versions are polled from the Steam Web API and the game servers' public
  query endpoints. This is public game data, not Discord data.

## What the bot stores

- **Command usage logs.** When you invoke a bot command, the bot records the
  command text (truncated to 500 characters), your Discord user ID and
  username, the guild/channel ID and name where the command was used, a
  timestamp, and whether the command succeeded. This is used for debugging
  and understanding which features are used.
- **Guild configuration.** Guild, channel, and role IDs configured by server
  admins (for example, the status channel).
- **Game statistics.** Aggregate server statistics (player counts, maps,
  session lengths) derived from Steam data. No Discord data is included.
- **`!nextgame` waitlist.** Your user ID and chosen queue mode are held in
  memory until you are notified or the waitlist is cleared.

## What the bot does not do

- No reading, storing, or analysis of non-command messages.
- No selling or sharing of data with third parties.
- No use of any data to train machine learning or AI models.
- No tracking of presence, member lists, or any activity outside explicit
  command usage.

## Storage and retention

Data is stored in a private database on a single server operated by the
maintainer and is not accessible to third parties; the server's storage is
encrypted at rest. Stored message content (the text of command invocations)
is automatically deleted after 30 days. Other data is retained only to
provide the features described above.

## Opting out and data removal

If you do not invoke bot commands, no message content of yours is ever
processed or stored. To request deletion of stored data associated with your
Discord account, open an issue at
<https://github.com/MatthewARoy/NebulousServerDiscordBot/issues> or contact
the maintainer on Discord.

## Changes

Updates to this policy are committed to this file in the public repository,
where its history is visible.
