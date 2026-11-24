#!/usr/bin/env python3
"""Production deploy steps that run ON the Oracle VM.

deploy-to-oracle.sh pipes this file over ssh (`python3 - <phase> ...`), so it
must stay standard-library only and Python 3.9 compatible (the VM's python3).
It encodes the 2.10/2.11 release procedure (docs/releases/):

  preflight  read-only: live container, compose project, intent-off env, and
             the exact compose diff this deploy would make
  backup     snapshot .env + compose, tag a rollback image, online SQLite
             backup proven by integrity check and a restored copy
  load       optional: docker load a CI release archive, verify checksum and
             revision label
  apply      pin the image, bind 8000 to loopback, ensure DJANGO_SECRET_KEY,
             then `docker compose up -d --no-build --force-recreate`
  status     prove the result. Exit 2 on hard failures (the caller rolls
             back), exit 3 on soft ones (a human decides)
  rollback   restore the snapshot and recreate

Never builds on the VM and never prints environment values: secrets are
reported as booleans.
"""
import argparse
import datetime
import difflib
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Must equal nebulous_project.settings._PUBLIC_PLACEHOLDER_KEYS (a test enforces it).
PLACEHOLDER_SECRET_KEYS = frozenset({
    'django-insecure-change-this-in-production',
    'your_django_secret_here',
    'your-generated-secret-key',
})
LOOPBACK_MAPPING = '"127.0.0.1:8000:8000"'
BASELINE_TABLES = (
    'nebulous_bot_guildconfig',
    'nebulous_bot_adviceproposal',
    'nebulous_bot_gamesession',
    'nebulous_bot_playersnapshot',
)
GATEWAY_READY = 'has connected to Discord!'
MONITORING_STARTED = 'Server monitoring started'
LOG_ERROR_MARKERS = ('ERROR', 'Traceback', 'heartbeat blocked')
OK, PRECONDITION, HARD, SOFT = 0, 1, 2, 3

_IMAGE_LINE = re.compile(r'^(?P<indent>[ \t]+)image:[ \t]*(?P<value>\S+)[ \t]*$', re.MULTILINE)
_PORT_8000 = re.compile(
    r'^(?P<prefix>[ \t]*-[ \t]*)["\']?(?:(?P<ip>[0-9.]+|\[[0-9A-Fa-f:]*\]):)?8000:8000(?:/tcp)?["\']?[ \t]*$',
    re.MULTILINE,
)


class DeployError(Exception):
    """A precondition failed; nothing further should happen."""


# --- pure functions (unit-tested in nebulous_bot/tests/test_deploy_hardening.py) ---

def rewrite_compose(text, image):
    """Pin the service image and bind port 8000 to loopback.

    Returns (new_text, changes), where changes lists what moved ('image',
    'ports'). Raises DeployError unless there is exactly one image line and
    one 8000 mapping, so an unexpected compose layout stops the deploy.
    """
    changes = []
    images = list(_IMAGE_LINE.finditer(text))
    if len(images) != 1:
        raise DeployError('expected exactly one image: line in compose, found %d' % len(images))
    match = images[0]
    if match.group('value') != image:
        text = text[:match.start()] + match.group('indent') + 'image: ' + image + text[match.end():]
        changes.append('image')
    ports = list(_PORT_8000.finditer(text))
    if len(ports) != 1:
        raise DeployError('expected exactly one 8000:8000 port mapping in compose, found %d' % len(ports))
    match = ports[0]
    if match.group('ip') != '127.0.0.1':
        text = text[:match.start()] + match.group('prefix') + LOOPBACK_MAPPING + text[match.end():]
        changes.append('ports')
    return text, changes


def env_value(raw):
    value = (raw or '').strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        value = value[1:-1]
    return value


def secret_key_is_real(raw):
    """Same rule as nebulous_project.settings.resolve_secret_key."""
    value = env_value(raw)
    return bool(value) and value not in PLACEHOLDER_SECRET_KEYS


