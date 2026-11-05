"""Exercise command callbacks without a Discord connection or ORM access."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import discord
from discord.ext import commands
import pytest

from fleet_strategy import MAX_FLEET_BYTES, load_bundle
from nebulous_bot.cogs.fleet_strategy import FleetStrategyCog, _review_embed

ROOT = Path(__file__).resolve().parents[2]
SHIP = b'<Ship><Name>@everyone [beam]</Name><HullType>Stock/Keystone Destroyer</HullType><SocketMap><HullSocket><ComponentName>Stock/Mk600 Beam Cannon</ComponentName></HullSocket></SocketMap></Ship>'


class Attachment:
    def __init__(self, data=SHIP, filename='example.ship', size=None):
        self.data, self.filename = data, filename
        self.size = len(data) if size is None else size
        self.read_count = 0

    async def read(self):
        self.read_count += 1
        return self.data


class Context:
    def __init__(self, attachments=(), *, slash=False):
        self.message = SimpleNamespace(attachments=list(attachments))
        self.interaction = object() if slash else None
        self.deferred = []
        self.sent = []

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)

    async def send(self, content=None, **kwargs):
        item = {'content': content, **kwargs}
        if 'file' in kwargs:
            item['document'] = kwargs['file'].fp.getvalue().decode('utf-8')
        self.sent.append(item)


def cog(removed=(), available=True):
    instance = FleetStrategyCog.__new__(FleetStrategyCog)
    instance.bundle = load_bundle(ROOT / 'knowledge')
    instance.bot = SimpleNamespace(get_cog=lambda name: SimpleNamespace(removed_ids=set(removed)) if available else None)
    return instance


def invoke(instance, ctx, role=None, command='fleetcheck'):
    asyncio.run(getattr(FleetStrategyCog, command).callback(instance, ctx, options=role))
    assert ctx.sent
    for item in ctx.sent:
        assert item['allowed_mentions'].to_dict() == discord.AllowedMentions.none().to_dict()
        if 'embed' in item:
            embed = item['embed']
            assert len(embed) <= 6000 and len(embed.fields) <= 25
            assert all(len(field.value) <= 1024 and len(field.name) <= 256 for field in embed.fields)


@pytest.mark.parametrize('attachments', [[], [Attachment(), Attachment()], [Attachment(filename='file.txt')],
                                         [Attachment(size=MAX_FLEET_BYTES + 1)]])
def test_rejects_bad_attachment_before_download(attachments):
    ctx = Context(attachments)
    invoke(cog(), ctx)
    assert all(item.read_count == 0 for item in attachments)
    assert 'document' not in ctx.sent[-1]


@pytest.mark.parametrize('data', [b'bad xml', b'x' * (MAX_FLEET_BYTES + 1), b'<!DOCTYPE Ship><Ship/>'],
                         ids=['malformed', 'actual-oversize', 'dtd'])
def test_checks_real_payload_and_malformed_xml(data):
    ctx = Context([Attachment(data=data, size=1)])
    invoke(cog(), ctx)
    assert 'Unable to review' in ctx.sent[-1]['content']


def test_unknown_role_and_unavailable_bundle_do_not_download():
    item = Attachment()
    ctx = Context([item])
    invoke(cog(), ctx, role='nonsense')
    assert 'Unknown role' in ctx.sent[-1]['content'] and item.read_count == 0
    instance = cog()
    instance.bundle = None
    ctx = Context([item])
    invoke(instance, ctx)
    assert 'unavailable' in ctx.sent[-1]['content'] and item.read_count == 0


def test_ship_review_lean_mode_and_tombstones():
    ctx = Context([Attachment()])
    invoke(cog(removed=['fb-001']), ctx, role='denial --lean')
    report = ctx.sent[-1]['document']
    assert 'Investment posture: lean' in report
    assert 'Check: beam-particle-support' not in report
    assert 'Check: beam-fire-control' in report
    assert 'Verified game version: not asserted' in report
    assert 'reinforced' in report.lower() and 'cringed' in report.lower()
    assert '@everyone' not in report


def test_missing_moderation_state_withholds_automated_advice():
    ctx = Context([Attachment()])
    invoke(cog(available=False), ctx)
    report = ctx.sent[-1]['document']
    assert 'community removal state could not be checked' in report
    assert 'Check: beam-particle-support' not in report
    assert 'not a quality verdict' in report


def test_full_guide_contains_examples_layout_and_build_sequence():
    ctx = Context()
    invoke(cog(), ctx, role='denial --lean', command='shipbuilding')
    report = ctx.sent[-1]['document']
    assert 'TF Oak' in report and 'Kyanite Squadron' in report
    assert 'Protected internal regions' in report
    assert 'Reinforced stacks' in report
    assert 'Select a reference package' in report
    assert 'Tethys' in report


def test_oversize_report_fails_explicitly_instead_of_silent_truncation():
    ctx = Context([Attachment()])
    with patch('nebulous_bot.cogs.fleet_strategy._REPORT_BYTE_LIMIT', 10):
        invoke(cog(), ctx)
    assert 'complete report is too large' in ctx.sent[-1]['content']
    assert 'document' not in ctx.sent[-1]


def test_embed_limits_and_no_pass_verdict():
    result = {'fleet_name': '@everyone' * 200, 'findings': [], 'limitations': ['x' * 10000] * 20,
              'unknown_ids': [], 'declared_points': None}
    embed = _review_embed(result, None)
    assert len(embed) <= 6000
    assert 'not a quality verdict' in embed.fields[0].value
    assert '@everyone' not in embed.title


def test_command_error_marks_global_handled_and_disables_mentions():
    ctx = Context()
    error = commands.MaxConcurrencyReached(1, commands.BucketType.default)
    asyncio.run(cog().strategy_error(ctx, error))
    assert error.fleet_strategy_handled
    assert 'already running' in ctx.sent[-1]['content']
    assert ctx.sent[-1]['allowed_mentions'].to_dict() == discord.AllowedMentions.none().to_dict()
