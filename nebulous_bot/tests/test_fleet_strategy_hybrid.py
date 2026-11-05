"""Slash uploads, private responses, and mention/DM compatibility without Discord."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from discord.ext import commands
from discord.ext.commands.view import StringView

from nebulous_bot.cogs.fleet_strategy import FleetStrategyCog
from nebulous_bot.management.commands.runbot import create_bot, handle_command_error
from nebulous_bot.tests.test_fleet_strategy_cog import Attachment, Context, cog


def test_hybrid_commands_have_explicit_uploads_and_canonical_names():
    check = FleetStrategyCog.fleetcheck
    guide = FleetStrategyCog.shipbuilding
    assert isinstance(check, commands.HybridCommand)
    assert isinstance(guide, commands.HybridCommand)
    assert check.aliases == ['shipcheck']
    assert [(p.name, p.type) for p in check.app_command.parameters] == [
        ('attachment', discord.AppCommandOptionType.attachment),
        ('options', discord.AppCommandOptionType.string),
    ]
    assert [p.name for p in guide.app_command.parameters] == ['options']
    for command in (check, guide):
        assert command._max_concurrency.number == 1
        assert command._max_concurrency.wait is False
        assert 0 < len(command.app_command.description) <= 100
        assert all(p.description != '…' for p in command.app_command.parameters)


def test_prefix_upload_parser_keeps_role_and_diagnostic_keys_intact():
    attachment = object()
    options = 'frontline --stack ShipCase:Socket_A,Socket_B --threat hei --dr 0.2'
    ctx = SimpleNamespace(interaction=None, view=StringView(options),
                          message=SimpleNamespace(attachments=[attachment]))
    asyncio.run(FleetStrategyCog.fleetcheck._parse_arguments(ctx))
    assert ctx.args[-1] is attachment
    assert ctx.kwargs == {'options': options}


def test_slash_review_uses_attachment_option_and_defers_before_reading():
    ctx = Context(slash=True)
    ctx.message = None  # Slash uploads do not depend on message attachments.
    attachment = Attachment()
    original_read = attachment.read

    async def read():
        assert ctx.deferred == [{'ephemeral': True}]
        return await original_read()

    attachment.read = read
    asyncio.run(FleetStrategyCog.fleetcheck.callback(cog(), ctx, attachment, options='frontline'))
    assert attachment.read_count == 1
    assert ctx.sent[-1]['document']
    assert all(item['ephemeral'] is True for item in ctx.sent)
    assert all(item['allowed_mentions'].everyone is False for item in ctx.sent)


def test_slash_invalid_options_do_not_download_or_defer():
    ctx, attachment = Context(slash=True), Attachment()
    asyncio.run(FleetStrategyCog.fleetcheck.callback(cog(), ctx, attachment, options='--bogus'))
    assert not ctx.deferred and attachment.read_count == 0
    assert ctx.sent[-1]['ephemeral'] is True


def test_slash_missing_attachment_fails_privately_without_using_message_files():
    attachment = Attachment()
    ctx = Context([attachment], slash=True)
    asyncio.run(FleetStrategyCog.fleetcheck.callback(cog(), ctx))
    assert attachment.read_count == 0
    assert not ctx.deferred
    assert 'attachment' in ctx.sent[-1]['content']
    assert ctx.sent[-1]['ephemeral'] is True


def test_prefix_multiple_attachments_still_fail_with_converter_selected_file():
    attachments = [Attachment(), Attachment()]
    ctx = Context(attachments)
    asyncio.run(FleetStrategyCog.fleetcheck.callback(cog(), ctx, attachments[0]))
    assert all(a.read_count == 0 for a in attachments)
    assert 'exactly one' in ctx.sent[-1]['content']


def test_slash_shipbuilding_defers_and_sends_private_guide():
    ctx = Context(slash=True)
    asyncio.run(FleetStrategyCog.shipbuilding.callback(cog(), ctx, options='denial --lean'))
    assert ctx.deferred == [{'ephemeral': True}]
    assert ctx.sent[-1]['ephemeral'] is True
    assert '/fleetcheck' in ctx.sent[-1]['document']


@pytest.mark.parametrize('error', [
    commands.MaxConcurrencyReached(1, commands.BucketType.default),
    commands.CommandOnCooldown(commands.Cooldown(1, 30), 10, commands.BucketType.user),
    commands.BadArgument('private diagnostic'),
])
def test_slash_errors_stay_private_and_global_handler_does_not_duplicate(error):
    async def exercise():
        ctx = Context(slash=True)
        await cog().strategy_error(ctx, error)
        assert len(ctx.sent) == 1 and ctx.sent[0]['ephemeral'] is True
        assert 'private diagnostic' not in ctx.sent[0]['content']
        await handle_command_error(ctx, error)
        assert len(ctx.sent) == 1

    asyncio.run(exercise())


def test_registration_preserves_intent_off_and_does_not_sync():
    async def exercise():
        bot = create_bot(message_content=False)
        bot.tree.sync = AsyncMock()
        try:
            await bot.add_cog(FleetStrategyCog(bot))
            assert bot.tree.get_command('fleetcheck') is not None
            assert bot.tree.get_command('shipbuilding') is not None
            assert bot.tree.get_command('shipcheck') is None
            assert bot.get_command('shipcheck') is bot.get_command('fleetcheck')
            assert not bot.intents.message_content
            bot.tree.sync.assert_not_awaited()
        finally:
            await bot.close()

    asyncio.run(exercise())
