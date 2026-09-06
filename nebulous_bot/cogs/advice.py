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
from discord import app_commands
from discord.ext import commands
from discord.utils import escape_markdown

from nebulous_bot.config import Config
from nebulous_bot import knowledge

logger = logging.getLogger(__name__)

MAX_RESULTS = 3
_FIELD_LIMIT = 1024  # Discord embed field value cap
_DESC_LIMIT = 4096   # Discord embed description cap
LIST_PAGE_SIZE = 15
ADVICE_MIN_LEN = 10
ADVICE_MAX_LEN = 300
MAX_OPEN_BALLOTS = 25  # bounds self.pending; deleting a ballot message voids it
MAX_OPEN_BALLOTS_PER_GUILD = 5  # no single server may starve the others
BALLOT_TTL_DAYS = 7  # a vote nobody settles must not hold a slot forever

_BALLOT_COLOR = 0xf1c40f  # amber: vote in progress
_BALLOT_FOOTER = (
    "One vote per person — reacting with both 👍 and 👎 cancels your vote, "
    "and the bot's own reactions don't count."
)


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + '…'


# discord.py's escape_markdown leaves bare brackets alone, so a display name
# containing "](" hijacks the masked link it is rendered inside. Labels get
# their own pass; plain text uses escape_markdown.
_LINK_LABEL_ESCAPE = str.maketrans({c: '\\' + c for c in '\\[]`*_~|'})


def _link_label(text):
    """Escape user-supplied text used as the label of a [label](url) link."""
    return text.translate(_LINK_LABEL_ESCAPE)


def format_result_field(entry):
    """Render one search hit as an embed (field name, field value) pair.

    Every hit carries its id, because `!advice remove <id>` tells people to
    find ids here. Author names and community rule text are user-supplied,
    so they are escaped before reaching a markdown-parsed value; curated
    text contains no markdown, so escaping leaves it untouched.
    """
    body = []
    if entry.get('situation'):
        body.append(f"*When:* {escape_markdown(entry['situation'])}")
    if entry.get('reason'):
        body.append(f"*Why:* {escape_markdown(entry['reason'])}")
    credit = entry.get('author', 'unknown')
    if entry.get('source_url'):
        attribution = f"— [{_link_label(credit)}]({entry['source_url']})"
    else:
        attribution = f"— {escape_markdown(credit)}"
    if entry.get('id'):
        attribution += f" · `{entry['id']}`"
    body.append(attribution)
    name = _truncate(f"💡{knowledge.entry_badges(entry)} {entry.get('rule', '')}", 256)
    return name, _truncate('\n'.join(body), _FIELD_LIMIT)


def find_existing_advice(entries, community, text):
    """The pool entry whose rule is exactly `text`, or None.

    Curated entries match even while tombstoned: re-proposing a voted-out
    entry's exact words would mint a ca-* copy stripped of the situation,
    reason, tags and original source the curated entry carried.
    """
    lowered = ' '.join(text.split()).lower()
    for entry in list(entries) + list(community):
        if entry.get('rule', '').lower() == lowered:
            return entry
    return None


def validate_advice_text(text):
    """Return (cleaned_text, error_message); exactly one is None."""
    if not text or not text.strip():
        return None, "Tell me the advice: use `/advice add` and enter the tip."
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


def _expire_stale_ballots(ttl_days):
    """Void ballots older than the TTL; returns their message ids.

    Deleting the ballot message was the only way to void a vote, and the
    message belongs to the bot, so a guild without a moderator could not
    clear one at all. Stale ballots then held open-vote slots forever.
    """
    from datetime import timedelta

    from django.utils import timezone
    from nebulous_bot.models import AdviceProposal
    stale = AdviceProposal.objects.filter(
        status=AdviceProposal.STATUS_PENDING,
        created_at__lt=timezone.now() - timedelta(days=ttl_days),
    )
    message_ids = list(stale.values_list('message_id', flat=True))
    if message_ids:
        stale.update(status=AdviceProposal.STATUS_EXPIRED, resolved_at=timezone.now())
    return message_ids


