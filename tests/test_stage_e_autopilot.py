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
    monkeypatch.setattr(gate, 'quiesce', lambda baseline, allow_gateway_unavailable=False: actions.append('quiesce'))
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

    def fail_quiesce(_baseline, allow_gateway_unavailable=False):
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
    monkeypatch.setattr(gate, 'quiesce', lambda baseline, allow_gateway_unavailable=False: actions.append('quiesce'))
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
    assert cfg == {'api_token_file': None}
    assert gate.CHECKS == (
        'messaging_connectivity',
        'hermes_inference',
        'matched_clients_unchanged',
        'media_preflight',
        'real_media',
    )


def test_bridge_health_url_inherits_effective_stage_d_bind(monkeypatch):
    gate = module()
    monkeypatch.setattr(
        gate,
        'run',
        lambda *a, **k: 'FOO=bar AI_BRIDGE_HOST=192.168.1.55 OTHER=value',
    )
    assert gate.bridge_health_url() == 'http://192.168.1.55:8080/health'

    monkeypatch.setattr(
        gate,
        'run',
        lambda *a, **k: 'AI_BRIDGE_HOST=0.0.0.0',
    )
    assert gate.bridge_health_url() == 'http://127.0.0.1:8080/health'


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
    assert "PREFLIGHT_FAIL=" in text
    assert "preflight_runtime(cfg)" in text
    assert "preflight_step('bridge_health_url'" in text
    assert "preflight_step('bridge_health'" in text
    assert "preflight_step('matched_clients'" in text
    assert "preflight_step('hermes_connected'" in text
    assert "preflight_step('media_preflight'" in text


def test_stage_e_gate_runs_git_as_worktree_owner():
    text = (ROOT / 'deploy/stage-e/autopilot/gate.py').read_text()
    assert "def git_run(" in text
    assert "'runuser', '-u', name" in text
    assert "git_run(['rev-parse', 'HEAD'])" in text
    assert "git_run(['status', '--porcelain'])" in text
    assert "run(['git', '-C', ROOT" not in text


def test_stage_e_builder_uses_owner_git_and_verified_source_sha():
    text = (ROOT / 'deploy/stage-e/build_release.sh').read_text()
    assert 'ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"' in text
    assert 'ugit()' in text
    assert 'HEAD_SHA="$(ugit -C "$ROOT" rev-parse HEAD)"' in text
    assert 'SOURCE_SHA="${STAGE_E_SOURCE_SHA:-$HEAD_SHA}"' in text
    assert 'ugit -C "$ROOT" archive "$SOURCE_SHA"' in text
    assert not any(
        line.strip().startswith('git -C "$ROOT" archive "$SOURCE_SHA"')
        for line in text.splitlines()
    )


def test_hermes_user_systemd_sets_home_and_runtime_dir():
    text = (ROOT / 'deploy/stage-e/autopilot/gate.py').read_text()
    assert "f'HOME={home}'" in text
    assert "f'XDG_RUNTIME_DIR=/run/user/{uid}'" in text


def test_api_smoke_accepts_completed_tokenized_empty_content(monkeypatch):
    gate = module()
    seen = {'request_id': None}
    def fake_fetch(url, payload=None, token=None, with_headers=False):
        if url.endswith('/health'): return {'readiness': True}
        if url.endswith('/models'): return {'models': [{'logical_id': 'reasoning-main'}]}
        if url.endswith('/systems'): return {'systems': [{'system_id': 'wvc'}]}
        if url.endswith('/ai'):
            seen['request_id'] = payload['context']['request_id']
            return {'request_id': seen['request_id'], 'state': 'completed',
                    'content': '', 'finish_reason': 'stop', 'job_id': 'job_test',
                    'usage': {'input_tokens': 17, 'output_tokens': 1},
                    'execution': {'model': 'reasoning-main'}}
        if url.endswith('/jobs/job_test'):
            return {'job': {'job_id': 'job_test', 'request_id': seen['request_id'], 'state': 'completed'}}
        if url.endswith('/jobs'): return {'jobs': [{'job_id': 'job_test'}]}
        raise AssertionError(url)
    monkeypatch.setattr(gate, 'fetch', fake_fetch)
    gate.api_smoke({'api_token_file': None})


def test_emergency_switch_to_d6_can_quiesce_without_gateway_status(monkeypatch, tmp_path):
    gate = module()
    d6, candidate = tmp_path / 'd6', tmp_path / 'candidate'
    d6.mkdir(); candidate.mkdir()
    current = tmp_path / 'current'
    current.symlink_to(candidate)
    monkeypatch.setattr(gate, 'CURRENT', current)
    monkeypatch.setattr(gate, 'D6', d6)
    monkeypatch.setattr(gate, 'verify_release', lambda *a: {'source_git_sha': gate.D6_SHA})
    monkeypatch.setattr(gate, 'clients', lambda: {})
    monkeypatch.setattr(gate, 'comfy_idle', lambda: None)
    actions = []
    monkeypatch.setattr(gate, 'quiesce', lambda baseline, allow_gateway_unavailable=False: actions.append(allow_gateway_unavailable))
    monkeypatch.setattr(gate, 'idle', lambda: (_ for _ in ()).throw(ConnectionError('gateway down')))
    monkeypatch.setattr(gate, 'runtime', lambda *a: None)
    monkeypatch.setattr(gate, 'resume_ingress', lambda baseline: actions.append('resume'))
    def fake_run(args, **kwargs):
        if 'show' in args and 'ai-bridge-analysis.service' in args: return 'inactive'
        return ''
    monkeypatch.setattr(gate, 'run', fake_run)
    gate.switch(d6, candidate, {}, {'clients': {}})
    assert current.resolve() == d6
    assert actions == [True, 'resume']


def test_stage_e_smoke_has_fresh_hermes_and_real_media_checks():
    text = (ROOT / 'deploy/stage-e/autopilot/gate.py').read_text()
    assert 'def hermes_oneshot_smoke' in text
    assert "HERMES_HOME=/srv/ai-data/hermes" in text
    assert "job.get('capability') == 'chat'" in text
    assert 'def real_media_smoke' in text
    assert "deploy/stage-e/validate_media_runtime.sh" in text
    assert "require((platforms.get('discord') or {}).get('state') == 'connected')" in text


def test_stage_e_real_media_helper_is_parseable_and_stage_bound():
    path = ROOT / 'deploy/stage-e/validate_media_runtime.sh'
    subprocess.run(['bash', '-n', path], check=True)
    text = path.read_text()
    assert "grep -qx 'stage=E'" in text
    assert 'stage-e-media-smoke' in text
    assert '--duration-seconds", "1"' in text
    assert 'media-video' in text
