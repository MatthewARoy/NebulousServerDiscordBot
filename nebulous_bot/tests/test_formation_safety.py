import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from discord.ext import commands
from discord.ext.commands.view import StringView

from nebulous_bot.cogs.formation import (
    MAX_FLEET_BYTES,
    MAX_SHIPS,
    FormationCog,
    FormationResult,
    _sample_animation_states,
    parse_formation_options,
    validate_fleet_xml,
)


VALID_FLEET = b"""<?xml version="1.0"?>
<Fleet>
  <Name>Test Fleet</Name>
  <Ships><Ship><InitialFormation /></Ship></Ships>
</Fleet>
"""


def test_formation_is_a_hybrid_command_with_attachment_option():
    command = FormationCog.optimize_formation
    assert isinstance(command, commands.HybridCommand)
    assert command.app_command is not None
    assert list(command.app_command._params) == ['attachment', 'options']


def test_legacy_formation_options_remain_compatible():
    options = parse_formation_options('500 -planar -symmetric -cleararcs -skip')
    assert options.min_radius_meters == 500
    assert options.planar is True
    assert options.symmetrical is True
    assert options.clear_arcs is True
    assert options.skip_images is True


def test_prefix_parser_keeps_attachment_separate_from_free_form_options():
    attachment = object()
    ctx = SimpleNamespace(
        interaction=None,
        view=StringView('500 -planar'),
        message=SimpleNamespace(attachments=[attachment]),
    )

    asyncio.run(FormationCog.optimize_formation._parse_arguments(ctx))

    assert ctx.args[-1] is attachment
    assert ctx.kwargs == {'options': '500 -planar'}


def test_formation_options_reject_unknown_or_unbounded_values():
    with pytest.raises(ValueError, match='Unknown formation option'):
        parse_formation_options('-surprise')
    with pytest.raises(ValueError, match='between'):
        parse_formation_options('0')


def test_fleet_xml_accepts_minimal_valid_document():
    assert validate_fleet_xml(VALID_FLEET) == 1


def test_fleet_xml_rejects_oversized_or_active_xml_constructs():
    with pytest.raises(ValueError, match='MiB limit'):
        validate_fleet_xml(b'x' * (MAX_FLEET_BYTES + 1))
    with pytest.raises(ValueError, match='declarations and entities'):
        validate_fleet_xml(b'<!DOCTYPE Fleet [<!ENTITY x "boom">]><Fleet />')

    utf16_dtd = '<!DOCTYPE Fleet><Fleet><Name>x</Name></Fleet>'.encode('utf-16')
    with pytest.raises(ValueError, match='declarations and entities'):
        validate_fleet_xml(utf16_dtd)


def test_fleet_xml_rejects_pathological_depth_and_ship_count():
    deep = ('<Fleet><Name>x</Name>' + '<x>' * 65 + '</x>' * 65 + '</Fleet>').encode()
    with pytest.raises(ValueError, match='maximum depth'):
        validate_fleet_xml(deep)

    ships = ''.join('<Ship><InitialFormation /></Ship>' for _ in range(MAX_SHIPS + 1))
    crowded = f'<Fleet><Name>x</Name><Ships>{ships}</Ships></Fleet>'.encode()
    with pytest.raises(ValueError, match=f'more than {MAX_SHIPS} ships'):
        validate_fleet_xml(crowded)


def test_animation_sampling_is_bounded_and_keeps_endpoints():
    states = [object() for _ in range(20)]
    sampled = _sample_animation_states(states)

    assert len(sampled) <= 5
    assert sampled[0] is states[0]
    assert sampled[-1] is states[-1]


def test_cancelled_worker_retains_exclusive_capacity_until_thread_finishes(monkeypatch):
    started = threading.Event()
    finish = threading.Event()

    def blocking_process(_content, _options):
        started.set()
        finish.wait(timeout=2)
        return FormationResult(b'<Fleet />', None, 1)

    monkeypatch.setattr('nebulous_bot.cogs.formation.process_formation', blocking_process)

    async def scenario():
        cog = FormationCog(SimpleNamespace())
        attachment = SimpleNamespace(
            filename='test.fleet',
            size=len(VALID_FLEET),
            read=AsyncMock(return_value=VALID_FLEET),
        )
        first_ctx = SimpleNamespace(
            interaction=SimpleNamespace(),
            defer=AsyncMock(),
            send=AsyncMock(),
        )
        first = asyncio.create_task(
            FormationCog.optimize_formation.callback(cog, first_ctx, attachment, options='-skip')
        )
        assert await asyncio.to_thread(started.wait, 1)

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert cog._optimization_lock.locked()

        busy_ctx = SimpleNamespace(interaction=SimpleNamespace(), send=AsyncMock())
        await FormationCog.optimize_formation.callback(cog, busy_ctx, attachment, options='-skip')
        busy_ctx.send.assert_awaited_once_with(
            '⏳ Another fleet is being optimized. Please try again shortly.',
            ephemeral=True,
        )
        attachment.read.assert_awaited_once()

        finish.set()
        for _ in range(20):
            if not cog._optimization_lock.locked():
                break
            await asyncio.sleep(0.01)
        assert not cog._optimization_lock.locked()

    asyncio.run(scenario())
