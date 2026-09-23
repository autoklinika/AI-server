import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_job_metrics_are_bounded_metadata_only():
    obs = load('src/ai_bridge/platform/observability.py', 'stage_i_observability')
    snapshot = {
        'recent_jobs': [{
            'job_id': 'job_1', 'request_id': 'req_1', 'domain': 'private-domain',
            'capability': 'reasoning', 'state': 'completed',
            'assigned_provider': 'ollama-local', 'assigned_node': 'ai-node-01',
            'queued_at': '2026-09-23T10:00:00+00:00',
            'admitted_at': '2026-09-23T10:00:00.100000+00:00',
            'started_at': '2026-09-23T10:00:00.110000+00:00',
            'finished_at': '2026-09-23T10:00:01.110000+00:00',
        }],
        'active': [], 'queued': [],
    }
    result = obs.job_metrics(snapshot)
    assert result['observed'] == 1
    assert result['states'] == {'completed': 1}
    assert result['providers'] == {'ollama-local': 1}
    assert result['queue_wait'] == {'count': 1, 'avg_ms': 100.0, 'max_ms': 100.0}
    assert result['execution'] == {'count': 1, 'avg_ms': 1000.0, 'max_ms': 1000.0}
    assert 'private-domain' not in str(result)
    assert 'req_1' not in str(result) and 'job_1' not in str(result)


def test_stage_i_release_validator_requires_observability_contract(tmp_path):
    validator = load('deploy/stage-i/validate_release_metadata.py', 'stage_i_metadata')
    sha = 'a' * 40
    release = tmp_path / 'release'
    (release / 'metadata').mkdir(parents=True)
    fields = {
        'release_id': 'stage-i-' + sha[:12], 'stage': 'I', 'phase': 'I',
        'source_git_sha': sha, 'ai_bridge_git_sha': sha, 'ai_gateway_git_sha': sha,
        'config_schema_version': '4', 'migration_version': 'observability-v1',
        'platform_api_contract_version': '1', 'observability_contract_version': '1',
        'resource_manager_contract_version': '2', 'priority_class_contract_version': '1',
        'job_state_contract_version': '1', 'provider_registry_schema_version': '1',
        'unified_admission_contract_version': '1', 'compatibility_contract_version': '1',
        'provider_model_config_version': 'test-config-v1',
    }
    (release / 'RELEASE').write_text('\n'.join(f'{k}={v}' for k, v in fields.items()) + '\n')
    manifest = f'''release:
  id: {fields["release_id"]}
  stage: I
  phase: I
  source_git_sha: {sha}
  config_schema_version: 4
  migration_version: observability-v1
  provider_model_config_version: test-config-v1
  contract_versions:
    platform_api: 1
    observability: 1
    resource_manager: 2
    priority_class: 1
    job_state: 1
    unified_admission: 1
    compatibility: 1
    llm_provider: 1
    agent_provider: 1
    media_generation_provider: 1
    embedding_provider: 1
    knowledge_backend: 1
  schema_versions:
    provider_registry: 1
ai_bridge:
  source_git_sha: {sha}
ai_gateway:
  source_git_sha: {sha}
'''
    (release / 'metadata/release-manifest.yaml').write_text(manifest)
    validator.validate(release)
    (release / 'RELEASE').write_text((release / 'RELEASE').read_text().replace(
        'observability_contract_version=1', 'observability_contract_version=2'))
    with pytest.raises(ValueError):
        validator.validate(release)


def test_stage_i_gate_is_pinned_to_verified_h_and_requires_functional_rollback():
    gate = (ROOT / 'deploy/stage-i/autopilot/gate.py').read_text()
    assert "BASE = Path('/opt/ai-platform/releases/stage-h-b9362bdae1c3')" in gate
    assert "BASE_SHA = 'b9362bdae1c30b53606d992fcecb575d7de71f4b'" in gate
    assert "observability_absent(cfg)" in gate
    assert "error.code == 404" in gate
    assert "baseline['hermes_active'] == 'active'" in gate
    assert "baseline['analysis_timer_active'] == 'active'" in gate
    assert "e.media_preflight()" in gate
    assert 'real_media_smoke' not in gate


def test_stage_i_control_plane_has_dedicated_resume_boundary():
    runner = (ROOT / 'deploy/autopilot/run_stage.sh').read_text()
    resume = (ROOT / 'deploy/autopilot/resume_pre_prod.sh').read_text()
    assert '^[EFGHI]$' in runner
    assert 'DEFAULT_WORKTREE="$HOME/agent-worktrees/stage-i"' in runner
    assert 'SESSION="$([[ "$STAGE" == "I" ]] && printf "stage-i-master"' in resume
    assert "exec '$CONTROL_DIR/run_stage.sh' I --resume-pre-prod" in resume
    assert 'agent/stage-$(printf' in resume


def test_gateway_disables_raw_uvicorn_access_log(monkeypatch):
    from types import SimpleNamespace
    import importlib

    gateway_main = importlib.import_module('ai_bridge.gateway.main')
    seen = {}
    monkeypatch.setattr(gateway_main, 'get_settings', lambda: SimpleNamespace(
        log_level='INFO', gateway_host='127.0.0.1', gateway_port=11435))
    monkeypatch.setattr(gateway_main.logging, 'basicConfig', lambda **kwargs: None)
    monkeypatch.setattr(gateway_main.uvicorn, 'run', lambda *args, **kwargs: seen.update(kwargs))
    gateway_main.main()
    assert seen['access_log'] is False
    assert seen['reload'] is False


def test_failed_build_rollback_is_noop_on_healthy_h(tmp_path, monkeypatch):
    gate = load('deploy/stage-i/autopilot/gate.py', 'stage_i_gate_failed_build')
    base = tmp_path / 'stage-h-b9362bdae1c3'
    base.mkdir()
    current = tmp_path / 'current'
    current.symlink_to(base)
    state = tmp_path / 'state'
    state.mkdir()
    calls = []
    monkeypatch.setattr(gate, 'BASE', base)
    monkeypatch.setattr(gate.e, 'CURRENT', current)
    monkeypatch.setattr(gate.e, 'runtime', lambda *args, **kwargs: calls.append('runtime'))
    monkeypatch.setattr(gate.e, 'switch', lambda *args, **kwargs: pytest.fail('healthy H was mutated'))
    monkeypatch.setattr(gate.e, 'user_systemctl', lambda args: 'active')
    monkeypatch.setattr(gate.e, 'run', lambda args, **kwargs: 'active')
    gate.rollback_to_h(state, tmp_path / 'candidate', {}, {'clients': {}, 'comfy': []})
    assert calls == ['runtime']
    receipt = gate.e.read(state / 'rollback.json')
    assert receipt['no_mutation'] is True


def test_built_candidate_rollback_uses_verified_switch(tmp_path, monkeypatch):
    gate = load('deploy/stage-i/autopilot/gate.py', 'stage_i_gate_built')
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'installed.json').write_text('{}')
    switched = []
    monkeypatch.setattr(gate.e, 'switch', lambda *args, **kwargs: switched.append(args))
    gate.rollback_to_h(state, tmp_path / 'candidate', {}, {'rollback': 'ignored'})
    assert len(switched) == 1
    assert switched[0][0] == gate.BASE
    assert gate.e.read(state / 'rollback.json')['no_mutation'] is False
