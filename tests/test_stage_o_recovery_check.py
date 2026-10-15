"""Offline checks of a deliberately non-authorizing recovery prerequisite tool."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/stage-o/recover_acceptance_once.py'
spec = importlib.util.spec_from_file_location('recovery_check', SCRIPT)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


@pytest.fixture
def documents():
    rollback_sha = 'a' * 40
    rollback = 'stage-o-' + rollback_sha[:12]
    baseline = dict(rollback=rollback, rollback_sha=rollback_sha, rollback_stage='O',
                    candidate=r.RELEASE, source_sha=r.SOURCE, schema=r.SCHEMA,
                    clients={p: ['b' * 64, 0o755, 0, 0] for p in r.CLIENTS},
                    comfy=['123', 'c' * 32], hermes_active='active',
                    analysis_timer_active='active', preload_unit='historical unit',
                    rollback_checksums='d' * 64)
    cc = dict(status='PASS', apps=['knowledge', 'benchmarks', 'ers', 'observability',
                                 'system-map', 'incidents'], knowledge_results=1)
    bm = dict(status='PASS', suite_case_counts={'automotive-reasoning': 58,
              'decision-models': 51, 'rag-knowledge': 61}, raw_results=1, reranked_results=1)
    d = {'baseline': baseline, 'installed': dict(candidate=r.RELEASE,
         source_sha=r.SOURCE, checksums='e' * 64)}
    for name, target in [('20_cutover', r.RELEASE), ('rollback', rollback), ('reactivate', r.RELEASE)]:
        d[name] = {'release_id': target}
    for n, name in enumerate(['candidate-smoke', 'rollback-smoke', 'final-smoke']):
        d[name] = dict(release_id=rollback if n == 1 else r.RELEASE, schema=r.SCHEMA,
                       control_center=copy.deepcopy(cc), time=100 + n,
                       benchmarks={'status': 'ROLLBACK_NOT_REQUIRED'} if n == 1 else copy.deepcopy(bm))
    return d


def export(tmp_path, documents):
    directory = tmp_path / 'evidence'
    directory.mkdir()
    for n, name in enumerate(r.NAMES):
        path = directory / (name + '.json')
        path.write_text(json.dumps(documents[name]))
        os.utime(path, ns=(10**9 + n, 10**9 + n))
    return directory


def report(capsys, *args):
    assert r.main(list(args)) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'NO_GO'
    assert result['apply_available'] is False
    assert result['e_safe'] == 'NOT_ESTABLISHED'
    return result


def test_consistent_copies_are_never_acceptance(tmp_path, documents, capsys):
    directory = export(tmp_path, documents)
    result = report(capsys, '--expected-source', r.SOURCE, '--evidence-dir', str(directory))
    assert result['copy_structure'] == 'CONSISTENT_UNAUTHENTICATED'
    assert set(result['copy_sha256']) == set(r.NAMES)
    assert set(result['blockers']) == set(r.BLOCKERS)


@pytest.mark.parametrize('name', r.NAMES)
def test_missing_artifact(tmp_path, documents, capsys, name):
    directory = export(tmp_path, documents)
    (directory / (name + '.json')).unlink()
    assert report(capsys, '--expected-source', r.SOURCE, '--evidence-dir', str(directory))['copy_structure'] == 'REJECTED'


@pytest.mark.parametrize('phase', ['candidate-smoke', 'final-smoke', 'rollback-smoke'])
@pytest.mark.parametrize('fault', ['cc_fail', 'empty_cc', 'false_count', 'bad_apps', 'bad_schema', 'bad_release', 'future', 'bool_time', 'empty_bm', 'nested_fail'])
def test_false_smoke(documents, phase, fault):
    s = documents[phase]
    if fault == 'cc_fail': s['control_center']['status'] = 'FAIL'
    elif fault == 'empty_cc': s['control_center'] = {}
    elif fault == 'false_count': s['control_center']['knowledge_results'] = True
    elif fault == 'bad_apps': s['control_center']['apps'] = []
    elif fault == 'bad_schema': s['schema'] = 'wrong'
    elif fault == 'bad_release': s['release_id'] = 'stage-o-other'
    elif fault == 'future': s['time'] = 999
    elif fault == 'bool_time': s['time'] = True
    elif fault == 'empty_bm': s['benchmarks'] = {}
    else: s['benchmarks']['status'] = 'FAIL'
    with pytest.raises(ValueError): r.validate_structure(documents, 200)


@pytest.mark.parametrize('phase', ['candidate-smoke', 'final-smoke'])
def test_candidate_cannot_use_rollback_exemption(documents, phase):
    documents[phase]['benchmarks'] = {'status': 'ROLLBACK_NOT_REQUIRED'}
    with pytest.raises(ValueError): r.validate_structure(documents, 200)


@pytest.mark.parametrize('fault', ['source', 'installed', 'rollback_sha', 'checksum', 'clients', 'client_mode', 'identity', 'preload', 'sequence', 'unknown_snapshot'])
def test_invalid_history(documents, fault):
    b = documents['baseline']
    if fault == 'source': b['source_sha'] = 'f' * 40
    elif fault == 'installed': documents['installed']['source_sha'] = 'f' * 40
    elif fault == 'rollback_sha': b['rollback_sha'] = r.SOURCE
    elif fault == 'checksum': documents['installed']['checksums'] = ''
    elif fault == 'clients': b['clients'].pop(next(iter(r.CLIENTS)))
    elif fault == 'client_mode': b['clients'][next(iter(r.CLIENTS))][1] = True
    elif fault == 'identity': b['comfy'] = ['123', '']
    elif fault == 'preload': b['preload_unit'] = ''
    elif fault == 'sequence': documents['candidate-smoke']['time'] = 103
    else: b['approved_config'] = {'status': 'PASS'}
    with pytest.raises(ValueError): r.validate_structure(documents, 200)


@pytest.mark.parametrize('extra', ['manifest', 'current', 'backup-empty', 'backup-fail', 'new-comfy', 'config-drift', 'modified-clients', 'rollback-accepted', 'auth', 'lock', 'health'])
def test_untrusted_supplements_cannot_clear_authority_blockers(tmp_path, documents, capsys, extra):
    # No claimed external observation is consumed as a trusted runtime/reference.
    # This is NOT a test of production drift detection: those checks are unimplemented.
    directory = export(tmp_path, documents)
    (directory / (extra + '.json')).write_text(json.dumps({'status': 'PASS'}))
    result = report(capsys, '--expected-source', r.SOURCE, '--evidence-dir', str(directory))
    assert result['copy_structure'] == 'REJECTED'
    assert set(result['blockers']) == set(r.BLOCKERS)


@pytest.mark.parametrize('fault', ['symlink_file', 'symlink_directory', 'duplicate_key', 'nan', 'hardlink', 'fifo', 'oversized', 'mtime'])
def test_unsafe_copies(tmp_path, documents, capsys, fault):
    directory = export(tmp_path, documents)
    path = directory / 'final-smoke.json'
    if fault == 'symlink_file':
        path.unlink(); path.symlink_to(directory / 'candidate-smoke.json')
    elif fault == 'symlink_directory':
        alias = tmp_path / 'alias'; alias.symlink_to(directory, target_is_directory=True); directory = alias
    elif fault == 'duplicate_key': path.write_text('{"x":1,"x":2}')
    elif fault == 'nan': path.write_text('{"x":NaN}')
    elif fault == 'hardlink': os.link(path, tmp_path / 'link')
    elif fault == 'fifo': path.unlink(); os.mkfifo(path)
    elif fault == 'oversized': path.write_bytes(b' ' * (1024 * 1024 + 1))
    else: os.utime(path, ns=(1, 1))
    assert report(capsys, '--expected-source', r.SOURCE, '--evidence-dir', str(directory))['copy_structure'] == 'REJECTED'


def test_changed_copy_during_read(tmp_path, documents, capsys, monkeypatch):
    directory = export(tmp_path, documents)
    original = r.os.read
    changed = False
    def racing_read(fd, size):
        nonlocal changed
        data = original(fd, size)
        if not changed:
            changed = True
            (directory / 'baseline.json').write_text('{}')
        return data
    monkeypatch.setattr(r.os, 'read', racing_read)
    assert report(capsys, '--expected-source', r.SOURCE, '--evidence-dir', str(directory))['copy_structure'] == 'REJECTED'


@pytest.mark.parametrize('source', [None, r.SOURCE[:12], 'f' * 40])
def test_expected_source_required_without_open(capsys, monkeypatch, source):
    monkeypatch.setattr(r.os, 'open', lambda *a, **k: pytest.fail('unexpected read'))
    args = ['--evidence-dir', '/not/read']
    if source is not None: args += ['--expected-source', source]
    assert 'EXPECTED_FULL_SOURCE_REQUIRED' in report(capsys, *args)['diagnostics']


@pytest.mark.parametrize('direct', [False, True])
@pytest.mark.parametrize('args', [[], ['--expected-source', r.SOURCE], ['--apply'],
    ['--apply', '--expected-source', r.SOURCE, '--owner-confirmation', 'approved', '--lock', 'held']])
def test_cli_no_writes_or_bytecode(tmp_path, args, direct):
    # Isolated copy so a .pyc leak is observable; no real staging/production paths.
    script = tmp_path / 'check.py'
    script.write_bytes(SCRIPT.read_bytes())
    script.chmod(0o755)
    before = set(tmp_path.rglob('*'))
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
    env['PYTHONPYCACHEPREFIX'] = str(tmp_path / 'cache')
    # Flags must apply before interpreter startup, including encoding imports.
    command = [str(script)] if direct else [sys.executable, '-I', '-B', '-S', str(script)]
    result = subprocess.run([*command, *args], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert set(tmp_path.rglob('*')) == before
    if '--apply' in args: assert 'unrecognized arguments' in result.stderr
    else: assert json.loads(result.stdout)['status'] == 'NO_GO'


def test_copy_read_does_not_change_metadata(tmp_path, documents):
    directory = export(tmp_path, documents)
    paths = [directory, *(directory / (n + '.json') for n in r.NAMES)]
    before = {p: (r.snapshot(p.stat()), p.stat().st_atime_ns) for p in paths}
    r.read_copies(str(directory))
    assert {p: (r.snapshot(p.stat()), p.stat().st_atime_ns) for p in paths} == before


@pytest.mark.parametrize('fault', ['modified_clients', 'config_drift', 'new_pid', 'reused_pid', 'manifest_rehashed'])
def test_plausible_substitution_still_cannot_authorize(tmp_path, documents, capsys, fault):
    # Structurally valid forgeries are explicitly NOT authenticated by this tool.
    b = documents['baseline']
    if fault == 'modified_clients': b['clients'][next(iter(r.CLIENTS))] = ['f' * 64, 0o700, 1000, 1000]
    elif fault == 'config_drift': b['preload_unit'] = 'changed unit with changed model'
    elif fault == 'new_pid': b['comfy'] = ['456', 'd' * 32]
    elif fault == 'reused_pid': b['comfy'] = ['123', 'd' * 32]
    else: documents['installed']['checksums'] = 'f' * 64
    directory = export(tmp_path, documents)
    result = report(capsys, '--expected-source', r.SOURCE, '--evidence-dir', str(directory))
    assert result['copy_structure'] == 'CONSISTENT_UNAUTHENTICATED'
    for blocker in ['CONFIG_REFERENCE_UNAVAILABLE', 'RELEASE_NOT_VERIFIED',
                    'RUNTIME_NOT_VERIFIED', 'BOOT_CONTINUITY_NOT_PROVEN']:
        assert blocker in result['blockers']


@pytest.mark.parametrize('backup', [{}, {'status': 'FAIL'}, {'status': 'PASS', 'restore': {'status': 'FAIL'}}])
def test_backup_cannot_be_laundered_through_smoke(documents, backup):
    documents['final-smoke']['control_center']['backup'] = backup
    with pytest.raises(ValueError): r.validate_structure(documents, 200)
