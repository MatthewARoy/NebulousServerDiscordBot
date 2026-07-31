"""Community advice search and community-voted additions/removals.

Serves curated community knowledge (knowledge/entries/*.toml — see
docs/superpowers/specs/2026-07-13-community-knowledge-base-design.md)
via keyword/tag search, merged with community-submitted entries that
passed a 👍/👎 vote (AdviceProposal rows — see docs/superpowers/specs/
2026-07-30-advice-community-voting.md).

The curated corpus loads into memory at boot; community state loads in
cog_load. Ballots resolve in on_raw_reaction_add: a proposal needs
Config.ADVICE_VOTE_THRESHOLD votes and a strict majority to pass or
fail. Approved additions join the searchable pool as "ca-NNN" entries;
rejected additions and voted-out entries form the "incorrect" pool
(auditable via !advice list incorrect, excluded from search).
"""
import asyncio
import logging

import discord
from discord.ext import commands

from nebulous_bot.config import Config
from nebulous_bot import knowledge

logger = logging.getLogger(__name__)

MAX_RESULTS = 3
_FIELD_LIMIT = 1024  # Discord embed field value cap
_DESC_LIMIT = 4096   # Discord embed description cap
LIST_PAGE_SIZE = 15
ADVICE_MIN_LEN = 10
ADVICE_MAX_LEN = 300

_BALLOT_COLOR = 0xf1c40f  # amber: vote in progress


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + '…'


def validate_advice_text(text):
    """Return (cleaned_text, error_message); exactly one is None."""
    if not text or not text.strip():
        return None, "Tell me the advice: `!advice add <the advice>`."
    cleaned = ' '.join(text.split())
    if len(cleaned) < ADVICE_MIN_LEN:
        return None, f"That's a bit short — advice needs at least {ADVICE_MIN_LEN} characters."
    if len(cleaned) > ADVICE_MAX_LEN:
        return None, (
            f"That's too long ({len(cleaned)} chars, max {ADVICE_MAX_LEN}). "
            "Try splitting it into separate tips."
        )
    return cleaned, None


def _jump_url(guild_id, channel_id, message_id):
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


# --- sync ORM helpers (never called on the event loop directly) ----------

async def _db(fn, *args):
    from asgiref.sync import sync_to_async
    return await sync_to_async(fn)(*args)


def _load_community_state():
    """Returns (approved add rows, pending rows, removed entry ids)."""
    from nebulous_bot.models import AdviceProposal
    fields = ('pk', 'kind', 'advice_text', 'target_entry_id', 'author_id',
              'author_name', 'guild_id', 'channel_id', 'message_id')
    approved = list(
        AdviceProposal.objects
        .filter(kind=AdviceProposal.KIND_ADD, status=AdviceProposal.STATUS_APPROVED)
        .values(*fields)
    )
    pending = list(
        AdviceProposal.objects
        .filter(status=AdviceProposal.STATUS_PENDING)
        .values(*fields)
    )
    removed = list(
        AdviceProposal.objects
        .filter(kind=AdviceProposal.KIND_REMOVE, status=AdviceProposal.STATUS_APPROVED)
        .values_list('target_entry_id', flat=True)
    )
    return approved, pending, removed


def _create_proposal(**fields):
    from nebulous_bot.models import AdviceProposal
    row = AdviceProposal.objects.create(**fields)
    return {'pk': row.pk, 'kind': row.kind, 'advice_text': row.advice_text,
            'target_entry_id': row.target_entry_id, 'author_id': row.author_id,
            'author_name': row.author_name, 'guild_id': row.guild_id,
            'channel_id': row.channel_id, 'message_id': row.message_id}


def _claim_resolution(pk, status, up, down):
    """Atomically move a pending row to a final status. True if we won."""
    from django.utils import timezone
    from nebulous_bot.models import AdviceProposal
    return AdviceProposal.objects.filter(
        pk=pk, status=AdviceProposal.STATUS_PENDING,
    ).update(status=status, up_votes=up, down_votes=down, resolved_at=timezone.now()) == 1


