"""Only injected tmp_path writer transactions; no production adapter probes."""
import copy
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest
from test_stage_o_recovery_check import documents, export

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/stage-o/recover_acceptance_apply.py'
spec = importlib.util.spec_from_file_location('recovery_apply_test', SCRIPT)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
NOW = 1800000000


class FixtureVerifier:
    """Test-only authority. Never exposed by CLI or used as production evidence."""
    approved = True

    def __init__(self, observation):
        self.observation = observation

    def observe(self):
        return copy.deepcopy(self.observation)

    def authorize(self, source, observation, records):
        return self.approved

    def recheck(self, observation):
        return self.observation == observation


@pytest.fixture
def transaction(tmp_path, documents, monkeypatch):
    parent = tmp_path / 'state'
    parent.mkdir(mode=0o700)
    state = export(tmp_path, documents)
    state.rename(parent / a.h.SOURCE)
    state = parent / a.h.SOURCE
    state.chmod(0o700)
    for path in state.iterdir():
        path.chmod(0o600)
    (parent / 'executor.lock').touch(mode=0o600)
    monkeypatch.setattr(a.p, 'ROOT_UID', os.getuid())
    monkeypatch.setattr(a.p, 'ROOT_GID', os.getgid())
    monkeypatch.setattr(a.os, 'geteuid', lambda: 0)
    # Only temporary ancestors relax trust; state/files retain exact checks.
    trusted = a.p.trusted
    def fixture_trust(st, mode=None):
        if mode is not None or not stat.S_ISDIR(st.st_mode):
            trusted(st, mode)
    monkeypatch.setattr(a.p, 'trusted', fixture_trust)
    o = dict(source_sha=a.h.SOURCE, manifest_sha256=documents['installed']['checksums'],
        clients=documents['baseline']['clients'], model=a.MODEL,
        adapter_source=a.ADAPTER_SOURCE, adapter_runtime=a.ADAPTER_RUNTIME,
        health=dict.fromkeys(['gateway', 'bridge', 'control_center', 'comfyui', 'ollama', 'hermes', 'analysis_timer'], 'ok'),
        queue=0, leases=0, restore='PASS',
        config_sha256={f'unit-{n}.service': 'a' * 64 for n in range(17)},
        boot_id='11111111-2222-3333-4444-555555555555', approval_id='TEST-ONLY-APPLY',
        env_exception_id=a.p.DECISION)
    for name in ('monitor', 'daily', 'weekly', 'nas'):
        o[name] = dict(status='PASS', time=NOW, source_sha256='b' * 64)
    return state, FixtureVerifier(o)


def commit(transaction):
    return a.commit(*transaction, clock=lambda: NOW)


