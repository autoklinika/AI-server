"""Offline D6GATEFIX tests: no live requests or service operations."""
import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from test_stage_d6_preparation import candidate, checksums  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy/stage-d'))
spec = importlib.util.spec_from_file_location('d6_bundle', ROOT / 'deploy/stage-d/d6_client_bundle.py')
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)

EXPECTED = {
    '/usr/local/bin/hermes-foto-dispatch': ('tools/local_image/hermes_foto_dispatch_global.py', 0o755),
    '/usr/local/libexec/ai-server/hermes_resource_queue.py': ('tools/hermes_resource_queue.py', 0o644),
    '/usr/local/libexec/ai-server/hermes_foto_prompt_compiler.py': ('tools/local_image/hermes_foto_prompt_compiler.py', 0o644),
    '/usr/local/libexec/ai-server/hermes_video_dispatch.py': ('tools/local_video/hermes_video_dispatch_global.py', 0o755),
    '/usr/local/libexec/ai-server/qwen_prompt_compiler.py': ('tools/local_video/qwen_prompt_compiler.py', 0o644),
}
LEGACY = ['generate_ltx23.py', 'generate_ltx23_stage29.py', 'generate_ltx23_base.py']


def test_exact_mapping():
    assert bundle.MAPPING == EXPECTED
    assert all(name not in p for name in LEGACY for p in bundle.MAPPING)


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    root = tmp_path / 'snapshot'
    root.mkdir()
    rows = []
    for name, (_, mode) in EXPECTED.items():
        path = root / name.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('old:' + name).encode())
        path.chmod(mode)
        rows.append(['DIFF', bundle.digest(path.read_bytes()), 'r1-not-binding', name, '/obsolete/r1'])
    # Historical DIFF rows do not expand restore scope or require legacy backups.
    rows.append(['DIFF', 'a' * 64, 'b' * 64, '/usr/local/libexec/ai-server/generate_ltx23.py', '/r1/generator'])
    manifest = root / 'inventory.tsv'
    with manifest.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t')
        writer.writerow(bundle.FIELDS)
        writer.writerows(rows)
    original = bundle.capture
    # Simulate production cp -a root ownership, without privileged test writes.
    monkeypatch.setattr(bundle, 'capture', lambda p: (*original(p)[:2], 0, 0))
    return root, manifest


def test_original_manifest_stat_contract(recovery):
    root, manifest = recovery
    result = bundle.backup_bundle(root, manifest)
    assert result.keys() == EXPECTED.keys()
    assert [v[1] for v in result.values()] == [v[1] for v in EXPECTED.values()]
    assert all(v[2:] == (0, 0) for v in result.values())


@pytest.mark.parametrize('failure', ['missing', 'tamper', 'mode', 'owner', 'duplicate', 'header', 'row', 'outside', 'symlink'])
def test_recovery_rejects_invalid_before_mutation(recovery, monkeypatch, failure):
    root, manifest = recovery
    path = root / next(iter(EXPECTED)).lstrip('/')
    if failure == 'missing':
        path.unlink()
    elif failure == 'tamper':
        path.write_bytes(b'bad')
    elif failure == 'mode':
        path.chmod(0o777)
    elif failure == 'owner':
        original = bundle.capture
        monkeypatch.setattr(bundle, 'capture', lambda p: (*original(p)[:2], 123, 123))
    elif failure == 'duplicate':
        manifest.write_text(manifest.read_text() + manifest.read_text().splitlines()[1] + '\n')
    elif failure == 'header':
        manifest.write_text(manifest.read_text().replace('installed_sha256', 'checksum'))
    elif failure == 'row':
        manifest.write_text(manifest.read_text().replace(next(iter(EXPECTED)), '/unapproved'))
    elif failure == 'outside':
        other = root.parent / 'manifest.tsv'
        shutil.copyfile(manifest, other)
        manifest = other
    elif failure == 'symlink':
        data = path.read_bytes()
        path.unlink()
        other = root / 'other'
        other.write_bytes(data)
        path.symlink_to(other)
    with pytest.raises((ValueError, OSError)):
        bundle.backup_bundle(root, manifest)


@pytest.fixture
def release(candidate):
    for service in ('ai-bridge', 'ai-gateway'):
        for source, _ in EXPECTED.values():
            path = candidate / 'services' / service / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('new:' + source).encode())
    checksums(candidate)
    return candidate