def parse_env(text):
    values = {}
    for line in text.replace('\r\n', '\n').split('\n'):
        name, sep, value = line.partition('=')
        if sep and name.strip() and not name.lstrip().startswith('#'):
            values[name.strip()] = env_value(value)
    return values


def update_env(text, deployment_time, make_secret=None):
    """Return (new_text, changed_names) for the live .env.

    Generates DJANGO_SECRET_KEY only when it is missing, blank or a public
    placeholder; stamps DEPLOYMENT_TIME. Every other line is kept verbatim.
    """
    make_secret = make_secret or (lambda: secrets.token_urlsafe(50))
    lines = text.replace('\r\n', '\n').split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    wanted = {'DEPLOYMENT_TIME': deployment_time}
    out, seen, changed = [], set(), []
    for line in lines:
        name, sep, value = line.partition('=')
        key = name.strip()
        if not sep or key not in ('DJANGO_SECRET_KEY', 'DEPLOYMENT_TIME'):
            out.append(line)
            continue
        if key in seen:  # collapse duplicates onto the first occurrence
            changed.append(key)
            continue
        seen.add(key)
        if key == 'DJANGO_SECRET_KEY':
            if secret_key_is_real(value):
                out.append(line)
            else:
                wanted[key] = make_secret()
        if key in wanted:
            out.append(key + '=' + wanted[key])
            changed.append(key)
    if 'DJANGO_SECRET_KEY' not in seen:
        out.append('DJANGO_SECRET_KEY=' + make_secret())
        changed.append('DJANGO_SECRET_KEY')
    if 'DEPLOYMENT_TIME' not in seen:
        out.append('DEPLOYMENT_TIME=' + deployment_time)
        changed.append('DEPLOYMENT_TIME')
    return '\n'.join(out) + '\n', sorted(set(changed))


def loopback_only(bindings):
    """True if every published 8000/tcp binding is on 127.0.0.1."""
    entries = (bindings or {}).get('8000/tcp') or []
    return bool(entries) and all((b or {}).get('HostIp') == '127.0.0.1' for b in entries)


# --- host helpers ---

def say(message):
    print(message, flush=True)


def require(condition, message):
    if not condition:
        raise DeployError(message)


def run(cmd, cwd=None, timeout=900):
    proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True, timeout=timeout)
    if proc.returncode != 0:
        raise DeployError('`%s` failed (%d): %s' % (' '.join(cmd[:5]), proc.returncode, proc.stdout.strip()[-600:]))
    return proc.stdout


def inspect(ref, kind='container'):
    proc = subprocess.run(['docker', kind, 'inspect', ref], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True)
    return json.loads(proc.stdout)[0] if proc.returncode == 0 else None


def container_env(meta):
    return dict(item.split('=', 1) for item in meta['Config'].get('Env') or [] if '=' in item)


def same_path(a, b):
    return bool(a) and os.path.realpath(str(a)) == os.path.realpath(str(b))


def atomic_write(path, text, mode):
    path = Path(path)
    temporary = path.with_name(path.name + '.deploy-tmp')
    with open(temporary, 'w', newline='\n') as handle:
        handle.write(text)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def table_counts(db, tables):
    return {t: db.execute('select count(*) from "%s"' % t.replace('"', '""')).fetchone()[0] for t in tables}


def listeners_8000():
    if not shutil.which('ss'):
        return None
    out = subprocess.run(['ss', '-ltnH'], stdout=subprocess.PIPE, universal_newlines=True).stdout
    return sorted({line.split()[3] for line in out.splitlines()
                   if len(line.split()) > 3 and line.split()[3].endswith(':8000')})


def mem_available_mib():
    try:
        with open('/proc/meminfo') as handle:
            for line in handle:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def compose_path(a):
    return Path(a.repo) / 'docker-compose.yml'


