import asyncio
from types import SimpleNamespace as NS

import discord
from discord.ext import commands

from nebulous_bot.cogs import ask as ask_module
from nebulous_bot.cogs.ask import (AskCog, ask_allowed, build_answer_embed, format_sources,
                                   MAX_QUESTION_CHARS)
from nebulous_bot.config import Config


def cit(n, tier, ref, url=''):
    return NS(n=n, tier=tier, ref=ref, url=url)


def result(status='answered', citations=None, text='Take at least two FPAs. [1]', log_id=7):
    return NS(text=text, status=status, citations=citations or [], game_label='0.6.2.6 (test)',
              log_id=log_id)


class FakeAnswerer:
    def __init__(self, res):
        self.res = res
        self.calls = []

    async def answer(self, question, **kwargs):
        self.calls.append((question, kwargs))
        return self.res

    def record_feedback(self, *args):
        pass

    def purge_log(self, days):
        return 0

    def usage_summary(self, days=7):
        return {'days': days, 'questions': 3, 'cost_usd': 0.06, 'avg_latency_ms': 4200,
                'statuses': {'answered': 3}, 'feedback': {}}


class FakeCtx:
    def __init__(self, guild_id=1, channel_id=10, author_id=99):
        self.guild = NS(id=guild_id) if guild_id else None
        self.channel = NS(id=channel_id)
        self.author = NS(id=author_id)
        self.sent = []
        self.deferred = False

    async def defer(self):
        self.deferred = True

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


def make_cog(res, monkeypatch, *, guilds=frozenset({1}), channels=frozenset(), dms=False):
    monkeypatch.setattr(Config, 'ASK_GUILD_IDS', guilds)
    monkeypatch.setattr(Config, 'ASK_CHANNEL_IDS', channels)
    monkeypatch.setattr(Config, 'ASK_ALLOW_DMS', dms)
    answerer = FakeAnswerer(res)
    bot = NS(get_cog=lambda name: None)
    return AskCog(bot, answerer=answerer), answerer


def run(cog, ctx, question):
    asyncio.run(AskCog.ask.callback(cog, ctx, question=question))


def test_ask_is_hybrid_with_cooldown_and_askstats_is_hidden():
    by_name = {c.name: c for c in AskCog.__cog_commands__}
    assert isinstance(by_name['ask'], commands.HybridCommand)
    assert by_name['ask'].app_command is not None
    assert by_name['ask'].app_command.description
    assert by_name['ask']._buckets._cooldown.rate == 3
    assert type(by_name['askstats']) is commands.Command
    assert by_name['askstats'].hidden is True


def test_ask_allowed_fails_closed():
    allowed = dict(guild_ids=frozenset({1}), channel_ids=frozenset(), allow_dms=False)
    assert ask_allowed(1, 10, **allowed)
    assert not ask_allowed(2, 10, **allowed)
    assert not ask_allowed(None, 10, **allowed)
    assert ask_allowed(None, 10, guild_ids=frozenset(), channel_ids=frozenset(), allow_dms=True)
    assert not ask_allowed(1, 11, guild_ids=frozenset({1}), channel_ids=frozenset({10}), allow_dms=False)


def test_sources_link_urls_and_escape_labels():
    text = format_sources([cit(1, 'wiki', 'Wiki: Ship:raines', 'https://wiki.example/Ship:raines#Armor'),
                           cit(2, 'community', 'Community advice [fb-001]')])
    assert '`[1]` 📘 [Wiki: Ship:raines](https://wiki.example/Ship:raines#Armor)' in text
    assert '`[2]` 💬 Community advice \\[fb-001\\]' in text


def test_sources_are_capped():
    text = format_sources([cit(i, 'data', f'Game data {i}') for i in range(1, 10)], limit=3)
    assert '…and 6 more' in text


def test_answer_embed_has_sources_and_disclaimer():
    embed = build_answer_embed('How many FPAs?', result(citations=[cit(1, 'community', 'Community advice fb-001')]))
    assert embed.description.startswith('Take at least two FPAs.')
    assert embed.fields[0].name == 'Sources'
    assert 'it can be wrong' in embed.footer.text
    assert embed.color.value == Config.EMBED_COLOR


def test_unknown_answer_embed_says_no_source():
    embed = build_answer_embed('pizza?', result(status='unknown', text="I don't know."))
    assert not embed.fields
    assert 'No source covered' in embed.footer.text


def test_ask_flow_sends_embed_with_feedback(monkeypatch):
    cog, answerer = make_cog(result(citations=[cit(1, 'data', 'Game data: Raines Frigate')]), monkeypatch)
    ctx = FakeCtx()
    run(cog, ctx, 'raines top speed?')
    assert ctx.deferred
    content, kwargs = ctx.sent[-1]
    assert isinstance(kwargs['embed'], discord.Embed)
    assert kwargs['view'] is not None
    assert kwargs['allowed_mentions'].everyone is False
    assert answerer.calls[0][1]['asker_id'] == 'discord:99'


def test_ask_rejected_outside_allowlist(monkeypatch):
    cog, answerer = make_cog(result(), monkeypatch)
    ctx = FakeCtx(guild_id=2)
    run(cog, ctx, 'raines?')
    assert answerer.calls == []
    assert 'not enabled' in ctx.sent[0][0]


def test_ask_rejects_long_questions(monkeypatch):
    cog, answerer = make_cog(result(), monkeypatch)
    ctx = FakeCtx()
    run(cog, ctx, 'x' * (MAX_QUESTION_CHARS + 1))
    assert answerer.calls == []


def test_budget_status_is_plain_text(monkeypatch):
    cog, _ = make_cog(result(status='budget', text='The daily question budget has been reached.'), monkeypatch)
    ctx = FakeCtx()
    run(cog, ctx, 'raines?')
    assert ctx.sent[-1][0].startswith('The daily question budget')
    assert 'embed' not in ctx.sent[-1][1]


def test_unavailable_reason(monkeypatch):
    monkeypatch.setattr(Config, 'ASK_ENABLED', False)
    assert AskCog.unavailable_reason() == 'ASK_ENABLED is off'
    monkeypatch.setattr(Config, 'ASK_ENABLED', True)
    monkeypatch.setattr(ask_module, 'nebulous_ask', None)
    assert 'not installed' in AskCog.unavailable_reason()


def test_community_entries_come_from_advice_cog(monkeypatch):
    cog, _ = make_cog(result(), monkeypatch)
    advice = NS(_corpus=lambda: [{'id': 'fb-001'}, {'id': 'ca-3', 'rule': 'x'}])
    cog.bot = NS(get_cog=lambda name: advice if name == 'Advice' else None)
    assert cog._community_entries() == [{'id': 'ca-3', 'rule': 'x'}]
