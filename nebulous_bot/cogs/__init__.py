"""Command cogs for the Nebulous Discord bot.

Each module holds one command group, moved verbatim out of
``management/commands/runbot.py`` (see docs/superpowers/plans/
2026-07-06-cog-split.md). Cogs read shared runtime state via attributes on
the bot object (``bot.server_monitor``, ``bot.formatter``,
``bot.deployment_time``) — these are None until ``on_ready`` fills them in,
so every command that needs them must keep its None-guard.

This package's ``__init__`` must stay import-light: tests import individual
cog modules for their pure parsing helpers, and ``cogs.formation`` pulls in
numpy + matplotlib.
"""
