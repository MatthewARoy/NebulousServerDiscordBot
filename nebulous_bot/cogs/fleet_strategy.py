"""Read-only fleet design guidance and attached fleet reviews."""
import asyncio
import io
import logging
import math
import os
from contextlib import closing
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from fleet_strategy import (
    BundleError, FleetInputError, MAX_FLEET_BYTES, load_bundle, parse_design,
    review_fleet, load_geometry,
)
from fleet_strategy.damage import damage_inventory, evaluate_stack
from fleet_strategy.protection import review_protection
from nebulous_bot.config import Config
from nebulous_bot.knowledge import KNOWLEDGE_DIR

logger = logging.getLogger(__name__)

ROLE_IDS = (
    'frontline', 'skirmish', 'denial', 'capture', 'scouting',
    'missile-support', 'carrier-support',
)
_ESCAPES = str.maketrans({char: '\\' + char for char in '\\`*_~|[]()<>'})
_SUMMARY_FINDINGS = 4
_EMBED_BUDGET = 5000
_REPORT_BYTE_LIMIT = 7 * 1024 * 1024
_SCOPE = (
    'Advisory review for standard 3000-point team PvP; no score or pass/fail verdict.',
    'Saved point costs are not recalculated against current game data.',
    'No current power, crew, firing arcs or PD coverage validation. Geometry coverage is stated separately.',
    'Teammate support, operating formation and execution need human review.',
)
_NO_COMMUNITY_STATE = (
    'Automated advice is unavailable because community removal state could not be checked. '
    'No automated findings were generated; the attached guide provides manual questions.'
)
_STACK_USAGE = '!fleetcheck [role] [--lean] --stack SHIP_KEY:SOCKET,SOCKET --threat ID --dr FRACTION'
_STACK_PROFILES = 'hei, 120-he, 250-he, 450-he, 450-ap, 300-rail, 600-hesh, 500-fracturing'
_DIRECTIONS = ('bow', 'stern', 'port', 'starboard', 'top', 'bottom')
_STACK_GUIDE = (
    'Regional review: /fleetcheck defaults to HEI from the bow. Use options such as --threat 450-ap --direction port. '
    'The current geometry cache supports HEI and 450 AP ray samples. HE explosion profiles need the manual calculator '
    'because complete overlap-query coverage is unavailable. '
    'Automatic coverage needs a matching geometry dataset configured by the bot operator; missing or unsupported data is grey. '
    'Sampled paths describe conditional packet/DT margins, not armor penetration, whole-region coverage or combat immunity. '
    'Recommendations are candidates for checking in the game, and continued operation is not guaranteed.',
    'Conditional destruction-threshold calculator (DT): use /fleetcheck with its attachment option for a .fleet or .ship file. '
    'Put the role and flags below in options. In a DM, use !fleetcheck; in a server, mention the bot followed by fleetcheck. '
    'Its report lists fitted reinforced socket keys. Select the ship and every recipient socket '
    'explicitly in assumed hit order; the file does not establish a nose, adjacency or the path of a damage ray.',
    _STACK_USAGE,
    'Example: !fleetcheck --stack ship-1:SocketA,SocketB --threat hei --dr 0.2 '
    '(replace the example keys with exact keys from your report).',
    'Profiles: ' + _STACK_PROFILES + '. DR is an assumed damage-reduction fraction from 0 to 0.9; '
    '0.2 means 20%. It is not inferred from the build.',
    'Blue means at or below DT only under the stated assumptions; amber means a threshold is exceeded; '
    'grey means unknown. Each recipient keeps its own DT: thresholds are not added together. '
    'Regional results also identify vulnerable or unknown supporting recipients. Overlay projections show amber for '
    'vulnerable support and grey for unknown support, even when the target itself is within DT. '
    'DT gates destruction; HP loss and disabled functions remain possible below DT. '
    'These colors do not establish combat immunity, survival or a safe nose design. '
    'Read the packet model, assumptions, limits and evidence in the attached report.',
)
_STACK_STATES = {
    'conditional-below-dt': ('🔵 Conditional: within DT', 0x3498DB),
    'threshold-exceeded': ('🟠 Threshold exceeded', 0xE0A000),
    'unknown': ('⚪ Unknown', 0x808080),
}


