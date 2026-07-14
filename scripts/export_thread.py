#!/usr/bin/env python
"""Export a Discord channel or thread's message history to knowledge/raw/.

Standalone on purpose: no Django, so it runs without the manage.py env-var
stubs. It talks to the Discord REST API directly with the bot token from
.env — no gateway connection, so it can run locally while the production
bot stays connected.

Usage:
    python scripts/export_thread.py 1508914822597709855
    python scripts/export_thread.py <channel_or_thread_id> --out custom.json

The bot must be in the guild and able to read the channel. Output is
oldest-first JSON with author, timestamp, content, reply reference,
reactions, and jump URL per message — everything curation needs.
"""
import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

import ssl

import aiohttp
import certifi
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / 'knowledge' / 'raw'
API_BASE = 'https://discord.com/api/v10'
PAGE_SIZE = 100


async def _get(session, path, params=None):
    """GET a Discord API path, sleeping through 429s and pre-emptive limits."""
    url = f'{API_BASE}{path}'
    while True:
        async with session.get(url, params=params) as resp:
            if resp.status == 429:
                data = await resp.json()
                delay = float(data.get('retry_after', 1.0))
                print(f'  rate limited, sleeping {delay:.1f}s', file=sys.stderr)
                await asyncio.sleep(delay)
                continue
            if resp.status in (401, 403, 404):
                detail = await resp.text()
                sys.exit(f'Discord API {resp.status} on {path}: {detail}')
            resp.raise_for_status()
            data = await resp.json()
            # Pre-emptively wait out an exhausted bucket instead of 429ing.
            if resp.headers.get('X-RateLimit-Remaining') == '0':
                await asyncio.sleep(float(resp.headers.get('X-RateLimit-Reset-After', 1.0)))
            return data


def _simplify(msg, guild_id, channel_id):
    author = msg.get('author', {})
    ref = msg.get('message_reference') or {}
    return {
        'id': msg['id'],
        'author_id': author.get('id'),
        'author_name': author.get('global_name') or author.get('username'),
        'timestamp': msg.get('timestamp'),
        'content': msg.get('content', ''),
        'reply_to_id': ref.get('message_id'),
        'reactions': [
            {'emoji': r.get('emoji', {}).get('name'), 'count': r.get('count', 0)}
            for r in msg.get('reactions', [])
        ],
        'attachments': len(msg.get('attachments', [])),
        'jump_url': f'https://discord.com/channels/{guild_id}/{channel_id}/{msg["id"]}',
    }


async def export_channel(channel_id, out_path):
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        sys.exit('DISCORD_TOKEN not set — put it in .env or the environment.')

    headers = {'Authorization': f'Bot {token}'}
    # Same certifi-backed context runbot uses — macOS/system Python often
    # lacks the CA bundle openssl expects.
    connector = aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where()))
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        channel = await _get(session, f'/channels/{channel_id}')
        guild_id = channel.get('guild_id', '@me')

        messages = []
        before = None
        while True:
            params = {'limit': str(PAGE_SIZE)}
            if before:
                params['before'] = before
            page = await _get(session, f'/channels/{channel_id}/messages', params)
            if not page:
                break
            messages.extend(_simplify(m, guild_id, channel_id) for m in page)
            before = page[-1]['id']  # pages come newest-first
            print(f'  fetched {len(messages)} messages...', file=sys.stderr)
            if len(page) < PAGE_SIZE:
                break

    messages.reverse()  # oldest-first for readable curation
    dump = {
        'channel_id': str(channel_id),
        'channel_name': channel.get('name'),
        'guild_id': guild_id,
        'exported_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'message_count': len(messages),
        'messages': messages,
    }

    # Atomic write: never leave a truncated dump behind.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(dump, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(out_path)
    print(f'Wrote {len(messages)} messages to {out_path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('channel_id', help='Discord channel or thread id')
    parser.add_argument('--out', help='Output path (default: knowledge/raw/<id>-<date>.json)')
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / '.env')
    date = datetime.date.today().isoformat()
    out = Path(args.out) if args.out else RAW_DIR / f'{args.channel_id}-{date}.json'
    asyncio.run(export_channel(args.channel_id, out))


if __name__ == '__main__':
    main()
