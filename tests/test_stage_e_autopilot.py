"""Offline fault injection only. Never invoke the production wrappers."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location(
        'stage_e_gate', ROOT / 'deploy/stage-e/autopilot/gate.py'
    )
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


def test_immutable_baseline_evidence(tmp_path):
    gate = module()
    path = tmp_path / 'baseline.json'
    gate.write_once(path, {'rollback': 'verified'})
    with pytest.raises(FileExistsError):
        gate.write_once(path, {'rollback': 'unverified'})
    assert gate.read(path) == {'rollback': 'verified'}


def test_switch_recovers_and_resumes_after_success(monkeypatch, tmp_path):
    gate = module()
    old, new = tmp_path / 'd6', tmp_path / 'candidate'
    old.mkdir()
    new.mkdir()
    current = tmp_path / 'current'
    current.symlink_to(new)
    monkeypatch.setattr(gate, 'CURRENT', current)
    monkeypatch.setattr(gate, 'D6', old)
    monkeypatch.setattr(gate, 'verify_release', lambda *a: {'source_git_sha': gate.D6_SHA})
    monkeypatch.setattr(gate, 'clients', lambda: {})
    monkeypatch.setattr(gate, 'comfy_idle', lambda: None)
    monkeypatch.setattr(
        gate, 'idle', lambda: pytest.fail('unavailable Gateway must not prevent recovery')
    )
    monkeypatch.setattr(gate, 'runtime', lambda *a: None)
    actions = []
    monkeypatch.setattr(gate, 'quiesce', lambda baseline: actions.append('quiesce'))
    monkeypatch.setattr(gate, 'resume_ingress', lambda baseline: actions.append('resume'))

    def run(args, **kwargs):
        if 'show' in args:
            return 'failed' if 'ai-gateway.service' in args else 'inactive'
        return ''

    monkeypatch.setattr(gate, 'run', run)
    gate.switch(old, new, {}, {'clients': {}})
    assert current.resolve() == old
    assert actions == ['quiesce', 'resume']


def test_failed_quiesce_never_switches_but_attempts_restore(monkeypatch, tmp_path):
    gate = module()
    old, new = tmp_path / 'd6', tmp_path / 'candidate'
    old.mkdir()
    new.mkdir()
    current = tmp_path / 'current'
    current.symlink_to(old)
    monkeypatch.setattr(gate, 'CURRENT', current)
    monkeypatch.setattr(gate, 'verify_release', lambda *a: {'source_git_sha': gate.D6_SHA})
    monkeypatch.setattr(gate, 'clients', lambda: {})
    actions = []

    def fail_quiesce(_baseline):
        actions.append('quiesce')
        raise RuntimeError('drain failed')

    monkeypatch.setattr(gate, 'quiesce', fail_quiesce)
    monkeypatch.setattr(gate, 'resume_ingress', lambda baseline: actions.append('resume'))
    with pytest.raises(RuntimeError):
        gate.switch(new, old, {}, {'clients': {}})
    assert current.resolve() == old
    assert actions == ['quiesce', 'resume']


def test_partial_mutation_keeps_ingress_closed_for_emergency_rollback(
    monkeypatch, tmp_path
):
    gate = module()
    old, new = tmp_path / 'd6', tmp_path / 'candidate'
    old.mkdir()
    new.mkdir()
    current = tmp_path / 'current'
    current.symlink_to(old)
    monkeypatch.setattr(gate, 'CURRENT', current)
    monkeypatch.setattr(gate, 'verify_release', lambda *a: {'source_git_sha': gate.D6_SHA})
    monkeypatch.setattr(gate, 'clients', lambda: {})
    monkeypatch.setattr(gate, 'idle', lambda: None)
    actions = []
    monkeypatch.setattr(gate, 'quiesce', lambda baseline: actions.append('quiesce'))
    monkeypatch.setattr(gate, 'resume_ingress', lambda baseline: actions.append('resume'))

    def run(args, **kwargs):
        if 'show' in args:
            return 'active' if 'ai-gateway.service' in args else 'inactive'
        if 'start' in args:
            raise RuntimeError('candidate start failed')
        return ''

    monkeypatch.setattr(gate, 'run', run)
    with pytest.raises(RuntimeError):
        gate.switch(new, old, {}, {'clients': {}})
    assert current.resolve() == new
    assert actions == ['quiesce']


def test_config_has_no_private_site_harness_dependency():
    gate = module()
    cfg = gate.config()
    assert cfg == {
        'bridge_health_url': 'http://127.0.0.1:8080/health',
        'api_token_file': None,
    }
    assert gate.CHECKS == (
        'messaging_connectivity',
        'matched_clients_unchanged',
        'media_preflight',
    )


def test_finalize_cannot_pass_missing_smokes(monkeypatch, tmp_path):
    gate = module()
    sha = 'a' * 40
    state = tmp_path / sha
    state.mkdir()
    monkeypatch.setattr(gate, 'STATE', tmp_path)
    monkeypatch.setattr(gate, 'config', lambda: {})
    monkeypatch.setattr(gate, 'run', lambda *a, **k: sha)
    monkeypatch.setattr(gate.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(gate, 'digest', lambda *a: 'hash')
    monkeypatch.setattr(gate, 'runtime', lambda *a: None)
    monkeypatch.setattr(gate, 'verify_release', lambda *a: {'source_git_sha': sha})
    gate.write_once(
        state / 'baseline.json',
        {
            'source_sha': sha,
            'rollback_sha': gate.D6_SHA,
            'candidate': 'stage-e-' + sha[:12],
            'rollback': gate.D6.name,
            'rollback_checksums': 'hash',
        },
    )
    gate.write_once(state / 'installed.json', {'source_sha': sha, 'checksums': 'hash'})
    with pytest.raises(FileNotFoundError):
        gate.main('90_finalize')


def test_stage_e_release_metadata_matches_actual_builder(tmp_path):
    import re

    spec = importlib.util.spec_from_file_location(
        'stage_e_meta_test', ROOT / 'deploy/stage-e/validate_release_metadata.py'
    )
    metadata = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metadata)
    builder = (ROOT / 'deploy/stage-e/build_release.sh').read_text()
    for tag, target in (
        ('MANIFEST', 'metadata/release-manifest.yaml'),
        ('STAMP', 'RELEASE'),
    ):
        content = re.search(r'<<' + tag + r'\n(.*?)\n' + tag, builder, re.S)[1]
        content = content.replace('$RELEASE_ID', 'stage-e-' + 'a' * 12).replace(
            '$SOURCE_SHA', 'a' * 40
        )
        path = tmp_path / target
        path.parent.mkdir(exist_ok=True)
        path.write_text(content + '\n')
    metadata.validate(tmp_path)
    stamp = tmp_path / 'RELEASE'
    stamp.write_text(
        stamp.read_text().replace(
            'platform_api_contract_version=1', 'platform_api_contract_version=2'
        )
    )
    with pytest.raises(ValueError):
        metadata.validate(tmp_path)


def test_preflight_is_non_idle_and_has_safe_diagnostic_labels():
    text = (ROOT / 'deploy/stage-e/autopilot/gate.py').read_text()
    assert "runtime(D6, cfg, require_idle=False)" in text
    assert "PREFLIGHT_FAIL=" in text
    assert "preflight_step('hermes_connected'" in text
    assert "preflight_step('media_preflight'" in text
