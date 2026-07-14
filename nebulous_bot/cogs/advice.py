"""Community advice search.

Serves curated community knowledge (knowledge/entries/*.toml — see
docs/superpowers/specs/2026-07-13-community-knowledge-base-design.md)
via keyword/tag search. The whole corpus loads into memory at boot;
it is a few hundred small text entries, so there is no DB and no index.
"""
import discord
from discord.ext import commands

from nebulous_bot.config import Config
from nebulous_bot import knowledge

MAX_RESULTS = 3
_FIELD_LIMIT = 1024  # Discord embed field value cap


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + '…'


class AdviceCog(commands.Cog, name='Advice'):
    """Search curated community advice from the knowledge base."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Eager load at construction (boot time, before the gateway
        # connects) per house style. Corpus is tiny.
        self.entries = knowledge.load_entries()
        self.tags = knowledge.load_tags()

    @commands.command(name='advice', aliases=['tips', 'tip'])
    async def advice(self, ctx, *, query: str = None):
        """Search community advice, e.g. `!advice point defense`.

        Without a query (or with `tags`), lists the searchable topics.
        """
        if not self.entries:
            await ctx.send("No advice loaded yet — the knowledge base is empty.")
            return
        if query is None or query.strip().lower() == 'tags':
            await ctx.send(embed=self._overview_embed())
            return

        results = knowledge.search(self.entries, query, limit=MAX_RESULTS)
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
        embed.set_footer(text="Advice curated from the community • !advice tags for topics")
        await ctx.send(embed=embed)

    def _overview_embed(self):
        categories = sorted({e['category'] for e in self.entries})
        embed = discord.Embed(
            title="📚 Community advice",
            description=(
                f"{len(self.entries)} curated tips from experienced players.\n"
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
        return embed
