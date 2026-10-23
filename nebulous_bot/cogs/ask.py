"""`/ask`: sourced answers to NEBULOUS questions.

A thin adapter over the optional private `nebulous_ask` library, which owns the
knowledge corpus, retrieval, the Claude API call, the daily spend guard and the
answer log. This cog only handles Discord: who may ask where, rendering the
answer with its sources, and feedback buttons.

The cog registers only when the library is installed and configured
(`AskCog.unavailable_reason()` returns None); otherwise the bot runs exactly as
before. The library (and the anthropic SDK under it, ~50 MiB RSS) is imported
only when ASK_ENABLED is on, and then eagerly at module scope for the same
reason as cogs.formation: a deferred import on the production VM can stall the
event loop for minutes.
"""
import asyncio
import importlib
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

from nebulous_bot.config import Config

logger = logging.getLogger(__name__)

# Optional dependency: the private NebulousAsk library (vendor/ wheel).
nebulous_ask = None
if Config.ASK_ENABLED:
    try:
        nebulous_ask = importlib.import_module('nebulous_ask')
    except ImportError:
        logger.warning('ASK_ENABLED is on but the nebulous_ask library is not installed')

MAX_QUESTION_CHARS = 500
MAX_ANSWER_CHARS = 1800
MAX_SOURCES_SHOWN = 6
MAX_CONCURRENT_ANSWERS = 2
FEEDBACK_TIMEOUT_S = 14 * 60  # inside the 15-minute interaction-token lifetime, so the final edit works
_FIELD_LIMIT = 1024

TIER_BADGES = {
    'verified': '✅',
    'data': '📊',
    'community': '💬',
    'wiki': '📘',
}
TIER_LEGEND = '✅ verified mechanics · 📊 game data · 💬 community advice · 📘 wiki'

_LINK_LABEL_ESCAPE = str.maketrans({c: '\\' + c for c in '\\[]`*_~|'})


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + '…'


def ask_allowed(guild_id, channel_id, *, guild_ids, channel_ids, allow_dms):
    """May /ask run here? Fail closed: guilds must be allowlisted explicitly."""
    if guild_id is None:
        return allow_dms
    if guild_id not in guild_ids:
        return False
    return not channel_ids or channel_id in channel_ids


def format_sources(citations, limit=MAX_SOURCES_SHOWN):
    """Numbered source lines with tier badges; links where the source has a URL."""
    lines = []
    for cit in citations[:limit]:
        badge = TIER_BADGES.get(cit.tier, '•')
        label = cit.ref.translate(_LINK_LABEL_ESCAPE)
        lines.append(f'`[{cit.n}]` {badge} [{label}]({cit.url})' if cit.url else f'`[{cit.n}]` {badge} {label}')
    if len(citations) > limit:
        lines.append(f'…and {len(citations) - limit} more')
    return _truncate('\n'.join(lines), _FIELD_LIMIT)


def build_answer_embed(question, result):
    """The answer message for one AnswerResult."""
    embed = discord.Embed(
        title=_truncate(f'❓ {question}', 256),
        description=_truncate(result.text, MAX_ANSWER_CHARS),
        color=Config.EMBED_COLOR if result.status == 'answered' else Config.EMBED_COLOR_NO_SERVERS,
    )
    if result.citations:
        embed.add_field(name='Sources', value=format_sources(result.citations), inline=False)
    footer = f'AI answer for game {result.game_label}; it can be wrong. '
    footer += TIER_LEGEND if result.citations else 'No source covered this question.'
    embed.set_footer(text=_truncate(footer, 2048))
    return embed


class FeedbackView(discord.ui.View):
    """👍 / 👎 under an answer. Feedback feeds the offline review queue."""

    def __init__(self, answerer, log_id, asker_id):
        super().__init__(timeout=FEEDBACK_TIMEOUT_S)
        self.answerer = answerer
        self.log_id = log_id
        self.asker_id = asker_id
        self.voted = set()
        self.message = None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def _record(self, interaction, kind):
        if interaction.user.id in self.voted:
            await interaction.response.send_message('You already rated this answer.', ephemeral=True)
            return
        self.voted.add(interaction.user.id)
        await asyncio.to_thread(self.answerer.record_feedback, self.log_id, kind,
                                '' if interaction.user.id == self.asker_id else 'from another user')
        reply = 'Thanks!' if kind == 'up' else 'Thanks, this answer will be reviewed.'
        await interaction.response.send_message(reply, ephemeral=True)

    @discord.ui.button(emoji='👍', style=discord.ButtonStyle.secondary)
    async def thumbs_up(self, interaction, _button):
        await self._record(interaction, 'up')

    @discord.ui.button(emoji='👎', style=discord.ButtonStyle.secondary)
    async def thumbs_down(self, interaction, _button):
        await self._record(interaction, 'down')


