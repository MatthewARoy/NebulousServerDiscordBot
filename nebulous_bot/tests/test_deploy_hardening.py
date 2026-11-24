"""Guards for settings and deploy files in a public repo.

The repo is public, so any default secret or published port is visible to
everyone. These tests are pure-logic: no DB, no network, no Docker.
"""
import re
from pathlib import Path

import pytest

from nebulous_project.settings import _PUBLIC_PLACEHOLDER_KEYS, resolve_secret_key

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_DIR = REPO_ROOT / 'deployment'


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


# --- Published ports ----------------------------------------------------------

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
        'deployment/oracle/deploy-to-oracle.sh',  # heredoc that prod actually uses
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