def recreate(a):
    say('Recreating %s with --no-build (no image build on the VM)...' % a.container)
    run(['docker', 'compose', 'up', '-d', '--no-build', '--force-recreate', a.service], cwd=a.repo, timeout=600)


def wait_for(predicate, timeout, interval=5):
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if result or time.monotonic() >= deadline:
            return result
        time.sleep(interval)


def wait_healthy(a, image, timeout):
    """Return (meta, health) once the container runs `image` and settles."""
    def settled():
        meta = inspect(a.container)
        if not meta or meta['Image'] != image or not meta['State'].get('Running'):
            return None
        health = (meta['State'].get('Health') or {}).get('Status', 'none')
        return (meta, health) if health in ('healthy', 'unhealthy') else None
    result = wait_for(settled, timeout)
    if result:
        return result
    meta = inspect(a.container)
    return meta, ((meta or {}).get('State', {}).get('Health') or {}).get('Status', 'missing')


def target_image(a, release):
    if a.accepted:
        return json.loads((release / 'accepted-image.json').read_text())['image']
    return json.loads((release / 'production-backup' / 'backup-report.json').read_text())['image']


# --- phases ---

def phase_preflight(a):
    meta = inspect(a.container)
    require(meta is not None, 'container %s not found' % a.container)
    state = meta['State']
    require(state.get('Running'), 'container is not running')
    require(not state.get('OOMKilled'), 'container was OOM-killed')
    labels = meta['Config'].get('Labels') or {}
    require(same_path(labels.get('com.docker.compose.project.working_dir'), a.repo),
            'container was not started from %s' % a.repo)
    require(same_path(labels.get('com.docker.compose.project.config_files'), compose_path(a)),
            'container was not started from %s' % compose_path(a))
    require(labels.get('com.docker.compose.service') == a.service, 'compose service is not %r' % a.service)

    env_text = (Path(a.repo) / '.env').read_text()
    env = parse_env(env_text)
    require(env.get('DISCORD_MESSAGE_CONTENT') == 'false',
            'live .env must keep DISCORD_MESSAGE_CONTENT=false (privileged intents stay off)')
    _, env_changes = update_env(env_text, '<deploy time>', lambda: '<generated>')

    planned = '<image loaded from the archive>' if a.new_image else meta['Image']
    old = compose_path(a).read_text()
    new, compose_changes = rewrite_compose(old, planned)
    if not a.new_image:
        require(set(compose_changes) <= {'ports'},
                'a config-only deploy may change only the port binding, not %s' % compose_changes)

    say('Live container: image %s, revision %s' % (meta['Image'], labels.get('org.opencontainers.image.revision', '?')))
    say('  started %s, restarts %s, health %s' % (state.get('StartedAt'), meta.get('RestartCount'),
                                                  (state.get('Health') or {}).get('Status', 'none')))
    say('  published 8000 loopback-only: %s; listeners: %s' % (
        loopback_only(meta['HostConfig'].get('PortBindings')), listeners_8000() or 'ss unavailable'))
    say('  container DJANGO_SECRET_KEY real: %s' % secret_key_is_real(container_env(meta).get('DJANGO_SECRET_KEY')))
    say('Host: MemAvailable %s MiB; free on %s: %d MiB' % (
        mem_available_mib(), a.release_root, shutil.disk_usage(a.release_root).free // (1 << 20)))
    say('.env keys this deploy sets (values never shown): %s' % (', '.join(env_changes) or 'none'))
    diff = ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        'docker-compose.yml (live)', 'docker-compose.yml (after)'))
    say('Compose change:\n' + (diff or '  (none)'))
    return OK