def _arguments(text, *, calculator=False):
    """Parse command options without folding case-sensitive fleet/socket keys."""
    tokens = text.split() if text else []
    flags, roles = {}, []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        flag = token.lower()
        if flag == '--lean':
            if flag in flags:
                raise FleetInputError('Duplicate --lean flag.')
            flags[flag] = True
        elif flag in {'--stack', '--threat', '--dr', '--direction'}:
            if not calculator:
                raise FleetInputError('Damage calculator flags are only available with !fleetcheck. ' + _STACK_USAGE)
            if flag in flags:
                raise FleetInputError('Duplicate ' + flag + ' flag.')
            index += 1
            if index >= len(tokens) or tokens[index].startswith('--'):
                raise FleetInputError('Missing value for ' + flag + '. ' + _STACK_USAGE)
            flags[flag] = tokens[index]
        elif token.startswith('-'):
            raise FleetInputError('Unknown or malformed flag. ' + _STACK_USAGE)
        else:
            roles.append(token.lower())
        index += 1
    if len(roles) > 1 or (roles and roles[0] not in ROLE_IDS):
        raise FleetInputError('Unknown role. Choose: ' + ', '.join(ROLE_IDS) + '. Add --lean for deliberate reduced investment.')
    scenario = None
    if '--direction' in flags and flags['--direction'].lower() not in _DIRECTIONS:
        raise FleetInputError('--direction must be one of: ' + ', '.join(_DIRECTIONS) + '.')
    if '--stack' in flags or '--dr' in flags:
        if not all(flag in flags for flag in ('--stack', '--threat', '--dr')):
            raise FleetInputError('Supply --stack, --threat and --dr together. ' + _STACK_USAGE)
        if '--direction' in flags:
            raise FleetInputError('--direction selects automatic coverage. Omit it when using an assumed --stack scenario.')
        stack = flags['--stack']
        if stack.count(':') != 1:
            raise FleetInputError('--stack must be SHIP_KEY:SOCKET,SOCKET using exact keys from the report.')
        ship_key, socket_text = stack.split(':')
        socket_keys = socket_text.split(',')
        if not ship_key or any(not key for key in socket_keys) or len(socket_keys) != len(set(socket_keys)):
            raise FleetInputError('--stack requires a ship key and unique, nonempty socket keys.')
        try:
            reduction = float(flags['--dr'])
        except ValueError as exc:
            raise FleetInputError('--dr must be a fraction from 0 to 0.9, for example 0.2 for 20%.') from exc
        if not math.isfinite(reduction) or not 0 <= reduction <= 0.9:
            raise FleetInputError('--dr must be a finite fraction from 0 to 0.9.')
        scenario = {
            'ship_key': ship_key, 'socket_keys': socket_keys,
            'threat_id': flags['--threat'].lower(), 'damage_reduction': reduction,
        }
    protection = {'threat_id': flags.get('--threat', 'hei').lower(),
                  'direction': flags.get('--direction', 'bow').lower()}
    return roles[0] if roles else None, 'lean' if '--lean' in flags else 'standard', scenario, protection


def _safe(value):
    """Keep arbitrary names/text from creating Markdown or Discord mentions."""
    return _plain(value).translate(_ESCAPES)


def _plain(value):
    """Keep attachment identifiers copyable without introducing live mentions."""
    text = ' '.join(str(value if value is not None else '').split())
    return discord.utils.escape_mentions(text)


