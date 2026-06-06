# `!ng modded` — wait for the next modded game

**Date:** 2026-06-05
**Status:** Approved (design)

## Summary

Add a `modded` flag to the existing `!nextgame` / `!ng` command so players can
sign up to be pinged only when a server **running mods** next becomes ready.
This serves players who only want full modded faction gameplay (e.g. Modded
Fight Night / "MFC" servers), rather than vanilla Nebulous.

The flag mirrors the existing `ptb` flag in every respect: it is a narrowing
filter on which "ready" servers trigger a given user's ping, it stacks with the
other flags, and plain `!ng` behaviour is unchanged.

## Behaviour

- `!ng modded` — ping me only when a **modded** server is ready (lobby with 3+
  players and space, or a server entering debrief).
- Stacks with existing flags: `!ng modded ptb`, `!ng modded lobby`,
  `!ng modded --skip` all valid. Keyword `modded` (alias `mod`).
- Plain `!ng` is unchanged — it still pings for any ready server, modded
  included. `modded` only *narrows*.
- `!cancelnextgame` cancels the modded signup too (it already clears all of a
  user's queue modes).
- "Ready" criteria for modded servers are identical to normal `!ng`: a lobby
  with `3 <= players < capacity`, or a server in / just transitioned to
  `debrief`.

## Modded detection (decided)

A server counts as modded when it reports a **non-empty `modList`** server rule
(the actual list of mods loaded). Verified against live servers:

- MFC (modded) servers report `modFriendly=1` **and** a non-empty `modList`
  (their faction mods).
- ERI (vanilla) servers report `modFriendly=0` and have **no** `modList`.
- No server reports a `modded` rule — the code's current `'modded'` key is dead.

`modList` non-empty is the precise signal for "running modded gameplay" and
will not false-trigger on vanilla servers that merely permit mods
(`modFriendly=1`, empty/absent `modList`).

### Latent bug to fix as part of this work

`SteamAPI._extract_direct_nebulous_rules` filters rules with
`key.lower() in nebulous_rule_keys`, but the set contains the mixed-case
`'modFriendly'` (and a never-present `'modded'`). So `modFriendly` is silently
dropped today and `modList` was never captured. Fix: lowercase all keys in the
set and add `'modlist'`; drop the dead `'modded'`.

## Approach

**Chosen: A — mirror `ptb_only` with a parallel `modded_only` boolean.**

The waiter system keys each signup by `(user_id, ptb_only)` and threads the
`ptb_only` boolean through ~10 call sites. We add a parallel `modded_only`
boolean alongside it everywhere it already flows. Repetitive but consistent
with the established pattern and lowest-risk to the working notification code.

Rejected: B — generalize the two booleans into one hashable "mode" / filter set
with a single match predicate. Cleaner long-term but a broader refactor of
currently-working code with more regression surface. **Note for the future:** if
a third filter dimension is ever added, switch to B rather than threading a
third boolean.

## Changes by layer

### 1. Data — `nebulous_bot/steam_api.py`

- Fix `_extract_direct_nebulous_rules`: lowercase the `nebulous_rule_keys` set,
  add `'modlist'`, remove the dead `'modded'`.
- Confirm both rule-parse paths surface `modList`: the embedded-JSON path
  (`_parse_nebulous_rules_json`) and the direct path
  (`_extract_direct_nebulous_rules`).
- In `_create_enhanced_server_data`, set `server['is_modded']` from a non-empty
  `modList` rule (mirroring how `competitive` / `autobalance` are set). Default
  `False` when rules are absent.

### 2. Command — `nebulous_bot/management/commands/runbot.py`

- In `next_game_notify`, parse a `modded` token (alias `mod`) like `ptb`, and
  pass `modded_only` to the monitor methods.
- Update the command's usage/help text and the confirmation + ping embeds to
  show a "modded only" indicator (alongside the existing "PTB only").

### 3. Waiter + matching — `nebulous_bot/server_monitor.py`

- Extend the waiter key to include `modded_only` (e.g.
  `_next_game_waiter_key(user_id, ptb_only, modded_only)`), and update the few
  key-unpacking sites that assume a 2-tuple (`(user_id, _)` / `key[0]` in
  `_notify_next_game_waiters`, `_check_daily_next_game_queue_alert`,
  `is_user_waiting_for_next_game`, `get_next_game_waiters_count`).
  `remove_next_game_waiter`'s `key[0]` "remove all modes" path already works.
- `add_next_game_waiter` / `get_next_game_waiter` / `is_user_waiting_for_next_game`
  gain a `modded_only` parameter; store `modded_only` in the waiter_info dict.
- `find_matching_servers_for_notification(ptb_only, modded_only)` — add a modded
  filter (`server.get('is_modded')`) mirroring the PTB filter.
- `_notify_next_game_waiters` — extend the channel grouping and `base_servers`
  filtering to account for `modded_only`, mirroring the PTB branch; add a
  "(modded only)" indicator to the notification embed/log text.
- `--skip` helpers (`get_joinable_lobby_ids`, `resolve_server_names`) gain a
  `modded_only` parameter so the skip-list is scoped to modded lobbies when in
  modded mode.

### 4. Tests — `nebulous_bot/tests/`

- Detection: a server whose rules carry a non-empty `modList` yields
  `is_modded=True`; empty/absent `modList` yields `False`.
- Matching: `find_matching_servers_for_notification(modded_only=True)` over a
  stubbed `cached_servers` returns only modded-ready servers; with
  `modded_only=False` it returns all ready servers (regression guard for plain
  `!ng`).

## Edge cases

- If the per-server rules query fails, `is_modded` is `False` and that server
  won't trigger a modded ping. This is consistent with every other
  rules-derived field (`competitive`, `submode`, etc.) and is acceptable.
- Plain `!ng` continues to trigger on modded servers — modded servers are still
  servers; `modded` only narrows.

## Out of scope (YAGNI)

- No `!ng vanilla` (exclude-modded) flag.
- No modded labeling in the live status embed.

Both are easy follow-ups if wanted later.
