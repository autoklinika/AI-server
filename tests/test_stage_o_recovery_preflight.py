"""Hermetic limited preflight tests; never run against production paths."""
import importlib.util
import json
import os
from pathlib import Path

import pytest
from test_stage_o_recovery_check import documents, export

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/stage-o/recover_acceptance_preflight.py'
spec = importlib.util.spec_from_file_location('original_preflight', SCRIPT)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


@pytest.fixture
def original(tmp_path, documents, monkeypatch):
    state = tmp_path / 'state'
    state.mkdir(mode=0o700)
    evidence = export(tmp_path, documents)
    evidence.rename(state / p.h.SOURCE)
    evidence = state / p.h.SOURCE
    evidence.chmod(0o700)
    for path in evidence.iterdir():
        path.chmod(0o600)
    (state / 'executor.lock').touch(mode=0o600)
    current = tmp_path / 'current'
    current.symlink_to(p.RELEASE)
    monkeypatch.setattr(p, 'STATE', str(state))
    monkeypatch.setattr(p, 'CURRENT', str(current))
    monkeypatch.setattr(p, 'ROOT_UID', os.getuid())
    monkeypatch.setattr(p, 'ROOT_GID', os.getgid())
    monkeypatch.setattr(p.os, 'geteuid', lambda: 0)
    # Only fixture ancestors bypass production trusted-parent policy.
    real_trusted = p.trusted
    def trusted(st, mode=None):
        if mode is not None or not __import__('stat').S_ISDIR(st.st_mode):
            real_trusted(st, mode)
    monkeypatch.setattr(p, 'trusted', trusted)
    return state, evidence, current


def run(capsys):
    assert p.main(['--check', '--expected-source', p.h.SOURCE]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'NO_GO'
    assert report['apply_available'] is False
    assert report['missing_proof'] == p.MISSING
    return report


def test_candidate_observation_without_write(original, capsys):
    state, evidence, current = original
    paths = [state, evidence, current, *state.iterdir(), *evidence.iterdir()]
    before = {str(x): p.h.snapshot(x.lstat()) for x in paths}
    assert run(capsys)['original_transaction'] == 'STRUCTURE_OBSERVED_UNDER_LOCK'
    assert {str(x): p.h.snapshot(x.lstat()) for x in paths} == before
    assert not (evidence / 'accepted.json').exists()


@pytest.mark.parametrize('fault', ['accepted', 'partial', 'lock_missing', 'lock_symlink',
    'current', 'artifact_symlink', 'mode', 'duplicate', 'wrong_user', 'missing'])
def test_rejects(original, capsys, monkeypatch, fault):
    state, evidence, current = original
    if fault in ('accepted', 'partial'):
        (evidence / ('accepted.json' if fault == 'accepted' else 'recovery-attestation.json')).write_text('{}')
    elif fault.startswith('lock'):
        (state / 'executor.lock').unlink()
        if fault == 'lock_symlink': (state / 'executor.lock').symlink_to(evidence / 'baseline.json')
    elif fault == 'current': current.unlink(); current.symlink_to('/wrong')
    elif fault == 'artifact_symlink':
        (evidence / 'baseline.json').unlink()
        (evidence / 'baseline.json').symlink_to(evidence / 'installed.json')
    elif fault == 'mode': (evidence / 'baseline.json').chmod(0o644)
    elif fault == 'duplicate': (evidence / 'baseline.json').write_text('{"x":1,"x":2}')
    elif fault == 'wrong_user': monkeypatch.setattr(p.os, 'geteuid', lambda: 1000)
    else: (evidence / 'baseline.json').unlink()
    before = {x.name: x.lstat() for x in evidence.iterdir()}
    assert run(capsys)['original_transaction'] == 'REJECTED'
    assert {x.name: x.lstat() for x in evidence.iterdir()} == before


@pytest.mark.parametrize('fault', ['artifact', 'current', 'lock'])
def test_race_rejected(original, capsys, monkeypatch, fault):
    state, evidence, current = original
    read = p.h.read_copies
    def racing(path):
        result = read(path)
        if fault == 'artifact': (evidence / 'baseline.json').write_text('{}')
        elif fault == 'current': current.unlink(); current.symlink_to('/wrong')
        else: (state / 'executor.lock').unlink(); (state / 'executor.lock').touch(mode=0o600)
        return result
    monkeypatch.setattr(p.h, 'read_copies', racing)
    assert run(capsys)['original_transaction'] == 'REJECTED'


@pytest.mark.parametrize('args', [['--apply'], ['--evidence-dir', '/tmp'], ['--approval-token', 'x']])
def test_no_privileged_cli(args, monkeypatch):
    monkeypatch.setattr(p, 'original_transaction', lambda: pytest.fail('must not probe'))
    with pytest.raises(SystemExit) as error:
        p.main(['--expected-source', p.h.SOURCE, *args])
    assert error.value.code == 2


def test_parent_trust_rejects_world_writable(tmp_path):
    with pytest.raises(ValueError):
        p.directory(str(tmp_path))


def test_busy_shared_lock(original, capsys):
    state, _, _ = original
    with (state / 'executor.lock').open('rb') as lock:
        p.fcntl.flock(lock, p.fcntl.LOCK_EX | p.fcntl.LOCK_NB)
        assert run(capsys)['original_transaction'] == 'REJECTED'


def test_cli_no_bytecode_or_created_lock(tmp_path):
    import subprocess
    import sys
    for source in [SCRIPT, SCRIPT.with_name('recover_acceptance_once.py')]:
        (tmp_path / source.name).write_bytes(source.read_bytes())
    before = set(tmp_path.rglob('*'))
    env = dict(os.environ, PYTHONPYCACHEPREFIX=str(tmp_path / 'cache'))
    # Invalid source rejects before any production read, even when tests run as root.
    result = subprocess.run([sys.executable, '-I', '-B', '-S', str(tmp_path / SCRIPT.name),
                             '--expected-source', 'invalid'], cwd=tmp_path,
                            env=env, capture_output=True, timeout=10)
    assert result.returncode == 2
    assert set(tmp_path.rglob('*')) == before