def _restore_entry(entry_id, community_pk):
    """Undo an approved removal. Returns (overturned ballots, add row).

    The removal ballots move to 'rejected', the end state a declined
    removal leaves; their recorded tallies are untouched, so the vote
    itself stays auditable. A dedicated 'overturned' status would need a
    migration, and phase 4 already plans that batch.
    """
    from nebulous_bot.models import AdviceProposal
    ballots = list(
        AdviceProposal.objects
        .filter(kind=AdviceProposal.KIND_REMOVE, target_entry_id=entry_id,
                status=AdviceProposal.STATUS_APPROVED)
        .values('pk', 'up_votes', 'down_votes')
    )
    if ballots:
        AdviceProposal.objects.filter(pk__in=[b['pk'] for b in ballots]).update(
            status=AdviceProposal.STATUS_REJECTED)
    row = None
    if community_pk is not None:
        AdviceProposal.objects.filter(
            pk=community_pk, kind=AdviceProposal.KIND_ADD,
            status=AdviceProposal.STATUS_REMOVED,
        ).update(status=AdviceProposal.STATUS_APPROVED)
        row = (
            AdviceProposal.objects
            .filter(pk=community_pk, kind=AdviceProposal.KIND_ADD,
                    status=AdviceProposal.STATUS_APPROVED)
            .values('pk', 'kind', 'advice_text', 'target_entry_id', 'author_id',
                    'author_name', 'guild_id', 'channel_id', 'message_id')
            .first()
        )
    return ballots, row