class AskCog(commands.Cog, name='Ask'):
    """Ask NEBULOUS questions, answered with sources."""

    def __init__(self, bot, answerer=None):
        self.bot = bot
        self.answerer = answerer or self._load_answerer()
        self.slots = asyncio.Semaphore(MAX_CONCURRENT_ANSWERS)

    @staticmethod
    def unavailable_reason():
        """Why /ask can't run in this deployment, or None when it can."""
        if not Config.ASK_ENABLED:
            return 'ASK_ENABLED is off'
        if nebulous_ask is None:
            return 'the nebulous_ask library is not installed'
        if not Path(Config.ASK_CORPUS_PATH).is_file():
            return f'corpus not found at {Config.ASK_CORPUS_PATH}'
        if not Config.ANTHROPIC_API_KEY:
            return 'ANTHROPIC_API_KEY is not set'
        if not Config.ASK_GUILD_IDS and not Config.ASK_ALLOW_DMS:
            return 'no guild is allowlisted in ASK_GUILD_IDS'
        return None

    @staticmethod
    def _load_answerer():
        kwargs = {'daily_budget_usd': Config.ASK_DAILY_BUDGET_USD, 'log_path': Config.ASK_LOG_PATH,
                  'api_key': Config.ANTHROPIC_API_KEY}
        if Config.ASK_MODEL:
            kwargs['model'] = Config.ASK_MODEL
        return nebulous_ask.Answerer.load(Config.ASK_CORPUS_PATH, **kwargs)

    async def cog_load(self):
        self.purge_loop.start()

    async def cog_unload(self):
        self.purge_loop.cancel()

    @tasks.loop(hours=24)
    async def purge_loop(self):
        removed = await asyncio.to_thread(self.answerer.purge_log, Config.ASK_LOG_RETENTION_DAYS)
        if removed:
            logger.info('Purged %d /ask log rows older than %d days', removed, Config.ASK_LOG_RETENTION_DAYS)

    def _community_entries(self):
        """Vote-approved community advice (ca-*) from the advice cog, if loaded."""
        advice = self.bot.get_cog('Advice')
        if advice is None or not hasattr(advice, '_corpus'):
            return []
        return [e for e in advice._corpus() if str(e.get('id', '')).startswith('ca-')]

    @commands.hybrid_command(
        name='ask',
        description='Ask a NEBULOUS gameplay question and get an answer with sources.',
    )
    @commands.cooldown(3, 120, commands.BucketType.user)
    @app_commands.describe(question='Your question about NEBULOUS: Fleet Command')
    async def ask(self, ctx, *, question: str):
        """
        Ask a NEBULOUS question and get an answer with its sources.

        Answers come from verified game mechanics, stock game data, community
        advice and the wiki, in that order of trust. AI answers can be wrong:
        check the sources and rate the answer with 👍 / 👎.

        Usage: !ask <question>
        Examples: !ask how many FPAs should I fit with beam weapons?
        - !ask <question> - Answer one gameplay question with numbered sources
        """
        guild_id = ctx.guild.id if ctx.guild else None
        if not ask_allowed(guild_id, ctx.channel.id, guild_ids=Config.ASK_GUILD_IDS,
                           channel_ids=Config.ASK_CHANNEL_IDS, allow_dms=Config.ASK_ALLOW_DMS):
            await ctx.send('Questions are not enabled in this channel.', ephemeral=True)
            return
        question = (question or '').strip()
        if not question:
            await ctx.send('Ask a question, for example `/ask how far can an R550 see?`', ephemeral=True)
            return
        if len(question) > MAX_QUESTION_CHARS:
            await ctx.send(f'Please keep questions under {MAX_QUESTION_CHARS} characters.', ephemeral=True)
            return

        await ctx.defer()
        async with self.slots:
            result = await self.answerer.answer(
                question, extra_entries=self._community_entries(), asker_id=f'discord:{ctx.author.id}')

        none = discord.AllowedMentions.none()
        if result.status in ('budget', 'error', 'refused'):
            await ctx.send(result.text, allowed_mentions=none)
            return
        view = FeedbackView(self.answerer, result.log_id, ctx.author.id) if result.log_id else None
        message = await ctx.send(embed=build_answer_embed(question, result), view=view, allowed_mentions=none)
        if view is not None:
            view.message = message

    @commands.command(name='askstats', hidden=True)
    @commands.is_owner()
    async def askstats(self, ctx, days: int = 7):
        """Owner-only /ask usage: questions, spend, statuses and feedback."""
        summary = await asyncio.to_thread(self.answerer.usage_summary, max(1, min(days, 90)))
        lines = [f'**/ask, last {summary.get("days")} days**',
                 f'Questions: {summary.get("questions", 0)}',
                 f'Spend: ${summary.get("cost_usd", 0):.2f}',
                 f'Average latency: {summary.get("avg_latency_ms", 0) / 1000:.1f} s',
                 f'Statuses: {summary.get("statuses", {})}',
                 f'Feedback: {summary.get("feedback", {})}']
        await ctx.send('\n'.join(lines))
