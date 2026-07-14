#!/usr/bin/env python
"""Generate mod/wiki exports from the canonical knowledge base.

Reads knowledge/entries/*.toml and writes derived artifacts to
knowledge/exports/ (gitignored — regenerate, never hand-edit):

  advice.json      one stable-shape file the in-game shipbuilding mod
                   bundles at build time
  <category>.md    one wiki/guide-ready Markdown page per category

Usage:
    python scripts/export_knowledge.py                # both formats
    python scripts/export_knowledge.py --format json
    python scripts/export_knowledge.py --format markdown
"""
import argparse
import datetime
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from nebulous_bot.knowledge import load_entries, load_tags  # noqa: E402

EXPORTS_DIR = REPO_ROOT / 'knowledge' / 'exports'


def export_json(entries, out_dir):
    payload = {
        'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'entry_count': len(entries),
        'entries': [
            {
                'id': e['id'],
                'category': e['category'],
                'situation': e.get('situation', ''),
                'rule': e['rule'],
                'reason': e.get('reason', ''),
                'tags': e.get('tags', []),
                'author': e.get('author', ''),
                'source_url': e.get('source_url', ''),
            }
            for e in entries
        ],
    }
    path = out_dir / 'advice.json'
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Wrote {path} ({len(entries)} entries)')


def export_markdown(entries, tags, out_dir):
    by_category = defaultdict(list)
    for e in entries:
        by_category[e['category']].append(e)

    for category, cat_entries in sorted(by_category.items()):
        title = category.replace('-', ' ').title()
        lines = [
            f'# {title} — Community Advice',
            '',
            '> Curated from the Nebulous: Fleet Command community Discord.',
            '> Generated file — edit `knowledge/entries/` instead.',
            '',
        ]
        # Group under each entry's first tag so related advice reads together.
        by_tag = defaultdict(list)
        for e in cat_entries:
            primary = e.get('tags', ['misc'])[0] if e.get('tags') else 'misc'
            by_tag[primary].append(e)
        for tag, tag_entries in sorted(by_tag.items()):
            heading = tag.replace('-', ' ').title()
            if tags.get(tag):
                heading += f' — {tags[tag]}'
            lines += [f'## {heading}', '']
            for e in tag_entries:
                lines.append(f'**{e["rule"]}**')
                if e.get('situation'):
                    lines.append(f'- *When:* {e["situation"]}')
                if e.get('reason'):
                    lines.append(f'- *Why:* {e["reason"]}')
                credit = e.get('author', 'unknown')
                if e.get('source_url'):
                    lines.append(f'- *Source:* [{credit} on Discord]({e["source_url"]})')
                else:
                    lines.append(f'- *Source:* {credit}')
                lines.append('')
        path = out_dir / f'{category}.md'
        path.write_text('\n'.join(lines), encoding='utf-8')
        print(f'Wrote {path} ({len(cat_entries)} entries)')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--format', choices=['json', 'markdown'], help='One format only (default: both)')
    parser.add_argument('--out', help='Output directory (default: knowledge/exports/)')
    args = parser.parse_args()

    entries = load_entries()
    if not entries:
        sys.exit('No entries found in knowledge/entries/ — nothing to export.')
    out_dir = Path(args.out) if args.out else EXPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.format in (None, 'json'):
        export_json(entries, out_dir)
    if args.format in (None, 'markdown'):
        export_markdown(entries, load_tags(), out_dir)


if __name__ == '__main__':
    main()
