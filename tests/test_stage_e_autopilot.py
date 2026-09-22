"""Offline fault injection only. Never invoke the production wrappers."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('stage_e_gate', ROOT / 'deploy/stage-e/autopilot/gate.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_scripts_parse_and_preflight_dispatch_is_read_only(monkeypatch, tmp_path):
    scripts = sorted((ROOT / 'deploy/stage-e/autopilot').glob('*.sh'))
    assert len(scripts) == 9
    for path in scripts:
        subprocess.run(['bash', '-n', path], check=True)
        assert path.stat().st_mode & 0o111
    gate = module()
    monkeypatch.setattr(gate, 'STATE', tmp_path / 'absent')
    monkeypatch.setattr(gate, 'config', lambda: {})
    monkeypatch.setattr(gate, 'run', lambda *a, **k: 'a' * 40)
    called = []
    monkeypatch.setattr(gate, 'preflight', lambda cfg: called.append(cfg))
    gate.main('00_preflight')
    assert called == [{}]
    assert not gate.STATE.exists()


def test_immutable_baseline_and_harness_evidence(monkeypatch, tmp_path):
    gate = module()
    path = tmp_path / 'baseline.json'
    gate.write_once(path, {'rollback': 'verified'})
    with pytest.raises(FileExistsError):
        gate.write_once(path, {'rollback': 'unverified'})
    assert gate.read(path) == {'rollback': 'verified'}
    cfg = {'harness': '/not-executed'}
    good = {'schema_version':1, 'challenge':'fresh', 'release_id':'candidate',
            'checks':{name:True for name in gate.CHECKS}}
    for mutation in ({'challenge':'stale'}, {'checks':{}}, {'private':'secret'},
                     {'checks':{name: 'PASS' for name in gate.CHECKS}}):
        monkeypatch.setattr(gate, 'run', lambda *a, value={**good, **mutation}, **k: json.dumps(value))
        with pytest.raises(RuntimeError):
            gate.harness(cfg, 'smoke', Path('candidate'), 'fresh')
    monkeypatch.setattr(gate, 'run', lambda *a, **k: json.dumps(good))
    assert gate.harness(cfg, 'smoke', Path('candidate'), 'fresh') == good


def test_rollback_recovers_partial_service_start_and_resumes(monkeypatch, tmp_path):
    gate = module()
    old, new = tmp_path / 'd6', tmp_path / 'candidate'
    old.mkdir(); new.mkdir()
    current = tmp_path / 'current'
    current.symlink_to(new)
    monkeypatch.setattr(gate, 'CURRENT', current)
    monkeypatch.setattr(gate, 'D6', old)
    monkeypatch.setattr(gate, 'verify_release', lambda *a: {'source_git_sha':gate.D6_SHA})
    monkeypatch.setattr(gate, 'clients', lambda: {})
    monkeypatch.setattr(gate, 'comfy_idle', lambda: None)
    monkeypatch.setattr(gate, 'idle', lambda: pytest.fail('unavailable Gateway must not prevent recovery'))
    monkeypatch.setattr(gate, 'runtime', lambda *a: None)
    actions = []
    monkeypatch.setattr(gate, 'harness', lambda cfg, action, *a: actions.append(action))
    def run(args, **kwargs):
        if 'show' in args:
            return 'failed' if 'ai-gateway.service' in args else 'inactive'
        return ''
    monkeypatch.setattr(gate, 'run', run)
    gate.switch(old, new, {}, {'clients':{}})
    assert current.resolve() == old
    assert actions == ['quiesce', 'resume']


def test_failed_drain_never_switches_and_resumes(monkeypatch, tmp_path):
    gate = module()
    old, new = tmp_path / 'd6', tmp_path / 'candidate'
    old.mkdir(); new.mkdir()
    current = tmp_path / 'current'; current.symlink_to(old)
    monkeypatch.setattr(gate, 'CURRENT', current)
    monkeypatch.setattr(gate, 'verify_release', lambda *a: {'source_git_sha':gate.D6_SHA})
    monkeypatch.setattr(gate, 'clients', lambda: {})
    monkeypatch.setattr(gate, 'run', lambda *a, **k: 'active')
    monkeypatch.setattr(gate, 'idle', lambda: gate.require(False))
    actions = []
    monkeypatch.setattr(gate, 'harness', lambda cfg, action, *a: actions.append(action))
    with pytest.raises(RuntimeError):
        gate.switch(new, old, {}, {'clients':{}})
    assert current.resolve() == old and actions == ['quiesce', 'resume']


def test_finalize_cannot_pass_missing_smokes(monkeypatch, tmp_path):
    gate = module()
    sha = 'a' * 40
    state = tmp_path / sha; state.mkdir()
    monkeypatch.setattr(gate, 'STATE', tmp_path)
    monkeypatch.setattr(gate, 'config', lambda: {})
    monkeypatch.setattr(gate, 'run', lambda *a, **k: sha)
    monkeypatch.setattr(gate.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(gate, 'digest', lambda *a: 'hash')
    monkeypatch.setattr(gate, 'runtime', lambda *a: None)
    monkeypatch.setattr(gate, 'verify_release', lambda *a: {'source_git_sha':sha})
    gate.write_once(state/'baseline.json', {'source_sha':sha,'rollback_sha':gate.D6_SHA,
        'candidate':'stage-e-'+sha[:12], 'rollback':gate.D6.name, 'config_digest':'hash', 'rollback_checksums':'hash'})
    gate.write_once(state/'installed.json', {'source_sha':sha, 'checksums':'hash'})
    with pytest.raises(FileNotFoundError):
        gate.main('90_finalize')


def test_stage_e_release_metadata_matches_actual_builder(tmp_path):
    import re
    spec = importlib.util.spec_from_file_location('stage_e_meta_test', ROOT / 'deploy/stage-e/validate_release_metadata.py')
    metadata = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metadata)
    builder = (ROOT/'deploy/stage-e/build_release.sh').read_text()
    for tag, target in (('MANIFEST', 'metadata/release-manifest.yaml'), ('STAMP', 'RELEASE')):
        content = re.search(r'<<' + tag + r'\n(.*?)\n' + tag, builder, re.S)[1]
        content = content.replace('$RELEASE_ID', 'stage-e-' + 'a'*12).replace('$SOURCE_SHA', 'a'*40)
        path = tmp_path/target; path.parent.mkdir(exist_ok=True)
        path.write_text(content+'\n')
    metadata.validate(tmp_path)
    stamp = tmp_path/'RELEASE'
    stamp.write_text(stamp.read_text().replace('platform_api_contract_version=1', 'platform_api_contract_version=2'))
    with pytest.raises(ValueError):
        metadata.validate(tmp_path)


def test_partial_mutation_keeps_ingress_closed_for_emergency_rollback(monkeypatch, tmp_path):
    gate = module()
    old, new = tmp_path/'d6', tmp_path/'candidate'
    old.mkdir(); new.mkdir()
    current = tmp_path/'current'; current.symlink_to(old)
    monkeypatch.setattr(gate, 'CURRENT', current)
    monkeypatch.setattr(gate, 'verify_release', lambda *a: {'source_git_sha':gate.D6_SHA})
    monkeypatch.setattr(gate, 'clients', lambda: {})
    monkeypatch.setattr(gate, 'idle', lambda: None)
    actions = []
    monkeypatch.setattr(gate, 'harness', lambda cfg, action, *a: actions.append(action))
    def run(args, **kwargs):
        if 'show' in args:
            return 'active' if 'ai-gateway.service' in args else 'inactive'
        if 'start' in args:
            raise RuntimeError('candidate start failed')
        return ''
    monkeypatch.setattr(gate, 'run', run)
    with pytest.raises(RuntimeError):
        gate.switch(new, old, {}, {'clients':{}})
    assert current.resolve() == new
    assert actions == ['quiesce']
