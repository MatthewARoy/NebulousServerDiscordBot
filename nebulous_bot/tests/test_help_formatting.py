"""Tests for the !help menu formatting and visibility rules.

The help embeds are generated from the cogs' own docstrings, so these
tests feed the parser docstrings copied verbatim from the real commands —
if someone reformats one, the help output stops matching and these fail.

The visibility tests build a throwaway Bot in memory (no gateway, no ORM)
with a stubbed `is_owner`, because "hidden owner commands stay hidden" is
the kind of rule that only breaks in production otherwise.
"""
import asyncio
from types import SimpleNamespace

import discord
import pytest
from discord import Embed
from discord.ext import commands

from nebulous_bot.help_command import (
    NebulousHelpCommand,
    CATEGORY_META,
    FIELD_VALUE_LIMIT,
    add_chunked_field,
    category_emoji,
    category_sort_key,
    chunk_lines,
    format_example,
    parse_help_sections,
    split_examples,
    truncate,
)

# Copied verbatim from ServersCog.list_servers.
LISTSERVERS_DOC = """
        List all active servers with optional filtering

        Usage: !listservers [filter]
        Filters: ptb, open, lobby, ingame, us, eu, competitive, casual, all
        Examples: !listservers ptb, !listservers open, !listservers lobby us, !listservers all
        """

# Copied verbatim from StatsCog.show_graph.
GRAPH_DOC = """
        Display a graph of data over the last week.

        Usage: !graph [value]
        Examples:
            !graph players online
            !graph servers
            !graph lobbies
            !graph games in progress
        """

# Copied verbatim from NextGameCog.next_game_notify.
NEXTGAME_DOC = """
        Get notified when the next game is ready to join.

        Usage: !nextgame [ptb] [modded] [newplayer] [lobby] [--skip]
        - !nextgame - Notify for all servers
        - !nextgame ptb - Notify only for PTB (test branch) servers
        - !nextgame --skip (or -skip) - Don't notify for lobbies already active right now

        You'll be pinged once when either:
        - A game enters debrief (game just ended, new one might start)
        - A lobby is at least half full (game about to start)
        """

# Copied verbatim from FormationCog.optimize_formation (trimmed bullets).
FORMATION_DOC = """
        Optimize a fleet formation file by compacting ships while maintaining minimum distance.

        Usage: !formation [min_radius_meters] [-skip] [-planar] [-symmetrical] [-arcs]
        - Attach a .fleet XML file to your message
        - Optional: use -skip to skip image generation (faster)

        Example: !formation 350  (for 350 meters)
        Example: !formation 500 -planar  (planar formation)
        """


def test_listservers_sections():
    sections = parse_help_sections(LISTSERVERS_DOC)
    assert sections.summary == "List all active servers with optional filtering"
    assert sections.usage == ["!listservers [filter]"]
    assert sections.examples == [
        "!listservers ptb",
        "!listservers open",
        "!listservers lobby us",
        "!listservers all",
    ]
    # Anything that isn't a usage/example line stays available as detail.
    assert "Filters: ptb, open, lobby, ingame, us, eu, competitive, casual, all" in sections.details


def test_examples_header_takes_the_indented_lines_below_it():
    sections = parse_help_sections(GRAPH_DOC)
    assert sections.usage == ["!graph [value]"]
    assert sections.examples == [
        "!graph players online",
        "!graph servers",
        "!graph lobbies",
        "!graph games in progress",
    ]
    assert sections.details == []


def test_command_bullets_become_examples_other_bullets_stay_details():
    sections = parse_help_sections(NEXTGAME_DOC)
    assert sections.summary == "Get notified when the next game is ready to join."
    assert sections.examples == [
        "!nextgame - Notify for all servers",
        "!nextgame ptb - Notify only for PTB (test branch) servers",
        "!nextgame --skip (or -skip) - Don't notify for lobbies already active right now",
    ]
    assert sections.details[0] == "You'll be pinged once when either:"
    assert "- A game enters debrief (game just ended, new one might start)" in sections.details


def test_repeated_example_headers_accumulate():
    sections = parse_help_sections(FORMATION_DOC)
    assert sections.usage == ["!formation [min_radius_meters] [-skip] [-planar] [-symmetrical] [-arcs]"]
    assert sections.examples == [
        "!formation 350  (for 350 meters)",
        "!formation 500 -planar  (planar formation)",
    ]
    assert "- Attach a .fleet XML file to your message" in sections.details


def test_single_line_docstring_is_all_summary():
    sections = parse_help_sections("Show general game statistics")
    assert sections.summary == "Show general game statistics"
    assert sections.usage == []
    assert sections.examples == []
    assert sections.details == []


def test_missing_docstring_is_empty():
    sections = parse_help_sections(None)
    assert sections.summary == ""
    assert sections.usage == []
    assert sections.examples == []
    assert sections.details == []


def test_split_examples_only_breaks_before_a_new_command():
    assert split_examples("!commandlogs 10, !commandlogs 50 stats") == [
        "!commandlogs 10",
        "!commandlogs 50 stats",
    ]
    # A comma inside one example must not split it.
    assert split_examples("!listservers lobby, us") == ["!listservers lobby, us"]


@pytest.mark.parametrize(
    "example,expected",
    [
        ("!formation 350  (for 350 meters)", "`!formation 350` — for 350 meters"),
        ("!nextgame ptb - Notify only for PTB servers", "`!nextgame ptb` — Notify only for PTB servers"),
        ("!graph servers", "`!graph servers`"),
        # A leading double-dash flag is an argument, not a note separator.
        ("!nextgame --skip - Skip active lobbies", "`!nextgame --skip` — Skip active lobbies"),
        ("!nextgame --skip", "`!nextgame --skip`"),
    ],
)
def test_format_example(example, expected):
    assert format_example(example) == expected


