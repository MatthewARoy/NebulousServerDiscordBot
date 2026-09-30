import asyncio
from types import SimpleNamespace

from nebulous_bot.command_logging import CommandMetricsLogger


def _context(*, interaction=None, command_failed=False):
    return SimpleNamespace(
        command=SimpleNamespace(qualified_name='advice add', name='add'),
        command_failed=command_failed,
        invoked_with='add',
        interaction=interaction,
        guild=SimpleNamespace(id=10, name='Guild'),
        channel=SimpleNamespace(id=20, name='commands', type=SimpleNamespace(name='text')),
        message=SimpleNamespace(id=30, content='!advice add private free-form text'),
        author=SimpleNamespace(id=40, __str__=lambda self: 'User'),
    )


def test_command_metrics_never_store_raw_message_content():
    logger = CommandMetricsLogger(bot=None)
    saved = {}

    async def capture(**kwargs):
        saved.update(kwargs)

    logger._save_log = capture
    asyncio.run(logger._create_log(_context(), success=True, error_type=None))

    assert saved['arguments'] == ''
    assert saved['full_command'] == 'prefix:advice add'
    assert 'private free-form text' not in repr(saved)


def test_slash_invocation_is_recorded_without_option_values():
    logger = CommandMetricsLogger(bot=None)
    saved = {}

    async def capture(**kwargs):
        saved.update(kwargs)

    logger._save_log = capture
    asyncio.run(logger._create_log(_context(interaction=object()), success=True, error_type=None))
    assert saved['full_command'] == 'slash:advice add'
    assert saved['arguments'] == ''


def test_failed_command_does_not_also_log_success():
    logger = CommandMetricsLogger(bot=None)
    calls = []

    async def capture(**kwargs):
        calls.append(kwargs)

    logger._save_log = capture
    ctx = _context(command_failed=True)
    asyncio.run(logger._log_success(ctx))
    asyncio.run(logger._log_error(ctx, ValueError('bad option')))
    assert len(calls) == 1
    assert calls[0]['success'] is False
