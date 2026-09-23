import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location('h_' + name, ROOT / 'deploy/stage-h' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def layout(tmp_path):
    q = load('quarantine')
    installed, quarantine = tmp_path / 'installed', tmp_path / 'quarantine'
    installed.mkdir()
    for index, name in enumerate(q.NAMES):
        p = installed / name
        p.write_text('original helper ' + str(index))
        p.chmod(0o755)
        os.utime(p, ns=(123456789000, 123456789000))
        os.setxattr(p, 'user.stage_h_test', b'preserved')
    kwargs = {'installed': installed, 'quarantine': quarantine}
    return q, q.plan('stage-h-0123456789ab', **kwargs), kwargs


def test_exact_quarantine_restore_reactivation_cycle(layout):
    q, manifest, kwargs = layout
    for restore in (False, True, False):
        q.relocate(manifest, restore=restore, **kwargs)
        q.verify(manifest, restored=restore, **kwargs)
        for entry in manifest['entries']:
            p = Path(entry['source'] if restore else entry['target'])
            assert q.fingerprint(p) == entry['fingerprint']
    assert manifest['purge'].startswith('PROHIBITED')


@pytest.mark.parametrize('drift', ['content', 'mode', 'xattr', 'symlink', 'hardlink'])
def test_drift_blocks_whole_batch_before_mutation(layout, drift):
    q, manifest, kwargs = layout
    p = Path(manifest['entries'][-1]['source'])
    if drift == 'content':
        p.write_text('unexpected')
    elif drift == 'mode':
        p.chmod(0o644)
    elif drift == 'xattr':
        os.setxattr(p, 'user.stage_h_test', b'changed')
    elif drift == 'hardlink':
        os.link(p, p.with_suffix('.hardlink'))
    else:
        p.unlink()
        p.symlink_to(Path(manifest['entries'][0]['source']))
    with pytest.raises(RuntimeError):
        q.relocate(manifest, **kwargs)
    assert Path(manifest['entries'][0]['source']).exists()
    assert not Path(manifest['entries'][0]['target']).exists()


def test_restore_handles_partial_move_without_discarding_any_file(layout):
    q, manifest, kwargs = layout
    first = manifest['entries'][0]
    target = Path(first['target'])
    target.parent.mkdir(parents=True)
    q.rename_exclusive(first['source'], target)
    q.relocate(manifest, restore=True, **kwargs)
    q.verify(manifest, restored=True, **kwargs)


def test_conflicting_restore_never_overwrites_new_file(layout):
    q, manifest, kwargs = layout
    q.relocate(manifest, **kwargs)
    p = Path(manifest['entries'][0]['source'])
    p.write_text('new operator file')
    with pytest.raises(RuntimeError, match='ambiguous'):
        q.relocate(manifest, restore=True, **kwargs)
    assert p.read_text() == 'new operator file'
    assert all(Path(e['target']).exists() for e in manifest['entries'])


def test_exclusive_rename_closes_destination_creation_race(tmp_path):
    q = load('quarantine')
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_text('original')
    target.write_text('new writer')
    with pytest.raises(FileExistsError):
        q.rename_exclusive(source, target)
    assert source.read_text() == 'original' and target.read_text() == 'new writer'


def test_manifest_cannot_move_outside_allowlist(layout):
    q, manifest, kwargs = layout
    manifest['entries'][0]['target'] += '/../../escape'
    with pytest.raises(RuntimeError, match='allowlist'):
        q.relocate(manifest, **kwargs)


def test_reference_audit_distinguishes_module_names_and_retained_stage30(tmp_path):
    audit = load('audit')
    q = load('quarantine')
    p = tmp_path / 'entrypoint.py'
    p.write_text('import generate_ltx23_stage29\n')
    assert audit.references(p, q.NAMES) == ['generate_ltx23_stage29.py']
    p.write_text('GENERATOR="$ROOT/tools/local_video/generate_ltx23_stage30.py"\n')
    assert audit.references(p, q.NAMES) == []


def test_kernel_containment_rollback_restores_without_gpu_probes(tmp_path, monkeypatch):
    gate = load('autopilot/gate')
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'quarantine.json').write_text('{}')
    baseline = tmp_path / 'verified-g'
    baseline.mkdir()
    current = tmp_path / 'current'
    current.symlink_to(tmp_path / 'candidate')
    calls, restores, evidence = [], [], []
    monkeypatch.setattr(gate, 'BASE', baseline)
    monkeypatch.setattr(gate, 'STATE', tmp_path)
    monkeypatch.setattr(gate.e, 'CURRENT', current)
    monkeypatch.setattr(gate, 'verify', lambda p: {'source_git_sha': gate.BASE_SHA})
    monkeypatch.setattr(gate, 'run', lambda args, **kw: calls.append(args))
    monkeypatch.setattr(gate.e, 'user_systemctl', lambda args: calls.append(args))
    monkeypatch.setattr(gate.e, 'require_hermes_stopped', lambda: None)
    monkeypatch.setattr(gate.f, 'require_no_media_workers', lambda: None)
    monkeypatch.setattr(gate.q, 'relocate', lambda m, **kw: restores.append(kw))
    monkeypatch.setattr(gate.e, 'write_once', lambda p, d: evidence.append(d))
    def forbidden(*args, **kwargs):
        raise AssertionError('GPU probe or latch recovery after kernel fault')
    monkeypatch.setattr(gate.e, 'fetch', forbidden)
    monkeypatch.setattr(gate.f, 'recover_gpu_quiesced', forbidden)
    assert gate.paused_rollback(state) == 'BLOCKED_GPU'
    assert restores == [{'restore': True}] and current.resolve() == baseline
    assert not any('start' in c and 'ai-gateway.service' in c for c in calls)
    assert evidence[0]['physical_power_cycle'] == 'REQUIRED'


