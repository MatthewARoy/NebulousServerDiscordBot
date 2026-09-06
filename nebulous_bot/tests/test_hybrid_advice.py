import asyncio
from types import SimpleNamespace

from discord.ext import commands
from discord.ext.commands.view import StringView

from nebulous_bot.cogs.advice import AdviceCog


def test_advice_group_uses_search_fallback():
    group = AdviceCog.advice
    assert isinstance(group, commands.HybridGroup)
    assert group.fallback == 'search'
    assert group.app_command is not None
    assert group.app_command.description


def test_public_advice_subcommands_have_application_commands():
    group = AdviceCog.advice
    for name in ('add', 'remove', 'pending', 'list'):
        command = group.get_command(name)
        assert isinstance(command, commands.HybridCommand)
        assert command.app_command is not None
        assert command.app_command.description


def test_advice_restore_remains_hidden_and_prefix_only():
    restore = AdviceCog.advice.get_command('restore')
    assert restore.hidden is True
    assert restore.app_command is None


def test_prefix_parser_keeps_bare_group_search_query():
    ctx = SimpleNamespace(
        interaction=None,
        view=StringView('point defense'),
        message=SimpleNamespace(attachments=[]),
    )

    asyncio.run(AdviceCog.advice._parse_arguments(ctx))

    assert ctx.kwargs == {'query': 'point defense'}
