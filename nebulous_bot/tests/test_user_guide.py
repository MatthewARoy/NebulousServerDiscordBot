"""The guide is usable in Discord without external documentation or channel spam."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from nebulous_bot.cogs.admin import AdminCog
from nebulous_bot.user_guide import build_user_guide


@pytest.mark.parametrize('message_content', [True, False])
def test_guide_fits_discord_and_describes_the_running_intent_mode(message_content):
    embed = build_user_guide(message_content=message_content)
    assert len(embed) <= 6000
    assert len(embed.fields) <= 25
    assert all(len(field.name) <= 256 and len(field.value) <= 1024 for field in embed.fields)
    text = '\n'.join(field.value for field in embed.fields)
    assert 'http' not in text.lower()
    assert 'github' not in text.lower()
    assert ('still work in server channels' in text) == message_content
    assert ('instead of plain' in text) != message_content
    assert '/formation' in text and '/nextgame' in text


@pytest.mark.parametrize('slash', [True, False])
def test_guide_responds_privately_to_slash_and_also_supports_prefix(slash):
    bot = SimpleNamespace(intents=discord.Intents.default())
    ctx = SimpleNamespace(interaction=object() if slash else None, send=AsyncMock())
    asyncio.run(AdminCog.show_guide.callback(AdminCog(bot), ctx))
    ctx.send.assert_awaited_once()
    assert isinstance(ctx.send.await_args.kwargs['embed'], discord.Embed)
    assert ctx.send.await_args.kwargs['ephemeral'] == slash
