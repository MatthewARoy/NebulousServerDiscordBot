"""Embed-based `!help` for the Nebulous bot.

discord.py's ``DefaultHelpCommand`` dumps every command into a single
plain-text code block: no colour, no usage, no examples, and the useful
arguments (``!listservers ptb``, ``!nextgame lobby``) stay hidden behind a
second command nobody runs. This module replaces it with three views:

* ``!help`` — one embed, commands grouped by category with a short blurb
* ``!help <category>`` — every command in that category, with usage/aliases
* ``!help <command>`` — summary, usage, examples, aliases and cooldown

Command help is generated from the docstrings the cogs already write
(``Usage:`` / ``Examples:`` lines, ``- !cmd ...`` bullets), so adding a
command needs no separate help table. All of that parsing lives in pure
module-scope helpers below so the tests can exercise it without a Bot, a
gateway connection or the ORM.
"""

from __future__ import annotations

import difflib
import inspect
import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

import discord
from discord.ext import commands

from nebulous_bot.config import Config

logger = logging.getLogger('nebulous_bot')

# Marks a hidden (bot-owner-only) command in the views only the owner sees.
OWNER_ONLY_MARKER = '🔒'

# Display order and decoration for the cogs, most player-facing first.
# Cogs missing from here still render — they sort to the end with the
# default emoji — so a new cog never disappears from the help menu.
CATEGORY_META = {
    'Servers': ('🚀', 'Browse live servers'),
    'Statistics': ('📊', 'Game history and trends'),
    'Next Game': ('🔔', 'Get pinged when a game is ready'),
    'Formation': ('🛠️', 'Fleet file tools'),
    'Advice': ('💡', 'Community knowledge base'),
    'Setup': ('⚙️', 'Per-guild configuration (admins)'),
    'Admin': ('🤖', 'Bot status and maintenance'),
    # Not a cog — the help command itself has no category.
    'Help': ('📖', 'This menu'),
}
DEFAULT_CATEGORY_EMOJI = '📁'
UNCATEGORIZED = 'Other'

# Discord hard limits (embed field value / field count).
FIELD_VALUE_LIMIT = 1024
FIELD_COUNT_LIMIT = 25
# Overview lines stay short so the menu reads as a scannable column.
SUMMARY_WIDTH = 66
CATEGORY_SUMMARY_WIDTH = 160


def category_emoji(name: str) -> str:
    """Emoji for a category (cog) name."""
    return CATEGORY_META.get(name, (DEFAULT_CATEGORY_EMOJI, ''))[0]


def category_blurb(name: str) -> str:
    """One-line description of a category, or '' if we have none."""
    return CATEGORY_META.get(name, ('', ''))[1]


def category_sort_key(name: str):
    """Sort known categories in CATEGORY_META order, unknown ones last."""
    order = list(CATEGORY_META)
    try:
        return (order.index(name), '')
    except ValueError:
        return (len(order), name.lower())


def truncate(text: str, width: int = SUMMARY_WIDTH) -> str:
    """Collapse whitespace and cut `text` to `width`, on a word boundary."""
    text = ' '.join((text or '').split())
    if len(text) <= width:
        return text
    cut = text[: width - 1].rstrip()
    if ' ' in cut:
        cut = cut[: cut.rfind(' ')]
    return cut.rstrip(' .,;:-—') + '…'


@dataclass
class HelpSections:
    """The parts of a command docstring the help embeds render separately."""

    summary: str = ''
    usage: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    details: List[str] = field(default_factory=list)


def split_examples(value: str, prefix: str = Config.COMMAND_PREFIX) -> List[str]:
    """Split a comma-joined `Examples:` line into individual examples.

    Only splits where the next fragment starts a new command, so
    "!formation 350, 500 or 800" stays one example.
    """
    parts = re.split(rf',\s*(?={re.escape(prefix)})', value.strip())
    return [part.strip() for part in parts if part.strip()]


