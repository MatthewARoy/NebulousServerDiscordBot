"""Guards for settings and deploy tooling in a public repo.

The repo is public, so any default secret or published port is visible to
everyone. These tests are pure-logic: no DB, no network, no Docker.
"""
import ast
import importlib.util
import re
from pathlib import Path

import pytest

from nebulous_project.settings import _PUBLIC_PLACEHOLDER_KEYS, resolve_secret_key

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_DIR = REPO_ROOT / 'deployment'
REMOTE_DEPLOY = DEPLOYMENT_DIR / 'oracle' / 'remote_deploy.py'
DEPLOY_SCRIPT = DEPLOYMENT_DIR / 'oracle' / 'deploy-to-oracle.sh'


def _load_remote_deploy():
    spec = importlib.util.spec_from_file_location('remote_deploy', REMOTE_DEPLOY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rd = _load_remote_deploy()

# The production compose file as the 2.11.0 rollout left it (no secrets in it).
LIVE_COMPOSE = '''services:
  bot:
    image: sha256:f61f43cee0476b89bc4d7b131c288cc936bf433c381ec96f9762231f87d42ada
    build:
      context: .
      dockerfile: deployment/docker/Dockerfile
    container_name: nebulous-discord-bot
    env_file:
      - .env
    environment:
      - DJANGO_SETTINGS_MODULE=nebulous_project.settings
      - PYTHONUNBUFFERED=1
      - DB_PATH=/mnt/data/db.sqlite3
    volumes:
      - /home/opc/nebulous-data:/mnt/data
      - ./logs:/app/logs
    ports:
      - "8000:8000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/').read()"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
'''
LIVE_IMAGE = 'sha256:f61f43cee0476b89bc4d7b131c288cc936bf433c381ec96f9762231f87d42ada'


# --- SECRET_KEY -------------------------------------------------------------

def test_real_secret_from_env_is_used_verbatim():
    real = 'k3y-from-the-vm-env-file-' + 'x' * 40
    assert resolve_secret_key(real) == real


@pytest.mark.parametrize('value', [None, '', '   '])
def test_unset_secret_falls_back_to_random_key(value):
    key = resolve_secret_key(value)
    assert len(key) >= 50  # Django's security.W009 minimum
    assert key not in _PUBLIC_PLACEHOLDER_KEYS


@pytest.mark.parametrize('placeholder', sorted(_PUBLIC_PLACEHOLDER_KEYS))
def test_public_placeholder_is_never_used(placeholder):
    assert resolve_secret_key(placeholder) != placeholder


def test_fallback_keys_are_random_not_a_fixed_default():
    assert resolve_secret_key(None) != resolve_secret_key(None)


def test_placeholder_list_covers_the_old_hardcoded_default():
    assert 'django-insecure-change-this-in-production' in _PUBLIC_PLACEHOLDER_KEYS


def test_remote_deploy_uses_the_same_placeholder_list():
    assert rd.PLACEHOLDER_SECRET_KEYS == _PUBLIC_PLACEHOLDER_KEYS


# --- Published ports in committed compose files --------------------------------

# A compose `ports:` list entry, e.g. - "8000:8000" or - 127.0.0.1:8000:8000/tcp
PORT_ENTRY = re.compile(
    r"""^\s*-\s*["']?(?P<host_ip>(?:\d{1,3}\.){3}\d{1,3}:)?\d+:\d+(?:/(?:tcp|udp))?["']?\s*$"""
)


def _port_mappings():
    for path in sorted(DEPLOYMENT_DIR.rglob('*')):
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        for lineno, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith('#'):
                continue
            match = PORT_ENTRY.match(line)
            if match:
                yield path.relative_to(REPO_ROOT).as_posix(), lineno, line.strip(), match['host_ip']


def test_guard_actually_finds_the_compose_files():
    files = {f for f, *_ in _port_mappings()}
    assert {
        'deployment/docker/docker-compose.yml',
        'deployment/oracle/docker-compose.oracle.yml',
    } <= files


def test_every_published_port_is_loopback_only():
    """Gunicorn serves Django admin on 8000; it must never face the internet.

    Health checks run inside the container and `curl localhost:8000` still
    works on the VM, so nothing needs the port on a public interface.
    """
    exposed = [
        f'{f}:{n}: {line}' for f, n, line, host_ip in _port_mappings()
        if host_ip != '127.0.0.1:'
    ]
    assert not exposed, 'Bind published ports to 127.0.0.1:\n' + '\n'.join(exposed)


# --- remote_deploy.rewrite_compose (the live compose file) --------------------

def test_config_only_rewrite_changes_only_the_ports_line():
    new, changes = rd.rewrite_compose(LIVE_COMPOSE, LIVE_IMAGE)
    assert changes == ['ports']
    old_lines, new_lines = LIVE_COMPOSE.splitlines(), new.splitlines()
    assert len(old_lines) == len(new_lines)
    differing = [(o, n) for o, n in zip(old_lines, new_lines, strict=True) if o != n]
    assert differing == [('      - "8000:8000"', '      - "127.0.0.1:8000:8000"')]


def test_rewrite_is_idempotent():
    once, _ = rd.rewrite_compose(LIVE_COMPOSE, LIVE_IMAGE)
    twice, changes = rd.rewrite_compose(once, LIVE_IMAGE)
    assert twice == once and changes == []


def test_new_image_rewrite_pins_the_image_and_ports():
    new, changes = rd.rewrite_compose(LIVE_COMPOSE, 'sha256:' + 'a' * 64)
    assert changes == ['image', 'ports']
    assert '    image: sha256:' + 'a' * 64 + '\n' in new
    assert LIVE_IMAGE not in new


@pytest.mark.parametrize('mapping', ['"8000:8000"', '8000:8000', '"0.0.0.0:8000:8000"', "'[::]:8000:8000'"])
def test_every_public_8000_form_is_rebound(mapping):
    text = LIVE_COMPOSE.replace('"8000:8000"', mapping)
    new, changes = rd.rewrite_compose(text, LIVE_IMAGE)
    assert changes == ['ports'] and '      - "127.0.0.1:8000:8000"' in new


@pytest.mark.parametrize('broken', [
    LIVE_COMPOSE.replace('    image: ' + LIVE_IMAGE + '\n', ''),
    LIVE_COMPOSE.replace('    container_name:', '    image: other\n    container_name:'),
    LIVE_COMPOSE.replace('      - "8000:8000"\n', ''),
    LIVE_COMPOSE.replace('      - "8000:8000"\n', '      - "8000:8000"\n      - "0.0.0.0:8000:8000"\n'),
])
def test_unexpected_compose_layout_stops_the_deploy(broken):
    with pytest.raises(rd.DeployError):
        rd.rewrite_compose(broken, LIVE_IMAGE)


# --- remote_deploy.update_env --------------------------------------------------

LIVE_ENV = '''# production
DISCORD_TOKEN=token-value
DISCORD_MESSAGE_CONTENT=false
DEPLOYMENT_TIME=2026-10-01T21:41:00+00:00
SERVER_CONFIGS=[{"guild_id": 1, "status_channel_id": 2}]
'''


def test_missing_secret_is_generated_and_everything_else_kept():
    new, changed = rd.update_env(LIVE_ENV, 'NOW', lambda: 'S' * 60)
    assert changed == ['DEPLOYMENT_TIME', 'DJANGO_SECRET_KEY']
    assert new == LIVE_ENV.replace('2026-10-01T21:41:00+00:00', 'NOW') + 'DJANGO_SECRET_KEY=' + 'S' * 60 + '\n'


def test_existing_real_secret_is_never_replaced():
    first, _ = rd.update_env(LIVE_ENV, 'T1', lambda: 'first-secret-' + 'x' * 50)
    second, changed = rd.update_env(first, 'T2', lambda: 'second-secret-' + 'y' * 50)
    assert changed == ['DEPLOYMENT_TIME']
    assert 'DJANGO_SECRET_KEY=first-secret-' in second and 'second-secret' not in second


@pytest.mark.parametrize('placeholder', sorted(_PUBLIC_PLACEHOLDER_KEYS) + ['', '""'])
def test_placeholder_secret_is_replaced(placeholder):
    new, changed = rd.update_env(LIVE_ENV + 'DJANGO_SECRET_KEY=' + placeholder + '\n', 'NOW', lambda: 'R' * 60)
    assert 'DJANGO_SECRET_KEY' in changed
    assert rd.parse_env(new)['DJANGO_SECRET_KEY'] == 'R' * 60


def test_duplicate_keys_collapse_to_one():
    text = LIVE_ENV + 'DJANGO_SECRET_KEY=' + 'a' * 60 + '\nDJANGO_SECRET_KEY=' + 'b' * 60 + '\n'
    new, _ = rd.update_env(text, 'NOW')
    assert new.count('DJANGO_SECRET_KEY=') == 1 and 'a' * 60 in new


def test_crlf_env_is_normalised_without_losing_lines():
    new, _ = rd.update_env(LIVE_ENV.replace('\n', '\r\n'), 'NOW', lambda: 'S' * 60)
    assert '\r' not in new and rd.parse_env(new)['DISCORD_MESSAGE_CONTENT'] == 'false'


def test_loopback_only():
    assert rd.loopback_only({'8000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8000'}]})
    assert not rd.loopback_only({'8000/tcp': [{'HostIp': '', 'HostPort': '8000'}]})
    assert not rd.loopback_only({'8000/tcp': [{'HostIp': '0.0.0.0'}, {'HostIp': '::'}]})
    assert not rd.loopback_only({})


# --- deploy tooling invariants ---------------------------------------------------

def test_remote_deploy_runs_on_the_vms_python_3_9():
    ast.parse(REMOTE_DEPLOY.read_text(), feature_version=(3, 9))


def test_deploy_never_ships_source_or_builds_on_the_vm():
    def code(path):  # commands only: comments may say what the tooling never does
        return '\n'.join(line for line in path.read_text().splitlines() if not line.lstrip().startswith('#'))

    script, remote = code(DEPLOY_SCRIPT), code(REMOTE_DEPLOY)
    for text in (script, remote):
        assert 'rsync' not in text
        assert not re.search(r'compose[^\n]*\bbuild\b(?!-)', text.replace('--no-build', ''))
        assert 'docker build' not in text
    for call in re.findall(r"\[[^\]]*'compose', 'up'[^\]]*\]", remote):
        assert "'--no-build'" in call, call


def test_deploy_files_are_lf_only():
    for path in (DEPLOY_SCRIPT, REMOTE_DEPLOY):
        assert b'\r' not in path.read_bytes(), path