def test_recovery_uses_deployed_manifest_after_controller_head_changes(tmp_path, monkeypatch):
    import json
    gate = load('autopilot/gate')
    monkeypatch.setattr(gate, 'STATE', tmp_path)
    deployed, controller = 'a' * 40, 'b' * 40
    (tmp_path / 'deployment.json').write_text(json.dumps({'source_sha': deployed}))
    assert gate.deployment_sha('40_rollback', controller) == deployed
    assert gate.deployment_sha('10_build_install', controller) == controller
    (tmp_path / 'deployment.json').write_text(json.dumps({'source_sha': '../escape'}))
    with pytest.raises(RuntimeError):
        gate.deployment_sha('40_rollback', controller)


def test_resume_analysis_timer_requires_enabled_and_active(monkeypatch):
    gate = load('autopilot/gate')
    calls = []
    responses = {
        ('systemctl', 'is-enabled', 'ai-bridge-analysis.timer'): 'enabled',
        ('systemctl', 'show', 'ai-bridge-analysis.timer', '-p', 'ActiveState', '--value'): 'active',
    }
    def fake_run(args, **kwargs):
        calls.append(tuple(args))
        if tuple(args) == ('systemctl', 'start', 'ai-bridge-analysis.timer'):
            return ''
        return responses[tuple(args)]
    monkeypatch.setattr(gate, 'run', fake_run)
    assert gate.resume_analysis_timer() == {'enabled': 'enabled', 'active': 'active'}
    assert ('systemctl', 'start', 'ai-bridge-analysis.timer') in calls


def test_resume_analysis_timer_fails_closed_if_timer_does_not_activate(monkeypatch):
    gate = load('autopilot/gate')
    def fake_run(args, **kwargs):
        if args[1] == 'is-enabled':
            return 'enabled'
        if args[1] == 'start':
            return ''
        if args[1] == 'show':
            return 'inactive'
        raise AssertionError(args)
    monkeypatch.setattr(gate, 'run', fake_run)
    with pytest.raises(RuntimeError):
        gate.resume_analysis_timer()


def test_reconcile_accepted_runtime_uses_deployed_acceptance_receipt(tmp_path, monkeypatch):
    import json
    gate = load('autopilot/gate')
    release = tmp_path / 'stage-h-accepted'
    release.mkdir()
    source_sha = 'c' * 40
    (release / 'RELEASE').write_text(
        'release_id=stage-h-accepted\nstage=H\nphase=H\nsource_git_sha=' + source_sha + '\n'
    )
    current = tmp_path / 'current'
    current.symlink_to(release)
    accepted = tmp_path / source_sha
    accepted.mkdir()
    (accepted / 'complete.json').write_text(json.dumps({'source_sha': source_sha}))
    monkeypatch.setattr(gate.e, 'CURRENT', current)
    monkeypatch.setattr(gate, 'STATE', tmp_path)
    monkeypatch.setattr(gate, 'verify', lambda path: {'source_git_sha': source_sha})
    monkeypatch.setattr(gate, 'resume_analysis_timer',
                        lambda: {'enabled': 'enabled', 'active': 'active'})
    assert gate.reconcile_accepted_runtime() == {
        'release': 'stage-h-accepted',
        'source_sha': source_sha,
        'analysis_timer': {'enabled': 'enabled', 'active': 'active'},
    }