def _mark_community_entry_removed(entry_pk):
    from nebulous_bot.models import AdviceProposal
    AdviceProposal.objects.filter(
        pk=entry_pk, kind=AdviceProposal.KIND_ADD,
    ).update(status=AdviceProposal.STATUS_REMOVED)


def _find_prior_verdict(text):
    """Has this exact advice already been voted incorrect? -> status or None."""
    from nebulous_bot.models import AdviceProposal
    row = (
        AdviceProposal.objects
        .filter(kind=AdviceProposal.KIND_ADD, advice_text__iexact=text,
                status__in=[AdviceProposal.STATUS_REJECTED, AdviceProposal.STATUS_REMOVED])
        .first()
    )
    return row.status if row else None


def _load_incorrect_pool():
    """Rows for `!advice list incorrect`: rejected adds + removed entries."""
    from nebulous_bot.models import AdviceProposal
    rejected = list(
        AdviceProposal.objects
        .filter(kind=AdviceProposal.KIND_ADD, status=AdviceProposal.STATUS_REJECTED)
        .values('advice_text', 'author_name', 'up_votes', 'down_votes')
    )
    removed_community = list(
        AdviceProposal.objects
        .filter(kind=AdviceProposal.KIND_ADD, status=AdviceProposal.STATUS_REMOVED)
        .values('pk', 'advice_text', 'author_name')
    )
    return rejected, removed_community