def parse_help_sections(help_text: Optional[str], prefix: str = Config.COMMAND_PREFIX) -> HelpSections:
    """Split a command docstring into summary / usage / examples / details.

    Recognises the conventions the cogs already use::

        Summary line, possibly wrapped over a few lines.

        Usage: !cmd [args]
        Examples: !cmd a, !cmd b
        - !cmd a - what that does      <- example bullet
        - anything else                <- detail bullet

    A ``Usage:``/``Examples:`` header with nothing after the colon takes
    the indented lines that follow it (see `!graph`).
    """
    sections = HelpSections()
    if not help_text:
        return sections

    summary_lines: List[str] = []
    in_summary = True
    capture: Optional[str] = None

    for raw_line in inspect.cleandoc(help_text).splitlines():
        line = raw_line.strip()

        if not line:
            capture = None
            in_summary = False
            if sections.details and sections.details[-1]:
                sections.details.append('')
            continue

        lowered = line.lower()
        if lowered.startswith('usage:'):
            in_summary = False
            value = line.split(':', 1)[1].strip()
            if value:
                sections.usage.append(value)
                capture = None
            else:
                capture = 'usage'
            continue

        if lowered.startswith(('example:', 'examples:')):
            in_summary = False
            value = line.split(':', 1)[1].strip()
            if value:
                sections.examples.extend(split_examples(value, prefix))
                capture = None
            else:
                capture = 'examples'
            continue

        if capture == 'usage':
            sections.usage.append(line)
            continue
        if capture == 'examples':
            sections.examples.append(line)
            continue

        bullet = line[2:].strip() if line.startswith(('- ', '* ')) else None
        if bullet and bullet.startswith(prefix):
            in_summary = False
            sections.examples.append(bullet)
            continue

        if in_summary:
            summary_lines.append(line)
            continue

        sections.details.append(line)

    sections.summary = ' '.join(summary_lines).strip()
    while sections.details and not sections.details[-1]:
        sections.details.pop()
    return sections


def format_example(example: str, prefix: str = Config.COMMAND_PREFIX) -> str:
    """Render one example as `code` — note, splitting off a trailing note.

    Handles both conventions in the cogs: ``!cmd x  (a note)`` (two
    spaces) and ``!cmd x - a note`` (spaced dash). A lone flag like
    ``--skip`` is not a separator.
    """
    text = example.strip()
    match = re.match(r'^(.*?)(?:\s{2,}|\s+[-–—]\s+)(.+)$', text)
    if not match:
        return f'`{" ".join(text.split())}`'
    code = ' '.join(match.group(1).split())
    note = ' '.join(match.group(2).split())
    if note.startswith('(') and note.endswith(')'):
        note = note[1:-1].strip()
    return f'`{code}` — {note}' if note else f'`{code}`'


def format_cooldown(command: commands.Command) -> str:
    """Human-readable cooldown, e.g. '2 uses every 30s per user'."""
    cooldown = command.cooldown
    if cooldown is None:
        return ''
    rate = int(cooldown.rate)
    per = cooldown.per
    seconds = f'{per:g}s'
    bucket = getattr(getattr(command, '_buckets', None), 'type', None)
    scope = {
        commands.BucketType.user: ' per user',
        commands.BucketType.channel: ' per channel',
        commands.BucketType.guild: ' per server',
        commands.BucketType.member: ' per user',
        commands.BucketType.category: ' per category',
        commands.BucketType.role: ' per role',
    }.get(bucket, '')
    plural = '' if rate == 1 else 's'
    return f'{rate} use{plural} every {seconds}{scope}'


def chunk_lines(lines: Sequence[str], limit: int = FIELD_VALUE_LIMIT) -> List[str]:
    """Pack `lines` into embed-field-sized blocks without splitting a line."""
    chunks: List[str] = []
    current: List[str] = []
    length = 0
    for line in lines:
        if len(line) > limit:
            line = line[: limit - 1] + '…'
        added = len(line) + (1 if current else 0)
        if current and length + added > limit:
            chunks.append('\n'.join(current))
            current, length, added = [], 0, len(line)
        current.append(line)
        length += added
    if current:
        chunks.append('\n'.join(current))
    return chunks


def add_chunked_field(embed: discord.Embed, name: str, lines: Sequence[str], inline: bool = False) -> None:
    """Add `lines` as one field, spilling into '(cont.)' fields if needed."""
    for index, chunk in enumerate(chunk_lines(lines)):
        if len(embed.fields) >= FIELD_COUNT_LIMIT:
            return
        embed.add_field(name=name if index == 0 else f'{name} (cont.)', value=chunk, inline=inline)