def test_success_durable_order_and_provenance(transaction, monkeypatch):
    state, _ = transaction
    events = []
    fsync = a.os.fsync
    def sync(fd):
        events.append('dir' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file')
        fsync(fd)
    monkeypatch.setattr(a.os, 'fsync', sync)
    before = {p.name: p.read_bytes() for p in state.iterdir()}
    result = commit(transaction)
    assert events == ['file', 'dir', 'file', 'dir']
    assert result['llm_model'] == a.MODEL
    a.verify_provenance(state, result)
    att = json.loads((state / a.ATTESTATION).read_bytes())
    assert att['env']['byte_identity'] == 'NOT_PROVEN'
    assert att['historical_finalize'] == 'NOT_PASSED'
    assert all((state / n).read_bytes() == raw for n, raw in before.items())
    for name in (a.ATTESTATION, 'accepted.json'):
        assert stat.S_IMODE((state / name).stat().st_mode) == 0o600
    with pytest.raises(ValueError, match='PARTIAL_OR_EXISTING'):
        commit(transaction)


@pytest.mark.parametrize('fault', ['accepted', 'partial', 'symlink', 'mode', 'owner', 'source',
    'missing_smoke', 'manifest', 'model', 'health', 'stagek', 'nas', 'approval', 'duplicate', 'clients', 'queue'])
def test_negative(transaction, monkeypatch, fault):
    state, v = transaction
    if fault in ('accepted', 'partial'):
        (state / ('accepted.json' if fault == 'accepted' else a.ATTESTATION)).write_text('{}')
    elif fault == 'symlink':
        (state / 'baseline.json').unlink()
        (state / 'baseline.json').symlink_to(state / 'installed.json')
    elif fault == 'mode':
        (state / 'baseline.json').chmod(0o644)
    elif fault == 'owner':
        monkeypatch.setattr(a.p, 'ROOT_UID', os.getuid() + 1)
    elif fault == 'source':
        v.observation['source_sha'] = 'a' * 40
    elif fault == 'missing_smoke':
        (state / 'final-smoke.json').unlink()
    elif fault == 'manifest':
        v.observation['manifest_sha256'] = 'c' * 64
    elif fault == 'model':
        v.observation['model'] = 'other'
    elif fault == 'health':
        v.observation['health']['gateway'] = 'failed'
    elif fault == 'stagek':
        v.observation['weekly']['status'] = 'FAIL'
    elif fault == 'nas':
        v.observation['nas']['time'] -= 61
    elif fault == 'approval':
        v.approved = False
    elif fault == 'duplicate':
        (state / 'installed.json').write_text('{"source_sha":1,"source_sha":2}')
    elif fault == 'clients':
        v.observation['clients'] = {}
    else:
        v.observation['queue'] = 1
    before = {p.name: p.lstat() for p in state.iterdir()}
    with pytest.raises((ValueError, OSError)):
        commit(transaction)
    assert {p.name: p.lstat() for p in state.iterdir()} == before


def test_lock_contention(transaction):
    state, _ = transaction
    with (state.parent / 'executor.lock').open('rb') as lock:
        a.fcntl.flock(lock, a.fcntl.LOCK_EX | a.fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            commit(transaction)
    assert not (state / a.ATTESTATION).exists()


@pytest.mark.parametrize('fault', ['artifact', 'lock', 'runtime', 'directory'])
def test_toctou(transaction, fault):
    state, v = transaction
    def race(*args):
        if fault == 'artifact':
            (state / 'baseline.json').write_text('{}')
        elif fault == 'lock':
            (state.parent / 'executor.lock').unlink()
            (state.parent / 'executor.lock').touch(mode=0o600)
        elif fault == 'runtime':
            v.observation['boot_id'] = 'changed'
        else:
            state.rename(state.with_name('moved'))
            state.mkdir(mode=0o700)
        return True
    v.authorize = race
    with pytest.raises((ValueError, OSError)):
        commit(transaction)
    assert not (state / 'accepted.json').exists()


def test_crash_between_writes_never_resumed(transaction):
    state, v = transaction
    calls = []
    def crash(o):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('injected crash')
        return True
    v.recheck = crash
    with pytest.raises(RuntimeError, match='injected crash'):
        commit(transaction)
    assert (state / a.ATTESTATION).exists()
    assert not (state / 'accepted.json').exists()
    with pytest.raises(ValueError, match='PARTIAL_OR_EXISTING'):
        commit(transaction)


@pytest.mark.parametrize('fault', ['attestation', 'original', 'missing', 'stripped'])
def test_provenance_tampering(transaction, fault):
    state, _ = transaction
    accepted = commit(transaction)
    if fault == 'attestation':
        (state / a.ATTESTATION).write_text('{}')
    elif fault == 'original':
        (state / 'installed.json').write_text('{}')
    elif fault == 'missing':
        (state / a.ATTESTATION).unlink()
    else:
        accepted.pop('recovery_provenance')
    with pytest.raises((ValueError, KeyError, OSError)):
        a.verify_provenance(state, accepted)


@pytest.mark.parametrize('args', [[], ['--check'], ['--apply']])
def test_production_adapter_always_blocked(args, monkeypatch, capsys):
    monkeypatch.setattr(a, 'commit', lambda *x: pytest.fail('writer reached'))
    monkeypatch.setattr(a.p, 'directory', lambda *x: pytest.fail('production read'))
    assert a.main(args) == 2
    assert json.loads(capsys.readouterr().out)['apply_available'] is False


def test_new_boot_identity_is_recovery_not_finalize(transaction):
    state, v = transaction
    historical = json.loads((state / 'baseline.json').read_bytes())['comfy']
    # Historical process identity is preserved; recovery records a new boot,
    # whereas existing finalize regression tests still reject changed PID.
    accepted = commit(transaction)
    assert accepted['phase'] == a.PHASE
    assert json.loads((state / 'baseline.json').read_bytes())['comfy'] == historical
    assert json.loads((state / a.ATTESTATION).read_bytes())['boot_id'] == v.observation['boot_id']


@pytest.mark.parametrize('fail_at', [1, 2, 3, 4])
def test_fsync_failure_leaves_state_and_blocks_retry(transaction, monkeypatch, fail_at):
    state, _ = transaction
    sync = a.os.fsync
    calls = []
    def fail(fd):
        calls.append(fd)
        if len(calls) == fail_at:
            raise OSError('injected fsync failure')
        sync(fd)
    monkeypatch.setattr(a.os, 'fsync', fail)
    with pytest.raises(OSError, match='fsync'):
        commit(transaction)
    assert (state / a.ATTESTATION).exists()
    with pytest.raises(ValueError, match='PARTIAL_OR_EXISTING'):
        commit(transaction)


def test_gate_routes_recovered_and_rejects_stripped_provenance(transaction, monkeypatch):
    state, _ = transaction
    accepted = commit(transaction)
    gate_spec = importlib.util.spec_from_file_location('recovery_integration_gate', SCRIPT.parent / 'autopilot/gate.py')
    g = importlib.util.module_from_spec(gate_spec)
    gate_spec.loader.exec_module(g)
    monkeypatch.setattr(g, 'STATE', state.parent)
    monkeypatch.setattr(g, 'candidate_identity', lambda sha: state.parent / a.h.RELEASE)
    monkeypatch.setattr(g.e, 'load_module', lambda *args: a)
    stamp = dict(stage='O', source_git_sha=a.h.SOURCE, technical_conversation_contract_version='1')
    assert g.accepted_stage_o(state.parent / a.h.RELEASE, stamp) == accepted
    accepted.pop('phase')
    accepted.pop('recovery_provenance')
    (state / 'accepted.json').write_bytes(a.encode(accepted))
    with pytest.raises((ValueError, KeyError)):
        g.accepted_stage_o(state.parent / a.h.RELEASE, stamp)


def test_cli_no_pycache(tmp_path):
    import subprocess
    import sys
    for source in [SCRIPT, SCRIPT.with_name('recover_acceptance_preflight.py'),
                   SCRIPT.with_name('recover_acceptance_once.py')]:
        (tmp_path / source.name).write_bytes(source.read_bytes())
    before = set(tmp_path.rglob('*'))
    result = subprocess.run([sys.executable, '-I', '-B', '-S', str(tmp_path / SCRIPT.name)],
                            cwd=tmp_path, capture_output=True, timeout=10)
    assert result.returncode == 2
    assert set(tmp_path.rglob('*')) == before


@pytest.mark.parametrize('fault', ['attestation', 'verifier_rejection'])
def test_between_writes_recheck(transaction, fault):
    state, verifier = transaction
    calls = []
    def recheck(observation):
        calls.append(1)
        if len(calls) == 2:
            if fault == 'attestation':
                (state / a.ATTESTATION).write_text('{}')
                return True
            return False
        return True
    verifier.recheck = recheck
    with pytest.raises(ValueError):
        commit(transaction)
    assert not (state / 'accepted.json').exists()


def test_post_write_recheck_failure_is_not_rollback(transaction):
    state, verifier = transaction
    calls = []
    def recheck(observation):
        calls.append(1)
        return len(calls) < 3
    verifier.recheck = recheck
    with pytest.raises(ValueError, match='RUNTIME_CHANGED'):
        commit(transaction)
    assert (state / 'accepted.json').exists()
    with pytest.raises(ValueError, match='PARTIAL_OR_EXISTING_STATE'):
        commit(transaction)


@pytest.mark.parametrize('name', [a.ATTESTATION, 'accepted.json'])
def test_file_create_failure(transaction, monkeypatch, name):
    state, _ = transaction
    original = a.exclusive_write
    def fail(fd, leaf, raw):
        if leaf == name:
            raise PermissionError('injected create failure')
        return original(fd, leaf, raw)
    monkeypatch.setattr(a, 'exclusive_write', fail)
    with pytest.raises(PermissionError):
        commit(transaction)
    assert not (state / 'accepted.json').exists()
    assert (state / a.ATTESTATION).exists() == (name == 'accepted.json')