def phase_backup(a):
    os.umask(0o077)
    release = Path(a.release)
    backup = release / 'production-backup'
    backup.mkdir(parents=True)  # a fresh stamp per deploy; refuse to overwrite one
    meta = inspect(a.container)
    require(meta is not None and meta['State'].get('Running'), 'container is not running')
    for name in ('.env', 'docker-compose.yml'):
        shutil.copy2(str(Path(a.repo) / name), str(backup / name))
        os.chmod(str(backup / name), 0o600)

    rollback_tag = 'nebulous-bot:rollback-%s' % a.stamp
    run(['docker', 'tag', meta['Image'], rollback_tag])
    tagged = inspect(rollback_tag, 'image')
    require(tagged is not None and tagged['Id'] == meta['Image'], 'rollback tag does not point at the live image')

    source = sqlite3.connect('file:%s?mode=ro' % a.db, uri=True, timeout=10)
    destination = sqlite3.connect(str(backup / 'db.sqlite3'))
    deadline = time.monotonic() + 180

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError('database backup took longer than 180 s')

    source.backup(destination, pages=256, progress=progress, sleep=0.1)
    require(destination.execute('pragma integrity_check').fetchone() == ('ok',), 'backup failed integrity_check')
    tables = [r[0] for r in destination.execute(
        "select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
    counts = table_counts(destination, tables)
    destination.close()
    source.close()

    restore = backup / 'restore-check.sqlite3'
    shutil.copy2(str(backup / 'db.sqlite3'), str(restore))
    restored = sqlite3.connect(str(restore))
    require(restored.execute('pragma integrity_check').fetchone() == ('ok',), 'restored copy failed integrity_check')
    require(table_counts(restored, tables) == counts, 'restored copy row counts differ')
    restored.close()
    restore.unlink()

    labels = meta['Config'].get('Labels') or {}
    report = {
        'stamp': a.stamp, 'image': meta['Image'], 'rollback_tag': rollback_tag,
        'revision': labels.get('org.opencontainers.image.revision'),
        'started_at': meta['State'].get('StartedAt'), 'integrity': 'ok', 'restore_check': 'ok',
        'tables': counts, 'env_names': sorted(container_env(meta)),
    }
    (backup / 'backup-report.json').write_text(json.dumps(report, indent=2))
    say('Backup %s: image %s tagged %s; DB integrity ok, restore check ok; %s' % (
        backup, meta['Image'][:19], rollback_tag,
        ', '.join('%s=%s' % (t.replace('nebulous_bot_', ''), counts.get(t)) for t in BASELINE_TABLES)))
    return OK


def phase_load(a):
    release = Path(a.release)
    archive = release / 'nebulous-bot.tar.gz'
    expected = (release / 'SHA256SUMS').read_text().split()
    require(len(expected) >= 2 and expected[1].lstrip('*') == archive.name, 'SHA256SUMS does not name %s' % archive.name)
    require(sha256_file(archive) == expected[0], 'archive checksum mismatch on the VM')
    revision = (release / 'source-revision.txt').read_text().strip()
    out = run(['docker', 'load', '-i', str(archive)], timeout=1800)
    refs = re.findall(r'Loaded image(?: ID)?: (\S+)', out)
    require(refs, 'docker load reported no image: %s' % out.strip()[-300:])
    image = inspect(refs[-1], 'image')
    require(image is not None, 'loaded image %s not found' % refs[-1])
    label = (image['Config'].get('Labels') or {}).get('org.opencontainers.image.revision')
    require(label == revision, 'image revision label %r does not match source-revision.txt %r' % (label, revision))
    (release / 'accepted-image.json').write_text(json.dumps({'image': image['Id'], 'revision': revision}, indent=2))
    say('Loaded %s (revision %s); checksum verified on the VM' % (image['Id'], revision))
    return OK


def phase_apply(a):
    release = Path(a.release)
    report = json.loads((release / 'production-backup' / 'backup-report.json').read_text())
    require(report.get('integrity') == 'ok' and report.get('restore_check') == 'ok', 'no verified backup for this release')
    meta = inspect(a.container)
    require(meta is not None and meta['Image'] == report['image'], 'production image changed since the backup')
    image = target_image(a, release)
    require(inspect(image, 'image') is not None, 'target image %s is not on the VM' % image)

    env_path = Path(a.repo) / '.env'
    new_env, env_changes = update_env(env_path.read_text(), datetime.datetime.now(datetime.timezone.utc).isoformat())
    require(parse_env(new_env).get('DISCORD_MESSAGE_CONTENT') == 'false', 'refusing to drop DISCORD_MESSAGE_CONTENT=false')
    new_compose, compose_changes = rewrite_compose(compose_path(a).read_text(), image)
    if not a.accepted:
        require(set(compose_changes) <= {'ports'}, 'config-only deploy would change %s' % compose_changes)

    atomic_write(env_path, new_env, 0o600)
    atomic_write(compose_path(a), new_compose, os.stat(str(compose_path(a))).st_mode & 0o777)
    (release / 'apply-report.json').write_text(json.dumps(
        {'image': image, 'env_changes': env_changes, 'compose_changes': compose_changes}, indent=2))
    say('Applied: .env keys %s; compose %s' % (env_changes, compose_changes or 'unchanged'))
    recreate(a)
    return OK


def phase_status(a):
    release = Path(a.release)
    baseline = json.loads((release / 'production-backup' / 'backup-report.json').read_text())
    image = target_image(a, release)
    hard, soft, facts = [], [], {}

    meta, health = wait_healthy(a, image, a.health_timeout)
    facts['health'] = health
    if not meta:
        hard.append('container %s is gone' % a.container)
    else:
        state = meta['State']
        env = container_env(meta)
        facts.update(image=meta['Image'], started_at=state.get('StartedAt'), restarts=meta.get('RestartCount'),
                     oom=state.get('OOMKilled'), listeners=listeners_8000())
        if meta['Image'] != image:
            hard.append('running image %s, expected %s' % (meta['Image'], image))
        if not state.get('Running'):
            hard.append('container is not running')
        if state.get('OOMKilled'):
            hard.append('container was OOM-killed')
        if meta.get('RestartCount'):
            hard.append('container restarted %s time(s)' % meta.get('RestartCount'))
        if health != 'healthy':
            hard.append('health is %r' % health)
        if not loopback_only(meta['NetworkSettings'].get('Ports')):
            hard.append('8000 is not bound to 127.0.0.1 only')
        if facts['listeners'] is not None and any(not l.startswith('127.0.0.1:') for l in facts['listeners']):
            hard.append('host listeners on 8000: %s' % facts['listeners'])
        if not secret_key_is_real(env.get('DJANGO_SECRET_KEY')):
            hard.append('container has no real DJANGO_SECRET_KEY')
        if env.get('DISCORD_MESSAGE_CONTENT') != 'false':
            hard.append('DISCORD_MESSAGE_CONTENT is not false')

    if not hard:
        try:
            with urllib.request.urlopen(a.health_url, timeout=20) as response:
                facts['http_health'] = response.status
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            facts['http_health'] = repr(exc)[:120]
        if facts['http_health'] != 200:
            soft.append('GET %s -> %s' % (a.health_url, facts['http_health']))

        db = sqlite3.connect('file:%s?mode=ro' % a.db, uri=True, timeout=10)
        facts['quick_check'] = db.execute('pragma quick_check').fetchone()[0]
        names = [t for t in BASELINE_TABLES if t in baseline['tables']]
        counts = table_counts(db, names)
        db.close()
        if facts['quick_check'] != 'ok':
            soft.append('database quick_check: %s' % facts['quick_check'])
        shrunk = [t for t in names if counts[t] < baseline['tables'][t]]
        if shrunk:
            soft.append('row counts fell below the backup for %s' % shrunk)

        def logs():
            return subprocess.run(['docker', 'logs', '--since', facts['started_at'], a.container],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True).stdout
        text = wait_for(lambda: (lambda t: t if GATEWAY_READY in t and MONITORING_STARTED in t else None)(logs()),
                        a.gateway_timeout, interval=10) or logs()
        facts['gateway_ready'] = GATEWAY_READY in text
        facts['monitoring_started'] = MONITORING_STARTED in text
        errors = [line for line in text.splitlines() if any(m in line for m in LOG_ERROR_MARKERS)]
        facts['log_error_lines'] = len(errors)
        if not facts['gateway_ready']:
            soft.append('no gateway-ready line within %d s' % a.gateway_timeout)
        if not facts['monitoring_started']:
            soft.append('no monitoring-started line within %d s' % a.gateway_timeout)
        if errors:
            soft.append('%d ERROR/Traceback line(s) since start, first: %s' % (len(errors), errors[0][:160]))

    facts.update(hard=hard, soft=soft, checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    (release / 'production-status.json').write_text(json.dumps(facts, indent=2, default=str))
    for key in ('image', 'started_at', 'health', 'restarts', 'oom', 'listeners', 'http_health', 'quick_check',
                'gateway_ready', 'monitoring_started', 'log_error_lines'):
        if key in facts:
            say('  %-18s %s' % (key, facts[key]))
    for problem in hard:
        say('HARD: ' + problem)
    for problem in soft:
        say('SOFT: ' + problem)
    if hard:
        return HARD
    return SOFT if soft else OK


def phase_rollback(a):
    backup = Path(a.release) / 'production-backup'
    report = json.loads((backup / 'backup-report.json').read_text())
    require(inspect(report['image'], 'image') is not None, 'rollback image %s is missing' % report['image'])
    atomic_write(Path(a.repo) / '.env', (backup / '.env').read_text(), 0o600)
    atomic_write(compose_path(a), (backup / 'docker-compose.yml').read_text(),
                 os.stat(str(compose_path(a))).st_mode & 0o777)
    recreate(a)
    meta, health = wait_healthy(a, report['image'], a.health_timeout)
    require(meta is not None and meta['Image'] == report['image'] and health == 'healthy',
            'rollback did not come back healthy on %s (health %r)' % (report['image'], health))
    say('Rolled back to %s; container healthy' % report['image'])
    return OK


PHASES = {
    'preflight': phase_preflight, 'backup': phase_backup, 'load': phase_load,
    'apply': phase_apply, 'status': phase_status, 'rollback': phase_rollback,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('phase', choices=sorted(PHASES))
    parser.add_argument('--repo', default='/home/opc/NebulousServerDiscordBot')
    parser.add_argument('--data', default='/home/opc/nebulous-data')
    parser.add_argument('--container', default='nebulous-discord-bot')
    parser.add_argument('--service', default='bot')
    parser.add_argument('--release-root', default='/home/opc')
    parser.add_argument('--release', help='this deploy\'s release directory')
    parser.add_argument('--stamp', help='UTC stamp naming the rollback tag')
    parser.add_argument('--accepted', action='store_true', help='target the image recorded by `load`')
    parser.add_argument('--new-image', action='store_true', help='preflight: an image archive will be loaded')
    parser.add_argument('--health-url', default='http://localhost:8000/health/')
    parser.add_argument('--health-timeout', type=int, default=300)
    parser.add_argument('--gateway-timeout', type=int, default=300)
    a = parser.parse_args(argv)
    a.db = str(Path(a.data) / 'db.sqlite3')
    if a.phase != 'preflight' and not a.release:
        parser.error('--release is required for %s' % a.phase)
    if a.phase == 'backup' and not a.stamp:
        parser.error('--stamp is required for backup')
    try:
        return PHASES[a.phase](a)
    except DeployError as exc:
        say('PRECONDITION FAILED (%s): %s' % (a.phase, exc))
        return PRECONDITION


if __name__ == '__main__':
    sys.exit(main())