class AdviceCog(commands.Cog, name='Advice'):
    """Search community advice; propose additions and removals by vote."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Eager load at construction (boot time, before the gateway
        # connects) per house style. Corpus is tiny.
        self.entries = knowledge.load_entries()
        self.tags = knowledge.load_tags()
        # Community state, filled by cog_load from the DB:
        self.community = {}      # proposal pk -> entry dict (approved adds)
        self.removed_ids = set() # entry ids voted out of the pool
        self.pending = {}        # ballot message_id -> proposal row dict
        self._resolve_lock = asyncio.Lock()
        self._reconciled = False

    async def cog_load(self):
        approved, pending, removed = await _db(_load_community_state)
        for row in approved:
            self.community[row['pk']] = self._entry_from_row(row)
        self.pending = {row['message_id']: row for row in pending}
        self.removed_ids = set(removed)
        logger.info(
            "Advice KB loaded: %d curated, %d community, %d removed, %d ballots pending",
            len(self.entries), len(self.community), len(self.removed_ids), len(self.pending),
        )

    def _entry_from_row(self, row):
        return knowledge.community_entry(
            row['pk'], row['advice_text'], row['author_name'],
            source_url=_jump_url(row['guild_id'], row['channel_id'], row['message_id']),
        )

    def _corpus(self):
        return knowledge.active_entries(self.entries, self.community.values(), self.removed_ids)

    # --- search (unchanged behaviour) ------------------------------------

    @commands.group(name='advice', aliases=['tips', 'tip'], invoke_without_command=True)
    async def advice(self, ctx, *, query: str = None):
        """Search community advice, e.g. `!advice point defense`.

        Without a query (or with `tags`), lists the searchable topics.
        Subcommands: `add`, `remove`, `pending`, `list`.
        """
        corpus = self._corpus()
        if not corpus:
            await ctx.send("No advice loaded yet — the knowledge base is empty.")
            return
        if query is None or query.strip().lower() == 'tags':
            await ctx.send(embed=self._overview_embed(corpus))
            return

        results = knowledge.search(corpus, query, limit=MAX_RESULTS)
        if not results:
            embed = discord.Embed(
                title="🤷 No advice found",
                description=(
                    f"Nothing matched **{_truncate(query, 100)}**.\n"
                    f"Try one of the tags below, or `!advice` for an overview."
                ),
                color=Config.EMBED_COLOR_NO_SERVERS,
            )
            embed.add_field(
                name="Available tags",
                value=_truncate(', '.join(f'`{t}`' for t in sorted(self.tags)) or '*(none)*', _FIELD_LIMIT),
                inline=False,
            )
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title=f"📚 Community advice: {_truncate(query, 100)}",
            color=Config.EMBED_COLOR,
        )
        for entry in results:
            body = []
            if entry.get('situation'):
                body.append(f"*When:* {entry['situation']}")
            if entry.get('reason'):
                body.append(f"*Why:* {entry['reason']}")
            credit = entry.get('author', 'unknown')
            if entry.get('source_url'):
                body.append(f"— [{credit}]({entry['source_url']})")
            else:
                body.append(f"— {credit}")
            embed.add_field(
                name=_truncate(f"💡 {entry['rule']}", 256),
                value=_truncate('\n'.join(body), _FIELD_LIMIT),
                inline=False,
            )
        embed.set_footer(text="!advice tags for topics • !advice add <tip> to contribute")
        await ctx.send(embed=embed)

    def _overview_embed(self, corpus):
        categories = sorted({e['category'] for e in corpus})
        embed = discord.Embed(
            title="📚 Community advice",
            description=(
                f"{len(corpus)} tips from experienced players.\n"
                "Search with `!advice <words>`, e.g. `!advice missile defense`."
            ),
            color=Config.EMBED_COLOR,
        )
        embed.add_field(
            name="Categories",
            value=_truncate(', '.join(c.replace('-', ' ') for c in categories) or '*(none)*', _FIELD_LIMIT),
            inline=False,
        )
        embed.add_field(
            name="Tags",
            value=_truncate(', '.join(f'`{t}`' for t in sorted(self.tags)) or '*(none)*', _FIELD_LIMIT),
            inline=False,
        )
        embed.add_field(
            name="Contribute",
            value=(
                "`!advice add <tip>` — propose new advice (community votes 👍/👎)\n"
                "`!advice remove <id>` — propose removing wrong advice\n"
                "`!advice list` — audit the whole knowledge pool"
            ),
            inline=False,
        )
        return embed

    # --- proposals --------------------------------------------------------

    def _ballot_rules_text(self):
        t = Config.ADVICE_VOTE_THRESHOLD
        return (
            f"**{t}+ 👍** (more 👍 than 👎) → added to the knowledge pool.\n"
            f"**{t}+ 👎** (more 👎 than 👍) → recorded as incorrect."
        )

    @advice.command(name='add')
    @commands.guild_only()
    @commands.cooldown(2, 60, commands.BucketType.user)
    async def advice_add(self, ctx, *, text: str = None):
        """Propose new advice; the community votes it in with 👍.

        Example: `!advice add Radar jammers break missile lock but not beam lock`
        """
        cleaned, error = validate_advice_text(text)
        if error:
            await ctx.send(f"❌ {error}")
            return

        lowered = cleaned.lower()
        for entry in self._corpus():
            if entry.get('rule', '').lower() == lowered:
                await ctx.send(f"❌ That advice is already in the pool as `{entry['id']}`.")
                return
        for row in self.pending.values():
            if row['kind'] == 'add' and row['advice_text'].lower() == lowered:
                url = _jump_url(row['guild_id'], row['channel_id'], row['message_id'])
                await ctx.send(f"❌ That advice is already [up for a vote]({url}).")
                return
        if await _db(_find_prior_verdict, cleaned):
            await ctx.send(
                "❌ That exact advice was previously voted incorrect "
                "(see `!advice list incorrect`). Reword it if you think the vote got it wrong."
            )
            return

        embed = discord.Embed(
            title="🗳️ New advice proposed — vote!",
            description=f"> {cleaned}",
            color=_BALLOT_COLOR,
        )
        embed.add_field(name="Proposed by", value=ctx.author.mention, inline=False)
        related = knowledge.search(self._corpus(), cleaned, limit=1)
        if related:
            r = related[0]
            embed.add_field(
                name="Possibly related existing advice",
                value=_truncate(f"`{r['id']}` {r['rule']}", _FIELD_LIMIT),
                inline=False,
            )
        embed.add_field(name="How it works", value=self._ballot_rules_text(), inline=False)
        embed.set_footer(text="One vote per person — the bot's own reactions don't count.")
        message = await ctx.send(embed=embed)

        row = await _db(lambda: _create_proposal(
            kind='add', advice_text=cleaned,
            author_id=ctx.author.id, author_name=ctx.author.display_name,
            guild_id=ctx.guild.id, channel_id=ctx.channel.id, message_id=message.id,
        ))
        self.pending[message.id] = row
        await self._seed_reactions(message)

    @advice.command(name='remove')
    @commands.guild_only()
    @commands.cooldown(2, 60, commands.BucketType.user)
    async def advice_remove(self, ctx, entry_id: str = None):
        """Propose removing wrong advice by its id; the community votes.

        Find ids with `!advice list` or `!advice <search>`. Example:
        `!advice remove fb-003`
        """
        norm = knowledge.normalize_entry_id(entry_id or '')
        if not norm:
            await ctx.send(
                "❌ Give me an entry id, e.g. `!advice remove fb-003`. "
                "Ids are shown by `!advice list`."
            )
            return
        entry = next((e for e in self._corpus() if e['id'] == norm), None)
        if entry is None:
            await ctx.send(f"❌ No entry `{norm}` in the knowledge pool — check `!advice list`.")
            return
        for row in self.pending.values():
            if row['kind'] == 'remove' and row['target_entry_id'] == norm:
                url = _jump_url(row['guild_id'], row['channel_id'], row['message_id'])
                await ctx.send(f"❌ Removing `{norm}` is already [up for a vote]({url}).")
                return

        t = Config.ADVICE_VOTE_THRESHOLD
        embed = discord.Embed(
            title=f"🗳️ Removal proposed: {norm} — vote!",
            description=f"> {entry['rule']}\n— *{entry.get('author', 'unknown')}*",
            color=_BALLOT_COLOR,
        )
        embed.add_field(name="Proposed by", value=ctx.author.mention, inline=False)
        embed.add_field(
            name="How it works",
            value=(
                f"**{t}+ 👍** (more 👍 than 👎) → removed and recorded as incorrect.\n"
                f"**{t}+ 👎** (more 👎 than 👍) → the advice stays."
            ),
            inline=False,
        )
        embed.set_footer(text="One vote per person — the bot's own reactions don't count.")
        message = await ctx.send(embed=embed)

        row = await _db(lambda: _create_proposal(
            kind='remove', target_entry_id=norm,
            author_id=ctx.author.id, author_name=ctx.author.display_name,
            guild_id=ctx.guild.id, channel_id=ctx.channel.id, message_id=message.id,
        ))
        self.pending[message.id] = row
        await self._seed_reactions(message)

    async def _seed_reactions(self, message):
        try:
            await message.add_reaction(knowledge.UP_EMOJI)
            await message.add_reaction(knowledge.DOWN_EMOJI)
        except discord.HTTPException as e:
            # Voting still works with user-added reactions; count_votes only
            # discounts the bot's seeds when they actually exist.
            logger.warning("Could not seed ballot reactions on %s: %s", message.id, e)

    @advice.command(name='pending')
    async def advice_pending(self, ctx):
        """Show proposals currently up for a vote."""
        if not self.pending:
            await ctx.send("No advice votes are open right now. Start one with `!advice add <tip>`.")
            return
        lines = []
        for row in sorted(self.pending.values(), key=lambda r: r['pk']):
            url = _jump_url(row['guild_id'], row['channel_id'], row['message_id'])
            if row['kind'] == 'add':
                what = _truncate(row['advice_text'], 120)
                lines.append(f"➕ {what} — [vote here]({url})")
            else:
                lines.append(f"🗑️ remove `{row['target_entry_id']}` — [vote here]({url})")
        embed = discord.Embed(
            title=f"🗳️ Open advice votes ({len(lines)})",
            description=_truncate('\n'.join(lines), _DESC_LIMIT),
            color=_BALLOT_COLOR,
        )
        await ctx.send(embed=embed)

    # --- audit ------------------------------------------------------------

    @advice.command(name='list', aliases=['audit'])
    async def advice_list(self, ctx, section: str = None, page: int = 1):
        """Audit the knowledge pool.

        `!advice list` — summary. `!advice list <category|community|incorrect|all> [page]`
        — every entry with its id (for `!advice remove <id>`).
        """
        if section is None:
            await ctx.send(embed=await self._audit_summary_embed())
            return

        section = section.strip().lower()
        corpus = self._corpus()
        categories = {e['category'] for e in corpus}

        if section == 'incorrect':
            title = "🚫 Incorrect pool (voted wrong by the community)"
            lines = await self._incorrect_lines()
            empty = "Nothing has been voted incorrect yet."
        elif section == 'all' or section in categories:
            selected = corpus if section == 'all' else [e for e in corpus if e['category'] == section]
            title = f"📋 Knowledge pool — {section} ({len(selected)} entries)"
            lines = [
                _truncate(f"`{e['id']}` {e['rule']}", 150)
                for e in sorted(selected, key=lambda e: e['id'])
            ]
            empty = "No entries here yet."
        else:
            known = ', '.join(f'`{c}`' for c in sorted(categories))
            await ctx.send(
                f"❌ Unknown section `{_truncate(section, 50)}`. "
                f"Use `all`, `incorrect`, or a category: {known}."
            )
            return

        if not lines:
            await ctx.send(empty)
            return

        pages = max(1, -(-len(lines) // LIST_PAGE_SIZE))
        page = min(max(page, 1), pages)
        start = (page - 1) * LIST_PAGE_SIZE
        embed = discord.Embed(
            title=title,
            description=_truncate('\n'.join(lines[start:start + LIST_PAGE_SIZE]), _DESC_LIMIT),
            color=Config.EMBED_COLOR,
        )
        if pages > 1:
            embed.set_footer(text=f"Page {page}/{pages} • !advice list {section} {page + 1} for more")
        await ctx.send(embed=embed)

    async def _audit_summary_embed(self):
        corpus = self._corpus()
        by_category = {}
        for e in corpus:
            by_category[e['category']] = by_category.get(e['category'], 0) + 1
        rejected, removed_community = await _db(_load_incorrect_pool)
        incorrect_count = len(rejected) + len(removed_community) + \
            len([i for i in self.removed_ids if not i.startswith(knowledge.COMMUNITY_ID_PREFIX + '-')])
        cat_lines = '\n'.join(
            f"• `{cat}` — {count}" for cat, count in sorted(by_category.items())
        ) or '*(empty)*'
        embed = discord.Embed(
            title="📋 Knowledge pool audit",
            description=f"{len(corpus)} active entries.",
            color=Config.EMBED_COLOR,
        )
        embed.add_field(name="By category", value=_truncate(cat_lines, _FIELD_LIMIT), inline=False)
        embed.add_field(
            name="Other pools",
            value=(
                f"🚫 incorrect: {incorrect_count} (`!advice list incorrect`)\n"
                f"🗳️ open votes: {len(self.pending)} (`!advice pending`)"
            ),
            inline=False,
        )
        embed.set_footer(text="!advice list <category|community|incorrect|all> [page] for details")
        return embed

    async def _incorrect_lines(self):
        rejected, removed_community = await _db(_load_incorrect_pool)
        curated_by_id = {e['id']: e for e in self.entries}
        lines = []
        for entry_id in sorted(self.removed_ids):
            entry = curated_by_id.get(entry_id)
            if entry:
                lines.append(_truncate(f"`{entry_id}` {entry['rule']} *(removed by vote)*", 150))
        for row in removed_community:
            eid = knowledge.community_entry_id(row['pk'])
            lines.append(_truncate(f"`{eid}` {row['advice_text']} *(removed by vote)*", 150))
        for row in rejected:
            lines.append(_truncate(
                f"• {row['advice_text']} *(by {row['author_name']}, "
                f"voted down {row['down_votes']}👎/{row['up_votes']}👍)*", 150))
        return lines

    # --- ballot resolution ------------------------------------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) not in (knowledge.UP_EMOJI, knowledge.DOWN_EMOJI):
            return
        if payload.message_id not in self.pending:
            return
        try:
            await self._tally(payload.message_id)
        except Exception:
            logger.exception("Advice ballot tally failed for message %s", payload.message_id)

    @commands.Cog.listener()
    async def on_ready(self):
        """Re-tally ballots once per boot — votes cast while the bot was
        offline arrive as no event, so pending ballots are checked here."""
        if self._reconciled:
            return
        self._reconciled = True
        for message_id in list(self.pending):
            try:
                await self._tally(message_id)
            except Exception:
                logger.exception("Advice ballot reconciliation failed for message %s", message_id)

    async def _tally(self, message_id):
        row = self.pending.get(message_id)
        if row is None:
            return
        channel = self.bot.get_channel(row['channel_id'])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(row['channel_id'])
            except discord.HTTPException:
                logger.warning("Ballot channel %s unreachable; leaving ballot pending", row['channel_id'])
                return
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            await self._expire(row)
            return
        except discord.HTTPException as e:
            logger.warning("Could not fetch ballot %s: %s", message_id, e)
            return

        up, down = knowledge.count_votes(
            (str(r.emoji), r.count, r.me) for r in message.reactions
        )
        verdict = knowledge.resolve_votes(up, down, Config.ADVICE_VOTE_THRESHOLD)
        if verdict is None:
            return

        async with self._resolve_lock:
            if message_id not in self.pending:
                return  # a concurrent tally won
            status = 'approved' if verdict == 'approved' else 'rejected'
            claimed = await _db(_claim_resolution, row['pk'], status, up, down)
            del self.pending[message_id]
            if not claimed:
                return
            await self._apply_verdict(row, verdict, message, up, down)

    async def _expire(self, row):
        """Ballot message was deleted — void the vote."""
        from nebulous_bot.models import AdviceProposal
        await _db(_claim_resolution, row['pk'], AdviceProposal.STATUS_EXPIRED, 0, 0)
        self.pending.pop(row['message_id'], None)
        logger.info("Advice ballot %s (proposal %s) voided: message deleted",
                    row['message_id'], row['pk'])

    async def _apply_verdict(self, row, verdict, message, up, down):
        tally = f"👍 {up} · 👎 {down}"
        if row['kind'] == 'add':
            if verdict == 'approved':
                entry = self._entry_from_row(row)
                self.community[row['pk']] = entry
                embed = discord.Embed(
                    title="✅ Advice added to the knowledge pool",
                    description=f"> {row['advice_text']}",
                    color=Config.EMBED_COLOR,
                )
                embed.add_field(name="Entry id", value=f"`{entry['id']}`", inline=True)
            else:
                embed = discord.Embed(
                    title="❌ Voted incorrect — not added",
                    description=f"> {row['advice_text']}",
                    color=Config.EMBED_COLOR_NO_SERVERS,
                )
                embed.set_footer(text="Recorded in the incorrect pool — !advice list incorrect")
        else:
            target = row['target_entry_id']
            if verdict == 'approved':
                self.removed_ids.add(target)
                if target.startswith(knowledge.COMMUNITY_ID_PREFIX + '-'):
                    for pk, entry in list(self.community.items()):
                        if entry['id'] == target:
                            del self.community[pk]
                            await _db(_mark_community_entry_removed, pk)
                embed = discord.Embed(
                    title=f"🗑️ Removed from the knowledge pool: {target}",
                    description="The community voted this advice incorrect.",
                    color=Config.EMBED_COLOR_NO_SERVERS,
                )
                embed.set_footer(text="Recorded in the incorrect pool — !advice list incorrect")
            else:
                embed = discord.Embed(
                    title=f"✅ Removal declined: {target} stays",
                    description="The community voted to keep this advice.",
                    color=Config.EMBED_COLOR,
                )
        embed.add_field(name="Final tally", value=tally, inline=True)
        embed.add_field(name="Proposed by", value=row['author_name'], inline=True)
        try:
            await message.edit(embed=embed)
        except discord.HTTPException as e:
            logger.warning("Could not edit resolved ballot %s: %s", message.id, e)
        logger.info("Advice proposal %s (%s) resolved %s (%s)",
                    row['pk'], row['kind'], verdict, tally)