def _clip(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + '…'


async def _send(ctx, content=None, **kwargs):
    """Keep uploaded designs and errors private on the slash-command surface."""
    await ctx.send(content, ephemeral=getattr(ctx, 'interaction', None) is not None,
                   allowed_mentions=discord.AllowedMentions.none(), **kwargs)


async def _defer(ctx):
    if getattr(ctx, 'interaction', None) is not None:
        await ctx.defer(ephemeral=True)


def _field(embed, name, value):
    """Apply both individual Discord limits and a whole-embed budget."""
    name = _clip(_safe(name), 256)
    budget = min(1024, _EMBED_BUDGET - len(embed) - len(name))
    if budget > 1 and len(embed.fields) < 25:
        embed.add_field(name=name, value=_clip(value or '—', budget), inline=False)


def _role(bundle, role_id):
    return next((r for r in bundle['strategy']['roles'] if r['id'] == role_id), None)


def _guide_lines(bundle, role_id=None, strategy=None, investment='standard'):
    """The complete human review guide; attachments never silently omit entries."""
    base = bundle['strategy']
    strategy = strategy or {}
    lines = [_safe(base['title']), _safe(base.get('context', '')), '']
    lines.extend(['Investment posture: ' + investment, _safe(base.get('provenance', '')), ''])
    for principle in strategy.get('principles', base['principles']):
        lines.extend([_safe(principle['title']), _safe(principle['summary'])])
        lines.extend('  Question: ' + _safe(q) for q in principle.get('questions', []))
        lines.append('')
    selected = strategy.get('role') or _role(bundle, role_id)
    roles = [selected] if selected else base['roles']
    for role in roles:
        lines.extend([f"Role: {_safe(role['id'])} — {_safe(role['title'])}", _safe(role['summary'])])
        for key, label in (
            ('targets', 'Target'), ('dependencies', 'Dependency'),
            ('tradeoffs', 'Tradeoff'), ('success_measures', 'Success measure'),
        ):
            lines.extend(f'  {label}: {_safe(value)}' for value in role.get(key, []))
        lines.append('')
    for section, label in (('investment_modes', 'Investment'), ('layout_concepts', 'Internal layout'),
                           ('build_sequence', 'Build sequence'), ('review_backlog', 'Further review')):
        for item in base.get(section, []):
            lines.extend([label + ': ' + _safe(item.get('title', item['id'])), _safe(item['summary'])])
            for field in ('mechanics', 'status', 'source'):
                if item.get(field):
                    lines.append('  ' + field.title() + ': ' + _safe(item[field]))
            for field in ('questions', 'conditions'):
                lines.extend('  - ' + _safe(value) for value in item.get(field, []))
            lines.append('')
    lines.append('Examples: local saved starter copies; not certified current built-in assets.')
    for example in strategy.get('examples', base.get('examples', [])):
        lines.extend([
            f"{_safe(example['title'])} ({_safe(example.get('faction', ''))})",
            _safe(example['summary']),
        ])
        lines.extend('  Lesson: ' + _safe(v) for v in example.get('lessons', []))
        lines.extend('  Dependency: ' + _safe(v) for v in example.get('dependencies', []))
        if example.get('source_file'):
            lines.append('  Saved example: ' + _safe(example['source_file']))
        lines.append('')
    for reference in base.get('references', []):
        lines.extend(['Reference: ' + _safe(reference['title']),
                      _safe(reference.get('url', reference.get('location', ''))),
                      _safe(reference.get('status', '')), ''])
    lines.extend(['Conditional component-stack calculation:', *_STACK_GUIDE, ''])
    return lines


def _damage_lines(result):
    lines = ['', 'Reinforced component inventory (not an inferred stack):']
    inventory = result.get('damage_inventory', [])
    if not inventory:
        lines.append('No supported reinforced socket keys are available for this report; this is not a protection verdict.')
    for ship in inventory:
        lines.extend(['Ship: ' + _safe(ship.get('ship_name')), '  Ship key: ' + _plain(ship.get('ship_key'))])
        for socket in ship.get('sockets', []):
            lines.append('  Socket key: ' + _plain(socket.get('key')) + '; component: ' +
                         _safe(socket.get('component')) + '; individual DT: ' + _safe(socket.get('threshold')))
    lines.append('Use exact ship/socket keys with --stack, --threat and --dr. See the built-in guide below.')
    scenario = result.get('damage_scenario')
    if scenario is None:
        return lines
    state, _ = _STACK_STATES.get(scenario.get('status'), _STACK_STATES['unknown'])
    threat = scenario.get('threat') or {}
    lines.extend([
        '', 'Explicit conditional damage scenario:',
        'Status: ' + _safe(state),
        'Title: ' + _safe(scenario.get('title')),
        'Summary: ' + _safe(scenario.get('summary')),
        'Selected ship key: ' + _plain(scenario.get('ship_key', 'unknown')),
        'Selected socket keys: ' + ', '.join(_plain(key) for key in scenario.get('socket_keys', [])),
        'Threat: ' + _safe(threat.get('label', threat.get('id', 'unknown'))),
        'Threat ID: ' + _safe(threat.get('id', 'unknown')),
        'Packet distribution: ' + _safe(threat.get('distribution', 'unknown')),
        'Source packet damage: ' + _safe(threat.get('packet_damage', 'unknown')),
        'Assumed damage-reduction fraction: ' + _safe(scenario.get('damage_reduction')),
        'Audited game version: ' + _safe(scenario.get('game_version', 'not asserted')),
    ])
    if 'applied_damage_reduction' in scenario:
        lines.append('Applied damage-reduction fraction for this profile: ' + _safe(scenario['applied_damage_reduction']))
    if 'shared_packet_budget_after_dr' in scenario:
        lines.append('Weakest-recipient equal-split budget after DR (not summed DT): ' +
                     _safe(scenario['shared_packet_budget_after_dr']))
    for recipient in scenario.get('recipients', []):
        outcome = {True: 'exceeded', False: 'not exceeded', None: 'unknown'}.get(recipient.get('exceeds_threshold'), 'unknown')
        lines.append('  Socket: ' + _plain(recipient.get('socket_key')) + '; component: ' +
                     _safe(recipient.get('component')) + '; individual DT: ' + _safe(recipient.get('threshold')) +
                     '; modeled packet: ' + _safe(recipient.get('packet')) + '; threshold: ' + outcome)
    for key, label in (('assumptions', 'Assumptions'), ('limitations', 'Limits'), ('evidence', 'Evidence')):
        lines.append(label + ':')
        lines.extend('  - ' + _safe(value) for value in scenario.get(key, []))
    lines.append('This is a conditional packet/DT comparison, not a combat immunity or survival guarantee.')
    return lines


def _protection_lines(protection, bundle):
    """Retain every sampled part and candidate with its evidence boundary."""
    if not protection:
        return []
    lines = ['', 'Regional component protection:',
             'Status: ' + _safe(protection.get('status', 'unknown')),
             'Summary: ' + _safe(protection.get('summary')),
             'Threat: ' + _safe(protection.get('threat_id')),
             'Approach: ' + _safe(protection.get('direction')),
             'Build identity: ' + _plain(protection.get('build_id')),
             'Geometry identity: ' + _plain(protection.get('geometry_id')),
             'Evidence scope: ' + _safe(protection.get('evidence_scope', 'sampled hypothetical paths')),
             'Audited game version: ' + _safe(bundle.get('damage_model', {}).get('game_version', 'unknown'))]
    for ship in protection.get('ships', []):
        lines.extend(['', 'Ship: ' + _safe(ship.get('ship_name')),
                      '  Ship key: ' + _plain(ship.get('ship_key')),
                      '  Status: ' + _safe(ship.get('status', 'unknown')),
                      '  Summary: ' + _safe(ship.get('summary'))])
        if 'damage_reduction' in ship:
            lines.extend(['  Modeled damage-reduction fraction: ' + _safe(ship['damage_reduction']),
                          '  DR basis: ' + _safe(ship.get('dr_provenance'))])
        for part in ship.get('parts', []):
            lines.extend([
                '  Socket: ' + _plain(part.get('socket_key')) + '; component: ' + _safe(part.get('component')),
                '    Region: ' + _safe(part.get('region')) + '; status: ' + _safe(part.get('status', 'unknown')),
                '    Worst sampled packet: ' + _safe(part.get('worst_packet')) + '; DT: ' + _safe(part.get('threshold')) +
                '; margin: ' + _safe(part.get('margin')),
                '    Tested paths: ' + _safe(part.get('tested_paths')) + '; unknown paths: ' + _safe(part.get('unknown_paths')),
                '    Supporting sockets: ' + ', '.join(_plain(v) for v in part.get('supporting_sockets', [])),
                '    Supporting-part DT status: ' + _safe(part.get('support_status', 'unknown')),
                '    Reason: ' + _safe(part.get('reason')),
            ])
            for sample in part.get('paths', []):
                lines.extend([
                    '    Probe ' + _safe(sample.get('index')) + ': ' + _safe(sample.get('status', 'unknown')) +
                    '; packet: ' + _safe(sample.get('packet')) + '; margin: ' + _safe(sample.get('margin')),
                    '      Recipients: ' + ', '.join(_plain(v) for v in sample.get('recipients', [])),
                    '      Hypothetical internal geometry: ' + _safe(sample.get('geometry')),
                ])
                if sample.get('reason'):
                    lines.append('      Limit: ' + _safe(sample['reason']))
        for suggestion in ship.get('suggestions', []):
            lines.extend([
                '  Candidate change: ' + _safe(suggestion.get('summary')),
                '    Socket: ' + _plain(suggestion.get('socket_key')) + '; component: ' + _safe(suggestion.get('component')) +
                '; previous component: ' + _safe(suggestion.get('previous_component')),
                '    Target sockets: ' + ', '.join(_plain(v) for v in suggestion.get('target_sockets', [])),
                '    Sampled margin before: ' + _safe(suggestion.get('before_margin')) +
                '; after: ' + _safe(suggestion.get('after_margin')),
            ])
            lines.extend('    Limit: ' + _safe(v) for v in suggestion.get('limitations', []))
    lines.extend('Limit: ' + _safe(v) for v in protection.get('limitations', []))
    lines.extend('Geometry evidence: ' + _safe(v) for v in protection.get('provenance', []))
    lines.extend('Damage-model evidence: ' + _safe(v) for v in bundle.get('damage_model', {}).get('evidence', []))
    lines.append('Within DT on sampled paths does not certify an immune region. HP loss and disabled functions remain possible.')
    return lines


def _report_text(result, bundle, role_id):
    lines = [
        'Fleet design review',
        'Fleet: ' + _safe(result.get('fleet_name', 'Unnamed fleet')),
        'Declared points: ' + _safe(result.get('declared_points', 'unknown')),
        'Intended role: ' + _safe(role_id or 'not specified'),
        'Investment posture: ' + _safe(result.get('investment', 'standard')),
        'Bundle: ' + _safe(bundle.get('bundle_id', 'unknown')),
        'Catalog: ' + _safe(bundle.get('catalog_version', 'unknown')),
        '', 'Scope and limitations:',
    ]
    lines.extend('- ' + _safe(v) for v in dict.fromkeys((*_SCOPE, *result.get('limitations', []))))
    lines.extend(['', 'Automated findings:'])
    findings = result.get('findings', [])
    if not findings:
        lines.append('No automated findings were produced. This is not a quality verdict.')
    for index, finding in enumerate(findings, 1):
        lines.extend([
            f"{index}. {_safe(finding.get('title', 'Review question'))}",
            '  Ship: ' + _safe(finding.get('ship_name') or 'Fleet'),
            '  Ship key: ' + _safe(finding.get('ship_key', '')),
            '  Dimension: ' + _safe(finding.get('dimension', '')),
            '  Severity: ' + _safe(finding.get('severity', '')),
            '  Check: ' + _safe(finding.get('check_id', '')),
            '  Advice: ' + _safe(finding.get('advice_id', '')),
            '  ' + _safe(finding.get('message', '')),
        ])
        lines.extend('  Evidence: ' + _safe(v) for v in finding.get('evidence', []))
        if finding.get('reason'):
            lines.append('  Reason: ' + _safe(finding['reason']))
        lines.append('  Attribution: ' + _safe(finding.get('author', 'community guidance')))
        lines.append('  Curated: ' + _safe(finding.get('curated', 'unknown')))
        lines.append('  Verified game version: ' + _safe(finding.get('verified_version') or 'not asserted'))
        lines.extend('  Provider: ' + _safe(v) for v in finding.get('providers', []))
        if finding.get('source_url'):
            lines.append('  Source: ' + _safe(finding['source_url']))
        lines.append('')
    lines.append('Unknown identifiers:')
    lines.extend(_safe(v) for v in result.get('unknown_ids', []))
    if not result.get('unknown_ids'):
        lines.append('None reported; this does not establish current game compatibility.')
    lines.extend(_damage_lines(result))
    lines.extend(_protection_lines(result.get('protection'), bundle))
    lines.extend(['', 'Manual design review:'])
    lines.extend(_guide_lines(bundle, role_id, result.get('strategy'), result.get('investment', 'standard')))
    return '\n'.join(lines) + '\n'


def _review_embed(result, role_id):
    findings = result.get('findings', [])
    description = (
        f"Declared points: {_safe(result.get('declared_points', 'unknown'))} · "
        f"Intended role: {_safe(role_id or 'not specified')}\n"
        f"Investment: {_safe(result.get('investment', 'standard'))}\n"
        f'{len(findings)} automated findings. '
        'The attached report includes every finding, evidence and manual review question.'
    )
    embed = discord.Embed(
        title=_clip('Fleet review: ' + _safe(result.get('fleet_name', 'Unnamed fleet')), 256),
        description=_clip(description, 700), color=Config.EMBED_COLOR,
    )
    scenario = result.get('damage_scenario')
    if scenario is not None:
        state, color = _STACK_STATES.get(scenario.get('status'), _STACK_STATES['unknown'])
        embed.color = discord.Color(color)
        _field(embed, state, _clip(_safe(scenario.get('summary', 'Unknown conditional scenario.')), 650) +
               '\nExplicit assumed recipients and DR only. Read assumptions and limits in the report; '
               'no combat immunity or survival guarantee. HP loss and disabled functions remain possible.')
    protection = result.get('protection')
    if protection:
        parts = [part for ship in protection.get('ships', []) for part in ship.get('parts', [])]
        within = sum(p.get('status') == 'within-dt' and p.get('support_status') == 'within-dt' for p in parts)
        exceeded = sum(p.get('status') == 'threshold-exceeded' or
                       (p.get('status') == 'within-dt' and p.get('support_status') == 'vulnerable') for p in parts)
        unknown = len(parts) - within - exceeded
        if scenario is None:
            color = 0x808080 if protection.get('status') != 'assessed' or unknown or not parts else (0xE0A000 if exceeded else 0x3498DB)
            embed.color = discord.Color(color)
        counts = (f'🔵 {within} within sampled DT with known support · 🟠 {exceeded} target/support breaches · '
                  f'⚪ {unknown} unknown target/support components.'
                  if parts else '⚪ Component coverage unavailable.')
        _field(embed, 'Regional protection coverage',
               _clip(_safe(protection.get('summary', 'Coverage unknown.')), 420) +
               '\n' + counts + '\n'
               'Sampled paths only; HP loss and disabled functions remain possible. No combat immunity guarantee.')
        for ship in protection.get('ships', [])[:3]:
            candidates = len(ship.get('suggestions', []))
            _field(embed, _safe(ship.get('ship_name') or ship.get('ship_key') or 'Ship') + ' — protection',
                   _clip(_safe(ship.get('summary')), 440) +
                   (f'\n{candidates} candidate changes in the report; check fitting and tradeoffs in game.' if candidates else ''))
    if not findings:
        _field(embed, 'Review result',
               'No automated findings were produced. This is not a quality verdict; '
               'check the manual questions and limitations.')
    for finding in findings[:_SUMMARY_FINDINGS]:
        _field(embed, finding.get('title', 'Review question'), _clip(
            _safe(finding.get('ship_name') or 'Fleet') + ': ' + _safe(finding.get('message', '')), 600))
    if len(findings) > _SUMMARY_FINDINGS:
        _field(embed, 'More findings', f'All {len(findings)} findings are in the attached report.')
    if result.get('unknown_ids'):
        _field(embed, 'Unknown identifiers',
               f"{len(result['unknown_ids'])} unrecognized identifiers; see the full report.")
    if scenario is None:
        _field(embed, 'Conditional component DT',
               'The report lists supported reinforced socket keys and !fleetcheck calculator usage. '
               'Select recipients and an assumed DR explicitly; placement and combat protection are not inferred.')
    _field(embed, 'Scope', '\n'.join(_SCOPE))
    if result.get('limitations'):
        _field(embed, 'Review limitations', '\n'.join(_safe(v) for v in result['limitations']))
    embed.set_footer(text='Read-only advice. Uploaded fleet unchanged.')
    return embed


class FleetStrategyCog(commands.Cog, name='Fleet Design'):
    """Shipbuilding principles and read-only fleet design reviews."""

    def __init__(self, bot, knowledge_dir=None):
        self.bot = bot
        self.bundle = None
        self.geometry = None
        self.geometry_problem = None
        geometry_path = os.getenv('FLEET_GEOMETRY_PATH')
        if geometry_path:
            try:
                self.geometry = load_geometry(geometry_path)
            except (ValueError, OSError):
                logger.warning('Fleet geometry dataset could not be loaded', exc_info=True)
                self.geometry_problem = 'The configured geometry dataset could not be loaded; automatic protection is unknown.'
        try:
            self.bundle = load_bundle(knowledge_dir or KNOWLEDGE_DIR)
        except Exception:
            # A missing/malformed deployment bundle must not stop the server bot.
            logger.exception('Fleet design bundle could not be loaded')

    async def _ready(self, ctx, role, *, calculator=False):
        try:
            role_id, investment, scenario, protection = _arguments(role, calculator=calculator)
        except FleetInputError as error:
            await _send(ctx, _clip(_safe(error), 1800))
            return False, None, 'standard', None, None
        if self.bundle is None:
            await _send(ctx, 'Fleet design guidance is unavailable because its knowledge bundle could not be loaded.')
            return False, None, investment, None, None
        return True, role_id, investment, scenario, protection

    @commands.hybrid_command(name='shipbuilding', description='Read shipbuilding principles and conditional component protection guidance.')
    @app_commands.describe(options='Optional role and --lean, for example: frontline --lean')
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def shipbuilding(self, ctx, *, options: Optional[str] = None):
        """Explain ship design principles for 3000-point team PvP.

        Usage: !shipbuilding [role] [--lean]
        Slash: /shipbuilding options:frontline --lean
        Examples:
        - !shipbuilding - read the design principles and complete guide
        - !shipbuilding frontline - focus on a frontline ship's responsibilities
        - !shipbuilding denial --lean - plan a deliberately expendable attack ship
        The guide explains conditional component DT comparisons with !fleetcheck and their limits.
        Roles: frontline, skirmish, denial, capture, scouting, missile-support, carrier-support.
        """
        ready, role_id, investment, _, _ = await self._ready(ctx, options)
        if not ready:
            return
        await _defer(ctx)
        base = self.bundle['strategy']
        embed = discord.Embed(title=_clip(_safe(base['title']), 256),
                              description=_clip(_safe(base.get('context', '')), 650), color=Config.EMBED_COLOR)
        selected = _role(self.bundle, role_id)
        if selected:
            _field(embed, selected['title'], _clip(_safe(selected['summary']), 750))
            _field(embed, 'Dependencies', _clip('\n'.join(_safe(v) for v in selected['dependencies']), 650))
        if investment == 'lean':
            _field(embed, 'Deliberate lean investment',
                   'Accept specified losses to protection or recovery for a clear payoff. Essential weapon dependencies still apply.')
        for principle in base['principles']:
            _field(embed, principle['title'], _clip(_safe(principle['summary']), 400))
        _field(embed, 'Complete guide', 'The attachment includes every principle, role question and example. '
               'Use /fleetcheck with one .fleet or .ship attachment for a read-only review. '
               'It also lists reinforced socket keys for explicit conditional DT comparisons; see the guide for usage and limits.')
        report = '\n'.join(_guide_lines(self.bundle, role_id, investment=investment) + ['', 'Scope:', *_SCOPE]) + '\n'
        with closing(discord.File(io.BytesIO(report.encode('utf-8')), filename='shipbuilding-guide.txt')) as document:
            await _send(ctx, embed=embed, file=document)

    @commands.hybrid_command(name='fleetcheck', aliases=['shipcheck'], description='Review a fleet or ship file with evidence and conditional protection checks.')
    @app_commands.describe(attachment='One .fleet or .ship file, up to 2 MiB',
                           options='Role, --lean, --threat hei --direction bow, or explicit --stack/--threat/--dr flags')
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def fleetcheck(self, ctx, attachment: Optional[discord.Attachment] = None, *, options: Optional[str] = None):
        """Review one attached fleet with evidence and manual design questions.

        Usage: !fleetcheck [role] [--lean] [--stack SHIP_KEY:SOCKET,SOCKET --threat ID --dr FRACTION]
        Slash: /fleetcheck attachment:your-file options:frontline --lean
        In servers use slash commands or mention the bot; prefix examples work in DMs.
        Examples:
        - !fleetcheck - attach exactly one .fleet or .ship file for read-only advice
        - !fleetcheck skirmish - review the attached fleet against its intended role
        - !shipcheck denial --lean - review a lean ship template
        - !fleetcheck --threat 450-ap --direction port - review sampled paths from the port side
        - !fleetcheck --stack ship-1:SocketA,SocketB --threat hei --dr 0.2 - compare explicitly selected recipients with assumed 20% DR
        Use exact ship/socket keys from a first report. Supply all three calculator flags together.
        Manual colors: blue within DT; amber threshold exceeded; grey unknown. Regional reports also flag support risk.
        No combat immunity guarantee.
        Files must be at most 2 MiB. Returns a summary and complete text report; no fleet edits or score.
        Roles: frontline, skirmish, denial, capture, scouting, missile-support, carrier-support.
        """
        ready, role_id, investment, scenario, protection = await self._ready(ctx, options, calculator=True)
        if not ready:
            return
        if getattr(ctx, 'interaction', None) is not None:
            attachments = [attachment] if attachment is not None else []
        else:
            # The prefix converter selects one attachment, but preserve the
            # exactly-one rule when the original message contains more files.
            attachments = list(getattr(getattr(ctx, 'message', None), 'attachments', ()))
            if not attachments and attachment is not None:
                attachments = [attachment]
        error = None
        if len(attachments) != 1:
            error = 'Use /fleetcheck with exactly one .fleet or .ship attachment (maximum 2 MiB), or attach it with a mention/DM command.'
        elif not attachments[0].filename.lower().endswith(('.fleet', '.ship')):
            error = 'Expected a .fleet or .ship attachment.'
        elif attachments[0].size > MAX_FLEET_BYTES:
            error = 'The fleet attachment is too large; the limit is 2 MiB.'
        if error:
            await _send(ctx, error)
            return
        await _defer(ctx)
        advice_cog = self.bot.get_cog('Advice')
        removed_ids = getattr(advice_cog, 'removed_ids', None)
        excluded = tuple(removed_ids) if removed_ids is not None else None

        def analyze(data):
            snapshot = parse_design(data)
            if excluded is not None:
                result = review_fleet(snapshot, self.bundle, role=role_id, excluded_entry_ids=excluded,
                                      investment=investment, geometry=getattr(self, 'geometry', None),
                                      protection_threat=protection['threat_id'], protection_direction=protection['direction'])
            else:
                result = {
                    'fleet_name': snapshot.get('fleet_name', snapshot.get('name', 'Unnamed fleet')),
                    'declared_points': snapshot.get('declared_points'),
                    'investment': investment,
                    'findings': [], 'unknown_ids': [], 'limitations': [_NO_COMMUNITY_STATE],
                    'damage_inventory': damage_inventory(snapshot, self.bundle),
                    'protection': review_protection(snapshot, self.bundle, geometry=getattr(self, 'geometry', None),
                                                    **protection),
                }
            if getattr(self, 'geometry_problem', None) and result.get('protection'):
                result['protection'].setdefault('limitations', []).append(self.geometry_problem)
            if scenario is not None:
                result['damage_scenario'] = evaluate_stack(snapshot, self.bundle, **scenario)
                result['damage_scenario'].setdefault('ship_key', scenario['ship_key'])
                result['damage_scenario'].setdefault('socket_keys', scenario['socket_keys'])
            return result

        try:
            data = await attachments[0].read()
            result = await asyncio.to_thread(analyze, data)
        except FleetInputError as error:
            await _send(ctx, 'Unable to review this fleet: ' + _clip(_safe(error), 1200))
            return
        except (discord.HTTPException, OSError):
            await _send(ctx, 'The attachment could not be read. Please attach the .fleet or .ship file again.')
            return
        except BundleError:
            logger.exception('Fleet design bundle failed during review')
            await _send(ctx, 'Fleet review is unavailable because its knowledge bundle could not be used.')
            return
        report = await asyncio.to_thread(_report_text, result, self.bundle, role_id)
        encoded = report.encode('utf-8')
        if len(encoded) > _REPORT_BYTE_LIMIT:
            await _send(ctx, 'The complete report is too large to attach. Review individual ship templates or a smaller fleet.')
            return
        with closing(discord.File(io.BytesIO(encoded), filename='fleet-review.txt')) as document:
            await _send(ctx, embed=_review_embed(result, role_id), file=document)

    @shipbuilding.error
    @fleetcheck.error
    async def strategy_error(self, ctx, error):
        """Handle decorator failures without duplicate global error messages."""
        error.fleet_strategy_handled = True
        if isinstance(error, commands.MaxConcurrencyReached):
            message = 'A fleet design request is already running. Please try again when it finishes.'
        elif isinstance(error, commands.CommandOnCooldown):
            message = f'Try this command again in {error.retry_after:.0f}s.'
        elif isinstance(error, commands.UserInputError):
            message = ('Use /shipbuilding or /fleetcheck with an attachment. Put roles and flags in options. '
                       'For mention/DM commands: !shipbuilding [role] [--lean] or ' + _STACK_USAGE +
                       ' with one .fleet or .ship attachment. Calculator flags are optional as a group.')
        else:
            logger.error('Fleet design command failed', exc_info=(type(error), error, error.__traceback__))
            message = 'Fleet design guidance could not complete this request. The error has been logged.'
        await _send(ctx, message)