@pytest.mark.parametrize('failure', [None, 'metadata', 'tamper', 'uncovered', 'service_drift'])
def test_release_source_validation(release, failure):
    source = release / 'services/ai-bridge' / next(iter(EXPECTED.values()))[0]
    if failure == 'metadata':
        (release / 'RELEASE').write_text('stage=D\nphase=D.0\n')
        checksums(release)
    elif failure == 'tamper':
        source.write_text('tamper')
    elif failure == 'uncovered':
        path = release / 'metadata/SHA256SUMS'
        path.write_text('\n'.join(l for l in path.read_text().splitlines() if str(source.relative_to(release)) not in l))
    elif failure == 'service_drift':
        source.write_text('drift')
        checksums(release)
    if failure:
        with pytest.raises(ValueError):
            bundle.candidate_bundle(release)
    else:
        assert bundle.candidate_bundle(release).keys() == EXPECTED.keys()


class FakeRuntime:
    def __init__(self):
        self.events = []
        self.hermes = ('10', 'old')
        self.comfy = ('20', 'stable')
        self.busy = False
        self.restart_failure = False

    def guard(self, release):
        self.events.append('idle')
        if self.busy:
            raise ValueError('busy')
        return ('30', 'gateway')

    def identity(self, unit, user=False):
        assert unit in ('hermes-gateway.service', 'comfyui.service')
        return self.hermes if user else self.comfy

    def restart(self, previous):
        self.events.append('restart-hermes')
        self.hermes = (str(int(self.hermes[0]) + 1), 'new')
        if self.restart_failure:
            self.restart_failure = False
            raise ValueError('connectivity failed')
        return self.hermes


@pytest.fixture
def transition_env(recovery, release, tmp_path):
    old = bundle.backup_bundle(*recovery)
    new = bundle.candidate_bundle(release)
    installed = tmp_path / 'installed'
    def destination(name):
        return installed / name.lstrip('/')
    for name, saved in old.items():
        path = destination(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(saved[0])
        path.chmod(saved[1])
    for name in LEGACY:
        destination('/usr/local/libexec/ai-server/' + name).write_bytes(b'recovery evidence')
    runtime = FakeRuntime()
    def install(path, saved):
        runtime.events.append('install:' + path.name)
        # Exercise actual atomic replace with unprivileged local ownership.
        bundle.atomic_install(path, (*saved[:2], os.getuid(), os.getgid()))
    return old, new, destination, runtime, install


@pytest.mark.parametrize('action', ['apply', 'restore'])
def test_transition_order_and_exact_bytes_modes(release, transition_env, action):
    old, new, dest, runtime, install = transition_env
    if action == 'restore':
        for name, data in new.items():
            install(dest(name), data)
        runtime.events.clear()
    identity = bundle.transition(action, release, old, new, runtime, dest, install)
    desired = new if action == 'apply' else old
    assert {n: bundle.capture(dest(n)) for n in EXPECTED} == desired
    assert identity != ('10', 'old')
    assert runtime.events.count('restart-hermes') == 1
    assert runtime.events[0] == 'idle'
    assert runtime.events.index('restart-hermes') > max(i for i, e in enumerate(runtime.events) if e.startswith('install:'))
    assert runtime.events[-1] == 'idle'
    assert all(dest('/usr/local/libexec/ai-server/' + n).read_bytes() == b'recovery evidence' for n in LEGACY)


@pytest.mark.parametrize('failure', ['busy', 'unknown', 'write', 'restart', 'comfy_changed', 'recovery_failed'])
def test_failure_and_entry_restore(release, transition_env, failure, capsys):
    old, new, dest, runtime, install = transition_env
    calls = 0
    def failing_install(path, saved):
        nonlocal calls
        calls += 1
        if calls == 2 and failure in ('write', 'recovery_failed'):
            if failure == 'recovery_failed':
                runtime.busy = True
            raise OSError('write failed')
        install(path, saved)
        if failure == 'comfy_changed':
            runtime.comfy = ('21', 'restarted')
    if failure == 'busy':
        runtime.busy = True
    if failure == 'unknown':
        dest(next(iter(EXPECTED))).write_bytes(b'unknown')
    if failure == 'restart':
        runtime.restart_failure = True
    with pytest.raises((ValueError, OSError)):
        bundle.transition('apply', release, old, new, runtime, dest, failing_install)
    if failure in ('busy', 'unknown'):
        assert calls == 0
        assert 'restart-hermes' not in runtime.events
    elif failure in ('write', 'restart'):
        assert {n: bundle.capture(dest(n)) for n in EXPECTED} == old
        assert 'RECOVERY: entry client bundle restored' in capsys.readouterr().out
        assert runtime.events.count('restart-hermes') == (2 if failure == 'restart' else 1)
    else:
        assert 'RECOVERY FAILED' in capsys.readouterr().out
        assert 'restart-hermes' not in runtime.events


def test_atomic_install_failure_preserves_destination(tmp_path, monkeypatch):
    path = tmp_path / 'client'
    path.write_bytes(b'old')
    def fail(*args):
        raise OSError('replace failed')
    monkeypatch.setattr(bundle.os, 'replace', fail)
    with pytest.raises(OSError):
        bundle.atomic_install(path, (b'new', 0o755, os.getuid(), os.getgid()))
    assert path.read_bytes() == b'old'
    assert list(tmp_path.iterdir()) == [path]


def test_guard_rejects_historical_release_before_observing_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, 'CURRENT', tmp_path)
    runtime = object.__new__(bundle.Runtime)
    with pytest.raises(ValueError, match='D.6 candidate must be active'):
        runtime.guard(tmp_path / 'candidate')


