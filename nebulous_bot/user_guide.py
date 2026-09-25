"""Self-contained user guidance rendered directly in Discord."""

import discord

from nebulous_bot.config import Config


def build_user_guide(*, message_content: bool) -> discord.Embed:
    embed = discord.Embed(
        title="📖 NebulousServerBot quick guide",
        description=(
            "Type `/`, choose a command belonging to this bot, fill in its options, "
            "and send. Everything you need to get started is here in Discord."
        ),
        color=Config.EMBED_COLOR,
    )
    fields = [
        ("Find servers and games", (
            "`/listservers` — browse servers; try **filters**: `us open`\n"
            "`/openlobbies` — find a lobby with room\n"
            "`/nextgame` — get a one-time game-ready ping; try **filters**: `modded lobby`\n"
            "`/cancelnextgame` — cancel your game-ready pings"
        )),
        ("Statistics and advice", (
            "`/stats` — game statistics; try **timeframe**: `week`\n"
            "`/mapstats` and `/serverstats` — popular maps and servers\n"
            "`/graph` — player counts and other trends\n"
            "`/advice search` — search tips; try **query**: `missile defense`\n"
            "`/advice add` — propose advice for a community vote"
        )),
        ("Upload a fleet", (
            "Choose `/formation`, select **attachment**, and upload your `.fleet` file "
            "(up to 2 MiB). The bot returns an optimized fleet and animation.\n"
            "Default spacing is 350 meters. For other settings, use **options**, "
            "for example `500 -planar`. Add `-skip` to omit the animation. "
            "If another fleet is processing, wait and try again."
        )),
        ("Familiar commands and help", (
            ("Plain `!commands` still work in server channels during the transition. "
             "Start using slash commands now; plain server commands will stop at cutoff.\n"
             if message_content else
             "Use slash commands instead of plain `!commands` in server channels.\n")
            + "You can also select the bot from the mention picker, then type `help`, "
            "`help formation`, or another command. In a DM, use `!help` or `!version`. "
            "Server-only commands still need a server. Short aliases such as `!ls` "
            "become `/listservers` in the slash menu."
        )),
        ("Waiting for a game?", (
            "Pending one-time `/nextgame` subscriptions reset when the bot restarts. "
            "If you were waiting before an update, run `/nextgame` again afterward."
        )),
        ("Missing a command?", (
            "Make sure you selected this bot, then reopen the command picker. "
            "If commands are still missing, ask a server admin to check "
            "**Use Application Commands** for this channel and the bot's command "
            "permissions under **Server Settings → Integrations**.\n"
            "Use `/status` to check the bot and `/version` for release notes. "
            "If something fails, tell Davaned which command you used and what happened."
        )),
    ]
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text="Use /guide anytime • Mention the bot followed by help for detailed command help")
    return embed