def _load_community_state(ttl_days):
    """Returns (approved add rows, pending rows, removed entry ids).

    Sweeps ballots past the TTL first, so a restart never reinstates a
    dead vote into the open-ballot budget.
    """
    from nebulous_bot.models import AdviceProposal
    _expire_stale_ballots(ttl_days)
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
        # Catalog aliases feed search as synonym expansion ("FPA" scores
        # as "focused particle accelerator"). Loaded once at boot like
        # the corpus; an absent catalog degrades to no expansion.
        self.expansions = knowledge.alias_expansions(knowledge.load_catalog())
        # Community state, filled by cog_load from the DB:
        self.community = {}      # proposal pk -> entry dict (approved adds)
        self.removed_ids = set() # entry ids voted out of the pool
        self.pending = {}        # ballot message_id -> proposal row dict
        self._resolve_lock = asyncio.Lock()
        self._propose_lock = asyncio.Lock()  # serializes dup-check -> create

    async def cog_load(self):
        approved, pending, removed = await _db(_load_community_state, BALLOT_TTL_DAYS)
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

    def _at_capacity(self, guild_id):
        mine = sum(1 for r in self.pending.values() if r['guild_id'] == guild_id)
        return mine >= MAX_OPEN_BALLOTS_PER_GUILD or len(self.pending) >= MAX_OPEN_BALLOTS

    async def _sweep_stale_ballots(self):
        expired = await _db(_expire_stale_ballots, BALLOT_TTL_DAYS)
        for message_id in expired:
            self.pending.pop(message_id, None)
        if expired:
            logger.info("Expired %d advice ballots older than %d days",
                        len(expired), BALLOT_TTL_DAYS)

    async def _ballot_slot_taken(self, ctx):
        """True (having said so) when this guild may not open another vote.

        Two caps: a per-guild share so one server cannot starve the rest,
        and the global bound on self.pending. Both sweep expired ballots
        before refusing, so the budget always frees itself.
        """
        if self._at_capacity(ctx.guild.id):
            await self._sweep_stale_ballots()
        if not self._at_capacity(ctx.guild.id):
            return False
        mine = sum(1 for r in self.pending.values() if r['guild_id'] == ctx.guild.id)
        if mine >= MAX_OPEN_BALLOTS_PER_GUILD:
            await ctx.send(
                f"❌ This server already has {mine} open votes — settle some first "
                f"(`/advice pending`). Votes expire on their own after {BALLOT_TTL_DAYS} days."
            )
        else:
            await ctx.send(
                f"❌ There are already {len(self.pending)} open votes across all servers "
                "— try again shortly (`/advice pending`)."
            )
        return True

    # --- search (unchanged behaviour) ------------------------------------

    @commands.hybrid_group(
        name='advice',
        aliases=['tips', 'tip'],
        fallback='search',
        description='Search community-authored NEBULOUS gameplay advice.',
    )
    @app_commands.describe(query='Words or topic tags to search for')
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

        results = knowledge.search(corpus, query, limit=MAX_RESULTS,
                                   expansions=self.expansions)
        if not results:
            embed = discord.Embed(
                title="🤷 No advice found",
                description=(
                    f"Nothing matched **{_truncate(query, 100)}**.\n"
                    f"Try one of the tags below, or `/advice search` for an overview."
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
        any_badges = ''
        for entry in results:
            any_badges += knowledge.entry_badges(entry)
            name, value = format_result_field(entry)
            embed.add_field(name=name, value=value, inline=False)
        legend = []
        if knowledge.BADGE_CONTESTED in any_badges:
            legend.append(f"{knowledge.BADGE_CONTESTED} contested")
        if knowledge.BADGE_PATCH_SENSITIVE in any_badges:
            legend.append(f"{knowledge.BADGE_PATCH_SENSITIVE} balance-dependent")
        footer = "/advice search tags for topics • /advice add to contribute"
        if legend:
            footer = ' · '.join(legend) + " • " + footer
        embed.set_footer(text=footer)
        await ctx.send(embed=embed)

    def _overview_embed(self, corpus):
        categories = sorted({e['category'] for e in corpus})
        embed = discord.Embed(
            title="📚 Community advice",
            description=(
                f"{len(corpus)} tips from experienced players.\n"
                "Search with `/advice search`, e.g. query `missile defense`."
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
                "`/advice add` — propose new advice (community votes 👍/👎)\n"
                "`/advice remove` — propose removing wrong advice\n"
                "`/advice list` — audit the whole knowledge pool"
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

    @advice.command(name='add', description='Propose new advice for a community vote.')
    @app_commands.describe(text='The gameplay advice to propose')
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

        await ctx.defer()

        # The lock serializes duplicate-check -> create, so two simultaneous
        # proposals of the same text can't both pass the checks.
        async with self._propose_lock:
            if await self._ballot_slot_taken(ctx):
                return
            lowered = cleaned.lower()
            existing = find_existing_advice(self.entries, self.community.values(), cleaned)
            if existing is not None:
                if existing['id'] in self.removed_ids:
                    await ctx.send(
                        f"❌ `{existing['id']}` was voted out of the pool. Re-adding the same "
                        "words would lose the context it carried — reword it, or ask the "
                        "bot owner to restore the entry."
                    )
                else:
                    await ctx.send(f"❌ That advice is already in the pool as `{existing['id']}`.")
                return
            for row in self.pending.values():
                if row['kind'] == 'add' and row['advice_text'].lower() == lowered:
                    url = _jump_url(row['guild_id'], row['channel_id'], row['message_id'])
                    await ctx.send(f"❌ That advice is already [up for a vote]({url}).")
                    return
            if await _db(_find_prior_verdict, cleaned):
                await ctx.send(
                    "❌ That exact advice was previously voted incorrect "
                    "(see `/advice list` with section `incorrect`). Reword it if needed."
                )
                return

            embed = discord.Embed(
                title="🗳️ New advice proposed — vote!",
                description=f"> {escape_markdown(cleaned)}",
                color=_BALLOT_COLOR,
            )
            embed.add_field(name="Proposed by", value=ctx.author.mention, inline=False)
            related = knowledge.search(self._corpus(), cleaned, limit=1,
                                       expansions=self.expansions)
            if related:
                r = related[0]
                embed.add_field(
                    name="Possibly related existing advice",
                    value=_truncate(f"`{r['id']}` {escape_markdown(r['rule'])}", _FIELD_LIMIT),
                    inline=False,
                )
            embed.add_field(name="How it works", value=self._ballot_rules_text(), inline=False)
            embed.set_footer(text=_BALLOT_FOOTER)
            message = await ctx.send(embed=embed)

            row = await _db(lambda: _create_proposal(
                kind='add', advice_text=cleaned,
                author_id=ctx.author.id, author_name=ctx.author.display_name,
                guild_id=ctx.guild.id, channel_id=ctx.channel.id, message_id=message.id,
            ))
            self.pending[message.id] = row
        await self._seed_reactions(message)
        # Catch reactions that landed before the ballot was registered above.
        await self._tally(message.id)

    @advice.command(name='remove', description='Propose removing an advice entry by ID.')
    @app_commands.describe(entry_id='Advice entry ID, such as fb-003')
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
                "❌ Give me an entry id, e.g. `fb-003` in `/advice remove`. "
                "Ids are shown by `/advice list`."
            )
            return
        await ctx.defer()
        async with self._propose_lock:
            if await self._ballot_slot_taken(ctx):
                return
            entry = next((e for e in self._corpus() if e['id'] == norm), None)
            if entry is None:
                await ctx.send(f"❌ No entry `{norm}` in the knowledge pool — check `/advice list`.")
                return
            for row in self.pending.values():
                if row['kind'] == 'remove' and row['target_entry_id'] == norm:
                    url = _jump_url(row['guild_id'], row['channel_id'], row['message_id'])
                    await ctx.send(f"❌ Removing `{norm}` is already [up for a vote]({url}).")
                    return

            t = Config.ADVICE_VOTE_THRESHOLD
            embed = discord.Embed(
                title=f"🗳️ Removal proposed: {norm} — vote!",
                description=_truncate(
                    f"> {escape_markdown(entry['rule'])}\n"
                    f"— *{escape_markdown(entry.get('author', 'unknown'))}*", _DESC_LIMIT),
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
            embed.set_footer(text=_BALLOT_FOOTER)
            message = await ctx.send(embed=embed)

            row = await _db(lambda: _create_proposal(
                kind='remove', target_entry_id=norm,
                author_id=ctx.author.id, author_name=ctx.author.display_name,
                guild_id=ctx.guild.id, channel_id=ctx.channel.id, message_id=message.id,
            ))
            self.pending[message.id] = row
        await self._seed_reactions(message)
        # Catch reactions that landed before the ballot was registered above.
        await self._tally(message.id)

    async def _seed_reactions(self, message):
        try:
            await message.add_reaction(knowledge.UP_EMOJI)
            await message.add_reaction(knowledge.DOWN_EMOJI)
        except discord.HTTPException as e:
            # Voting still works with user-added reactions; count_votes only
            # discounts the bot's seeds when they actually exist.
            logger.warning("Could not seed ballot reactions on %s: %s", message.id, e)

    @advice.command(name='restore', hidden=True, with_app_command=False)
    @commands.is_owner()
    async def advice_restore(self, ctx, entry_id: str = None):
        """Put a voted-out entry back in the knowledge pool (bot owner only).

        A removal vote is global and permanent otherwise; this is the only
        way back. Example: `!advice restore fb-001`
        """
        norm = knowledge.normalize_entry_id(entry_id or '')
        if not norm or norm not in self.removed_ids:
            shown = norm or _truncate(entry_id or '?', 50)
            await ctx.send(
                f"❌ Nothing is tombstoned under `{shown}` — see `/advice list` with `incorrect`."
            )
            return
        ballots, row = await _db(_restore_entry, norm, knowledge.community_entry_pk(norm))
        self.removed_ids.discard(norm)
        if row:
            self.community[row['pk']] = self._entry_from_row(row)
        entry = next((e for e in self._corpus() if e['id'] == norm), None)
        if entry:
            description = _truncate(f"> {escape_markdown(entry['rule'])}", _DESC_LIMIT)
        else:
            description = ("The tombstone is cleared, but no entry with that id is loaded "
                           "any more — it is gone from the knowledge files.")
        embed = discord.Embed(
            title=f"♻️ Restored to the knowledge pool: {norm}",
            description=description,
            color=Config.EMBED_COLOR,
        )
        embed.add_field(
            name="Removal ballots overturned",
            value=', '.join(f"👍 {b['up_votes']} · 👎 {b['down_votes']}" for b in ballots) or 'none',
            inline=False,
        )
        await ctx.send(embed=embed)
        logger.info("Advice entry %s restored by user %s, overturning %d removal ballots",
                    norm, ctx.author.id, len(ballots))

    @advice.command(name='pending', description='Show advice proposals currently open for voting.')
    async def advice_pending(self, ctx):
        """Show proposals currently up for a vote."""
        # Other guilds' ballots are not listed: their jump links would go
        # nowhere for anyone here, and their votes are not this server's
        # business.
        guild_id = ctx.guild.id if ctx.guild else 0
        here = [r for r in self.pending.values() if r['guild_id'] == guild_id]
        if not here:
            await ctx.send("No advice votes are open right now. Start one with `/advice add`.")
            return
        lines = []
        for row in sorted(here, key=lambda r: r['pk']):
            url = _jump_url(row['guild_id'], row['channel_id'], row['message_id'])
            if row['kind'] == 'add':
                what = escape_markdown(_truncate(row['advice_text'], 120))
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

    @advice.command(name='list', aliases=['audit'], description='Browse or audit the advice pool.')
    @app_commands.describe(
        section='Category, community, incorrect, or all',
        page='Page number to display',
    )
    async def advice_list(self, ctx, section: str = None, page: int = 1):
        """Audit the knowledge pool.

        `!advice list` — summary. `!advice list <category|community|incorrect|all> [page]`
        — every entry with its id (for `!advice remove <id>`).
        """
        await ctx.defer()
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
                _truncate(f"`{e['id']}` {escape_markdown(e['rule'])}", 150)
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
            embed.set_footer(text=f"Page {page}/{pages} • use /advice list for page {page + 1}")
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
                f"🚫 incorrect: {incorrect_count} (`/advice list`)\n"
                f"🗳️ open votes: {len(self.pending)} (`/advice pending`)"
            ),
            inline=False,
        )
        embed.set_footer(text="Use /advice list with a section and page for details")
        return embed

    async def _incorrect_lines(self):
        rejected, removed_community = await _db(_load_incorrect_pool)
        curated_by_id = {e['id']: e for e in self.entries}
        lines = []
        for entry_id in sorted(self.removed_ids):
            entry = curated_by_id.get(entry_id)
            if entry:
                lines.append(_truncate(
                    f"`{entry_id}` {escape_markdown(entry['rule'])} *(removed by vote)*", 150))
        for row in removed_community:
            eid = knowledge.community_entry_id(row['pk'])
            lines.append(_truncate(
                f"`{eid}` {escape_markdown(row['advice_text'])} *(removed by vote)*", 150))
        for row in rejected:
            lines.append(_truncate(
                f"• {escape_markdown(row['advice_text'])} *(by {escape_markdown(row['author_name'])}, "
                f"voted down {row['down_votes']}👎/{row['up_votes']}👍)*", 150))
        return lines

    # --- ballot resolution ------------------------------------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self._vote_changed(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """Withdrawing a vote can settle a ballot too: a tie stays open by
        design, so 5-5 waits for someone to pull a vote, and that is not an
        added reaction."""
        await self._vote_changed(payload)

    async def _vote_changed(self, payload):
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
    async def on_raw_message_delete(self, payload):
        """Deleting a ballot message cancels its vote."""
        row = self.pending.get(payload.message_id)
        if row is not None:
            await self._expire(row)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        for message_id in payload.message_ids:
            row = self.pending.get(message_id)
            if row is not None:
                await self._expire(row)

    @commands.Cog.listener()
    async def on_ready(self):
        """Re-tally open ballots on every connect — votes cast while the
        bot was away arrive as no event, and a reconnect leaves the same gap
        a restart does. Bounded by MAX_OPEN_BALLOTS."""
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

        # Per-user tally: fetch the actual voter lists so one person reacting
        # with both emoji cancels out instead of counting twice.
        up_ids, down_ids = [], []
        for reaction in message.reactions:
            emoji = str(reaction.emoji)
            if emoji == knowledge.UP_EMOJI:
                up_ids = [u.id async for u in reaction.users()]
            elif emoji == knowledge.DOWN_EMOJI:
                down_ids = [u.id async for u in reaction.users()]
        up, down = knowledge.tally_voters(up_ids, down_ids, exclude=(self.bot.user.id,))
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
                    description=f"> {escape_markdown(row['advice_text'])}",
                    color=Config.EMBED_COLOR,
                )
                embed.add_field(name="Entry id", value=f"`{entry['id']}`", inline=True)
            else:
                embed = discord.Embed(
                    title="❌ Voted incorrect — not added",
                    description=f"> {escape_markdown(row['advice_text'])}",
                    color=Config.EMBED_COLOR_NO_SERVERS,
                )
                embed.set_footer(text="Recorded in the incorrect pool — /advice list section:incorrect")
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
                embed.set_footer(text="Recorded in the incorrect pool — /advice list section:incorrect")
            else:
                embed = discord.Embed(
                    title=f"✅ Removal declined: {target} stays",
                    description="The community voted to keep this advice.",
                    color=Config.EMBED_COLOR,
                )
        embed.add_field(name="Final tally", value=tally, inline=True)
        embed.add_field(name="Proposed by", value=escape_markdown(row['author_name']), inline=True)
        try:
            await message.edit(embed=embed)
        except discord.HTTPException as e:
            logger.warning("Could not edit resolved ballot %s: %s", message.id, e)
        logger.info("Advice proposal %s (%s) resolved %s (%s)",
                    row['pk'], row['kind'], verdict, tally)