class NebulousHelpCommand(commands.HelpCommand):
    """Category-grouped, embed-based help built from command docstrings."""

    def __init__(self, **options):
        options.setdefault(
            'command_attrs',
            {
                'aliases': ['commands'],
                'help': (
                    'Show this help menu.\n\n'
                    'Usage: !help [command|category]\n'
                    'Examples: !help listservers, !help Servers'
                ),
                'brief': 'Show the command menu',
            },
        )
        super().__init__(**options)

    # -- helpers ---------------------------------------------------------

    @property
    def prefix(self) -> str:
        return self.context.clean_prefix if self.context else Config.COMMAND_PREFIX

    def _is_help_command(self, command: commands.Command) -> bool:
        return command is getattr(self, '_command_impl', None)

    def _category_name(self, cog: Optional[commands.Cog]) -> str:
        return cog.qualified_name if cog else UNCATEGORIZED

    def _command_category(self, command: commands.Command) -> str:
        if self._is_help_command(command):
            return 'Help'
        return self._category_name(command.cog)

    def _default_usage(self, command: commands.Command) -> str:
        """Signature without the `[cmd|alias|alias]` pile — aliases get their own field."""
        return f'{self.prefix}{command.qualified_name} {command.signature}'.strip()

    def _base_embed(self, title: str, description: Optional[str] = None) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=Config.EMBED_COLOR)
        embed.set_footer(text=f'v{Config.VERSION} • {self.prefix}help <command> for usage and examples')
        return embed

    def _overview_line(self, command: commands.Command) -> str:
        # Hidden commands only reach here for the bot owner (see
        # prepare_help_command) — flag them so they read as owner-only.
        lock = f' {OWNER_ONLY_MARKER}' if command.hidden else ''
        return f'`{self.prefix}{command.name}` — {truncate(command.short_doc or "No description")}{lock}'

    def _resolve_category(self, query: str) -> Optional[commands.Cog]:
        """Find a cog by name, ignoring case and spaces ('nextgame' → 'Next Game')."""
        normalized = query.replace(' ', '').replace('-', '').replace('_', '').lower()
        for name, cog in self.context.bot.cogs.items():
            if name.replace(' ', '').lower() == normalized:
                return cog
        return None

    async def _suggestions(self, query: str) -> List[str]:
        """Close matches for a typo — only over commands the asker may see."""
        names = set()
        for command in await self.filter_commands(self.context.bot.commands):
            names.add(command.name)
            names.update(command.aliases)
        names.update(self.context.bot.cogs)
        return difflib.get_close_matches(query.lower(), sorted(names), n=3, cutoff=0.55)

    async def _is_visible(self, command: commands.Command) -> bool:
        """Whether this asker is allowed to see `command` exists at all.

        Delegates to filter_commands so one rule covers every view: hidden
        commands need show_hidden (owner-only, set in prepare_help_command)
        and every command's own checks must pass for the asker.
        """
        return bool(await self.filter_commands([command]))

    async def _visible_commands(self, command_iter: Iterable[commands.Command]) -> List[commands.Command]:
        filtered = await self.filter_commands(command_iter, sort=True)
        return [command for command in filtered if not self._is_help_command(command)]

    # -- dispatch --------------------------------------------------------

    async def prepare_help_command(self, ctx, command: Optional[str] = None, /):
        """Decide, per invocation, whether hidden commands may be revealed.

        `!commandlogs` is `hidden=True` + `@is_owner()` because it dumps
        cross-guild usage data; only the bot owner should learn it exists.
        discord.py hands each invocation its own copy of the help command
        (`HelpCommand.copy()`), so setting `show_hidden` here is per-asker,
        not global state.
        """
        await super().prepare_help_command(ctx, command)
        self.show_hidden = await self._is_bot_owner(ctx)

    async def _is_bot_owner(self, ctx) -> bool:
        try:
            return await ctx.bot.is_owner(ctx.author)
        except Exception as error:  # network hiccup fetching app info — fail closed
            logger.warning(f"Could not resolve bot owner for help visibility: {error}")
            return False

    async def command_callback(self, ctx, *, command: Optional[str] = None):
        """Accept `!help !stats` and case-insensitive category names."""
        if command:
            query = command.strip()
            if query.startswith(self.prefix):
                query = query[len(self.prefix):].strip()
            if query and ctx.bot.get_command(query) is None and ctx.bot.get_cog(query) is None:
                cog = self._resolve_category(query)
                if cog is not None:
                    await self.prepare_help_command(ctx, command)
                    return await self.send_cog_help(cog)
            command = query or None
        return await super().command_callback(ctx, command=command)

    async def send_bot_help(self, mapping):
        prefix = self.prefix
        embed = self._base_embed(
            '📖 Command Guide',
            (
                f'Live server tracking and stats for **{Config.GAME_NAME}**.\n'
                f'`{prefix}help <command>` for usage and examples • '
                f'`{prefix}help <category>` for everything in one group.'
            ),
        )

        groups = []
        for cog, cog_commands in mapping.items():
            visible = await self._visible_commands(cog_commands)
            if visible:
                groups.append((self._category_name(cog), visible))
        groups.sort(key=lambda group: category_sort_key(group[0]))

        if not groups:
            embed.description = 'No commands are available to you here.'
            return await self.get_destination().send(embed=embed)

        for name, group_commands in groups:
            blurb = category_blurb(name)
            lines = [f'*{blurb}*'] if blurb else []
            lines += [self._overview_line(command) for command in group_commands]
            add_chunked_field(embed, f'{category_emoji(name)} {name}', lines)

        await self.get_destination().send(embed=embed)

    async def send_cog_help(self, cog):
        prefix = self.prefix
        name = cog.qualified_name
        description = cog.description or category_blurb(name) or None
        embed = self._base_embed(f'{category_emoji(name)} {name}', description)

        visible = await self._visible_commands(cog.get_commands())
        if not visible:
            embed.description = 'No commands in this category are available to you here.'
            return await self.get_destination().send(embed=embed)

        for command in visible:
            sections = parse_help_sections(command.help, prefix)
            summary = truncate(sections.summary or command.short_doc or '', CATEGORY_SUMMARY_WIDTH)
            lines = [summary] if summary else []
            usage = sections.usage[0] if sections.usage else self._default_usage(command)
            lines.append(f'Usage: `{usage}`')
            if command.aliases:
                lines.append('Aliases: ' + ', '.join(f'`{prefix}{alias}`' for alias in sorted(command.aliases)))
            value = '\n'.join(lines)[:FIELD_VALUE_LIMIT]
            if len(embed.fields) >= FIELD_COUNT_LIMIT:
                break
            lock = f' {OWNER_ONLY_MARKER}' if command.hidden else ''
            embed.add_field(name=f'{prefix}{command.name}{lock}', value=value, inline=False)

        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command):
        # `!help <hidden command>` must not confirm the command exists to
        # someone who can't run it — answer exactly like an unknown name.
        if not await self._is_visible(command):
            return await self.send_error_message(await self.command_not_found(command.name))

        prefix = self.prefix
        sections = parse_help_sections(command.help, prefix)
        category = self._command_category(command)
        embed = self._base_embed(
            f'{category_emoji(category)} {prefix}{command.name}',
            sections.summary or command.short_doc or 'No description available.',
        )

        usage = sections.usage or [self._default_usage(command)]
        add_chunked_field(embed, '📋 Usage', [f'`{line}`' for line in usage])

        if sections.examples:
            add_chunked_field(embed, '💡 Examples', [format_example(line, prefix) for line in sections.examples])

        if sections.details:
            add_chunked_field(embed, '📝 Details', sections.details)

        if command.aliases:
            embed.add_field(
                name='🔁 Aliases',
                value=', '.join(f'`{prefix}{alias}`' for alias in sorted(command.aliases)),
                inline=False,
            )

        cooldown = format_cooldown(command)
        if cooldown:
            embed.add_field(name='⏳ Cooldown', value=cooldown, inline=False)

        if command.hidden:
            embed.add_field(
                name=f'{OWNER_ONLY_MARKER} Visibility',
                value='Bot owner only — hidden from everyone else\'s command list.',
                inline=False,
            )

        embed.set_footer(text=f'{category_emoji(category)} {category} • {prefix}help for the full command list')
        await self.get_destination().send(embed=embed)

    async def send_group_help(self, group):
        await self.send_command_help(group)

    # -- errors ----------------------------------------------------------

    async def command_not_found(self, string: str) -> str:
        message = f'No command or category called `{string}`.'
        suggestions = await self._suggestions(string)
        if suggestions:
            rendered = [
                f'`{name}` (category)' if name in self.context.bot.cogs else f'`{self.prefix}{name}`'
                for name in suggestions
            ]
            message += '\n\nDid you mean: ' + ', '.join(rendered)
        return message

    def subcommand_not_found(self, command, string: str) -> str:
        return f'`{self.prefix}{command.qualified_name}` has no subcommand called `{string}`.'

    async def send_error_message(self, error: str):
        embed = discord.Embed(
            title='❓ Not found',
            description=error,
            color=Config.EMBED_COLOR_NO_SERVERS,
        )
        embed.set_footer(text=f'{self.prefix}help lists every command')
        await self.get_destination().send(embed=embed)
