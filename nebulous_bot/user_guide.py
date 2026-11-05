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
        ("Build and review ships", (
            "`/shipbuilding` — read design guidance; try **options**: `frontline --lean`\n"
            "`/fleetcheck` — upload one `.fleet` or `.ship` using **attachment** (up to 2 MiB). "
            "The bot returns advice and a complete report without changing the file. "
            "Regional checks use HEI or 450 AP rays; try **options**: `--threat 450-ap --direction port`. "
            "HE explosion profiles need the manual calculator with the current geometry cache. "
            "Missing geometry or unsupported coverage is grey. "
            "For a manual DT scenario, put `--stack SHIP:SOCKET,SOCKET --threat hei --dr 0.2` "
            "in **options**, using exact keys from your first report. Manual blue is conditional, "
            "amber exceeds DT, grey is unknown. Regional reports also flag vulnerable support. HP loss and disabled functions remain possible; "
            "the colors do not certify combat immunity. Read the report's assumptions and limits."
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