def test_truncate_leaves_short_text_alone():
    assert truncate("Force refresh the server list", width=40) == "Force refresh the server list"


def test_truncate_cuts_on_a_word_boundary():
    result = truncate("Show map play frequency statistics calculated from games", width=30)
    assert len(result) <= 30
    assert result.endswith("…")
    assert "statistic" not in result.rstrip("…")  # cut before the partial word


def test_chunk_lines_never_splits_a_line():
    lines = ["x" * 500, "y" * 500, "z" * 500]
    chunks = chunk_lines(lines, limit=FIELD_VALUE_LIMIT)
    assert len(chunks) == 2
    assert all(len(chunk) <= FIELD_VALUE_LIMIT for chunk in chunks)
    assert chunks[0] == "x" * 500 + "\n" + "y" * 500
    assert chunks[1] == "z" * 500


def test_chunk_lines_truncates_an_over_long_line():
    chunks = chunk_lines(["q" * 2000], limit=FIELD_VALUE_LIMIT)
    assert len(chunks) == 1
    assert len(chunks[0]) == FIELD_VALUE_LIMIT
    assert chunks[0].endswith("…")


def test_add_chunked_field_marks_continuations():
    embed = Embed()
    add_chunked_field(embed, "🚀 Servers", ["a" * 700, "b" * 700])
    assert [field.name for field in embed.fields] == ["🚀 Servers", "🚀 Servers (cont.)"]
    assert all(len(field.value) <= FIELD_VALUE_LIMIT for field in embed.fields)


def test_categories_sort_in_declared_order_with_unknown_cogs_last():
    names = ["Zebra", "Admin", "Servers", "Statistics"]
    assert sorted(names, key=category_sort_key) == ["Servers", "Statistics", "Admin", "Zebra"]


def test_every_known_category_has_an_emoji():
    assert all(emoji for emoji, _ in CATEGORY_META.values())
    assert category_emoji("Not A Real Cog") == "📁"


# --- visibility: hidden owner-only commands ---------------------------------


class _FakeChannel:
    """Collects the embeds the help command sends."""

    def __init__(self):
        self.embeds = []

    async def send(self, *, embed=None, **kwargs):
        self.embeds.append(embed)


def _build_bot(*, is_owner: bool):
    """A gateway-free Bot with one public and one hidden owner-only command."""
    bot = commands.Bot(
        command_prefix='!',
        intents=discord.Intents.none(),
        help_command=NebulousHelpCommand(),
    )

    @bot.command(name='openlobbies')
    async def open_lobbies(ctx):
        """List servers with available player slots"""

    @bot.command(name='commandlogs', aliases=['cmdlogs', 'logs'], hidden=True)
    @commands.is_owner()
    async def command_logs(ctx):
        """View command usage logs (bot owner only)"""

    # is_owner() would otherwise fetch application info over the network.
    async def fake_is_owner(user):
        return is_owner

    bot.is_owner = fake_is_owner
    return bot


def _ask_help(*, is_owner: bool, argument=None):
    """Run one `!help [argument]` invocation and return the embeds sent."""

    async def run():
        bot = _build_bot(is_owner=is_owner)
        channel = _FakeChannel()
        help_command = bot.help_command
        ctx = SimpleNamespace(
            bot=bot,
            author=object(),
            guild=None,
            channel=channel,
            clean_prefix='!',
            command=None,
            send=channel.send,
        )
        help_command.context = ctx
        await help_command.command_callback(ctx, command=argument)
        return channel.embeds

    return asyncio.run(run())


def _embed_text(embed):
    parts = [embed.title or '', embed.description or '']
    parts += [f'{field.name}\n{field.value}' for field in embed.fields]
    return '\n'.join(parts)


def test_hidden_command_is_absent_from_the_menu_for_non_owners():
    text = '\n'.join(_embed_text(embed) for embed in _ask_help(is_owner=False))
    assert 'openlobbies' in text
    assert 'commandlogs' not in text


def test_hidden_command_help_page_is_refused_for_non_owners():
    embeds = _ask_help(is_owner=False, argument='commandlogs')
    assert len(embeds) == 1
    # Must not confirm the command exists — same answer as a bogus name.
    assert embeds[0].title == '❓ Not found'
    assert 'No command or category called `commandlogs`' in embeds[0].description


def test_hidden_command_aliases_are_refused_for_non_owners():
    embeds = _ask_help(is_owner=False, argument='logs')
    assert embeds[0].title == '❓ Not found'


def test_typo_suggestions_never_leak_a_hidden_command():
    embeds = _ask_help(is_owner=False, argument='commandlog')
    assert embeds[0].title == '❓ Not found'
    assert 'commandlogs' not in embeds[0].description
    assert 'cmdlogs' not in embeds[0].description


def test_owner_sees_the_hidden_command_in_the_menu():
    text = '\n'.join(_embed_text(embed) for embed in _ask_help(is_owner=True))
    assert 'commandlogs' in text
    assert '🔒' in text


def test_owner_gets_the_hidden_command_help_page():
    embeds = _ask_help(is_owner=True, argument='commandlogs')
    assert embeds[0].title == '📁 !commandlogs'
    assert any(field.name == '🔒 Visibility' for field in embeds[0].fields)


def test_public_command_help_page_works_for_non_owners():
    embeds = _ask_help(is_owner=False, argument='openlobbies')
    assert embeds[0].title.endswith('!openlobbies')