@pytest.mark.parametrize('fresh,connected', [(True, True), (False, True), (True, False)])
def test_restart_requires_fresh_connected_state_and_new_identity(tmp_path, monkeypatch, fresh, connected):
    runtime = object.__new__(bundle.Runtime)
    runtime.user_command = ['mock-systemctl', '--user']
    runtime.state = tmp_path / 'gateway_state.json'
    payload = {'gateway_state': 'running', 'platforms': {p: {'state': 'connected'} for p in ('telegram', 'api_server')}}
    runtime.state.write_text(json.dumps(payload))
    os.utime(runtime.state, ns=(1, 1))
    commands = []
    def command(args):
        commands.append(args)
        if fresh:
            if not connected:
                payload['platforms']['api_server']['state'] = 'disconnected'
            runtime.state.write_text(json.dumps(payload))
            os.utime(runtime.state, ns=(100, 100))
    runtime.command = command
    runtime.identity = lambda *a: ('11', 'new')
    monkeypatch.setattr(bundle.time, 'time_ns', lambda: 50)
    times = iter([0, 1, 100])
    monkeypatch.setattr(bundle.time, 'monotonic', lambda: next(times))
    monkeypatch.setattr(bundle.time, 'sleep', lambda _: None)
    if fresh and connected:
        assert runtime.restart(('10', 'old')) == ('11', 'new')
    else:
        with pytest.raises(ValueError, match='reconnect timeout'):
            runtime.restart(('10', 'old'))
    assert commands == [['mock-systemctl', '--user', 'restart', 'hermes-gateway.service']]


@pytest.mark.parametrize('busy', ['active', 'queued', 'leases', 'comfy_running', 'comfy_pending', None])
def test_runtime_guard_checks_every_idle_counter(tmp_path, monkeypatch, busy):
    release = tmp_path / 'release'
    cwd = release / 'services/ai-gateway'
    cwd.mkdir(parents=True)
    current = tmp_path / 'current'
    current.symlink_to(release)
    monkeypatch.setattr(bundle, 'CURRENT', current)
    original_resolve = Path.resolve
    def resolve(path, *args, **kwargs):
        if str(path) == '/proc/30/cwd':
            return cwd
        return original_resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', resolve)
    runtime = object.__new__(bundle.Runtime)
    runtime.identity = lambda *args: ('30', 'gateway')
    counters = dict(active=0, queued=0, leases=0, comfy_running=0, comfy_pending=0)
    if busy:
        counters[busy] = 1
    monkeypatch.setattr(bundle, 'snapshot', lambda fetch: counters)
    if busy:
        with pytest.raises(ValueError, match='not idle'):
            runtime.guard(release)
    else:
        assert runtime.guard(release) == ('30', 'gateway')


def test_failed_restore_returns_to_entry_d6_bundle(release, transition_env):
    old, new, dest, runtime, install = transition_env
    for name, saved in new.items():
        install(dest(name), saved)
    runtime.restart_failure = True
    with pytest.raises(ValueError):
        bundle.transition('restore', release, old, new, runtime, dest, install)
    assert {n: bundle.capture(dest(n)) for n in EXPECTED} == new
    assert runtime.events.count('restart-hermes') == 2


def test_unchanged_hermes_identity_never_passes_restart(tmp_path, monkeypatch):
    runtime = object.__new__(bundle.Runtime)
    runtime.user_command = ['mock']
    runtime.state = tmp_path / 'state.json'
    runtime.state.write_text('{}')
    runtime.command = lambda *a: None
    runtime.identity = lambda *a: ('10', 'old')
    ticks = iter([0, 1, 100])
    monkeypatch.setattr(bundle.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(bundle.time, 'sleep', lambda _: None)
    with pytest.raises(ValueError, match='reconnect timeout'):
        runtime.restart(('10', 'old'))


def test_operator_ordering_and_pid_contract():
    runbook = (ROOT / 'deploy/stage-d/D6_VALIDATION_RUNBOOK.md').read_text()
    rollback = runbook.split('Rollback:\n')[1].split('Re-activation:')[0]
    assert rollback.index('d6_client_bundle.py restore') < rollback.index('rollback_release.sh')
    activation = runbook.split('Re-activation:\n')[1]
    assert activation.index('Activate D.6 release first') < activation.index('d6_client_bundle.py apply')
    assert 'new Hermes PID baseline' in runbook
    assert 'ComfyUI PID/invocation must remain unchanged' in runbook
