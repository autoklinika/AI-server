"""Deployment safety and production opt-in. CPU-only, no service mutations."""
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.settings import Settings
from test_gateway_priority_classes import api_client
from test_vision_engine_lifecycle import make

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vision_deploy', ROOT / 'tools/deploy_vision_radio.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_production_default_does_not_connect_to_radio(tmp_path, monkeypatch):
    import ai_bridge.gateway.vision_radio_client as client
    def unexpected(): raise AssertionError('default must not connect')
    monkeypatch.setattr(client, 'RadioExecutorClient', unexpected)
    app, _ = make(tmp_path)
    async with api_client(app) as connection:
        status = (await connection.get('/status')).json()
        assert next(e for e in status['resource_manager']['engines'] if e['id'] == 'vision')['execution_available'] is False
        assert app.state.resource_leases.vision_executor is None


@pytest.mark.anyio
async def test_explicit_opt_in_registers_only_the_fixed_radio_client(tmp_path, monkeypatch):
    import ai_bridge.gateway.vision_radio_client as client
    runtime = SimpleNamespace(available=lambda: True, resource_id='local-primary')
    monkeypatch.setattr(client, 'RadioExecutorClient', lambda: runtime)
    app, _ = make(tmp_path, gateway_vision_radio_enabled=True)
    async with api_client(app) as connection:
        status = (await connection.get('/status')).json()
        assert next(e for e in status['resource_manager']['engines'] if e['id'] == 'vision')['execution_available'] is True
        assert app.state.resource_leases.vision_executor is runtime


def test_explicit_opt_in_refuses_an_unavailable_supervisor(tmp_path, monkeypatch):
    import ai_bridge.gateway.vision_radio_client as client
    monkeypatch.setattr(client, 'RadioExecutorClient', lambda: SimpleNamespace(available=lambda: False))
    with pytest.raises(RuntimeError, match='supervisor unavailable'):
        create_gateway_app(Settings(_env_file=None, gateway_gpu_marker=tmp_path / 'marker',
                                    gateway_vision_radio_enabled=True))


def test_radio_opt_in_requires_the_existing_exclusive_slot():
    with pytest.raises(RuntimeError, match='single-slot RM'):
        create_gateway_app(Settings(_env_file=None, gateway_vision_radio_enabled=True,
                                    gateway_max_concurrency=2))


def test_package_changes_are_detected_before_system_operations(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, 'MANIFEST', tmp_path / 'manifest.json')
    deploy.MANIFEST.write_text('{}')
    with pytest.raises(RuntimeError, match='manifest changed'): deploy.verified_files('not-the-hash')


def test_build_refuses_unrelated_production_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, 'OLD', tmp_path / 'old')
    deploy.OLD.mkdir()
    (deploy.OLD / 'SOURCE_SHA256.json').write_text(json.dumps({'src/other.py': 'old'}))
    files = {deploy.SOURCE: json.dumps({'src/other.py': 'changed'}).encode(), deploy.PATCH: b''}
    with pytest.raises(RuntimeError, match='unrelated production change'):
        deploy.build_tree(tmp_path / 'candidate', files)


def test_patch_cannot_write_outside_vision_files(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, 'OLD', tmp_path / 'old')
    deploy.OLD.mkdir()
    (deploy.OLD / 'SOURCE_SHA256.json').write_text('{}')
    files = {deploy.SOURCE: b'{}', deploy.PATCH: b'--- /dev/null\n+++ b/../../etc/unsafe\n'}
    with pytest.raises(RuntimeError, match='non-Vision path'):
        deploy.build_tree(tmp_path / 'candidate', files)


@pytest.mark.parametrize('field,value', [('result', 'BLOCKED'), ('gateway_uid', 0),
                                      ('prior_gateway_restored', False)])
def test_unverified_gpu_pilot_cannot_authorize_deployment(field, value):
    report = json.loads((ROOT / 'docs/reports/VISION_RADIO_GPU_PILOT_RESULT_2026-10-20.json').read_text())
    report[field] = value
    with pytest.raises(RuntimeError): deploy.validate_pilot(report)


@pytest.mark.parametrize('active,queued,leases', [(1, 0, 1), (0, 1, 0), (0, 0, 1)])
def test_rollback_never_stops_live_work(tmp_path, monkeypatch, active, queued, leases):
    monkeypatch.setattr(deploy, 'DROPIN', tmp_path / 'vision.conf')
    deploy.DROPIN.write_text('ours')
    calls = []
    monkeypatch.setattr(deploy, 'command', lambda *args: calls.append(args) or 'active')
    base = SimpleNamespace(json_get=lambda _: {'active_count': active, 'queued_count': queued,
                                               'resource_leases': {'lease_count': leases}})
    with pytest.raises(RuntimeError, match='live work must complete'):
        deploy.restore(base, 'ours')
    assert not any(call[:2] == ('systemctl', 'stop') for call in calls)
    assert deploy.DROPIN.read_text() == 'ours'


def test_rollback_never_removes_an_unknown_override(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, 'DROPIN', tmp_path / 'vision.conf')
    deploy.DROPIN.write_text('unknown')
    with pytest.raises(RuntimeError, match='unknown override'): deploy.restore(None, 'ours')
    assert deploy.DROPIN.read_text() == 'unknown'


@pytest.fixture
def operator(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, 'STATE', tmp_path)
    monkeypatch.setattr(deploy, 'DROPIN', tmp_path / 'vision.conf')
    report = json.loads((ROOT / 'docs/reports/VISION_RADIO_GPU_PILOT_RESULT_2026-10-20.json').read_text())
    (tmp_path / 'PILOT_RESULT.json').write_text(json.dumps(report))
    monkeypatch.setattr(deploy, 'trusted_file', lambda *a: None)
    monkeypatch.setattr(deploy, 'install', lambda *a: tmp_path / 'candidate')
    monkeypatch.setattr(deploy, 'module', lambda *a: object())
    calls = []
    monkeypatch.setattr(deploy, 'command', lambda *a: calls.append(a) or '')
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1 if 'is-enabled' in args else 0,
                                           'disabled' if 'is-enabled' in args else '', '')
    monkeypatch.setattr(deploy.subprocess, 'run', run)
    monkeypatch.setattr(deploy, 'smoke', lambda *a: None)
    return calls


def test_cutover_rollback_and_final_activation_are_all_required(operator, monkeypatch):
    switches = []
    monkeypatch.setattr(deploy, 'switch', lambda base, pilot, content: switches.append(content))
    result = deploy.apply({}, 'a'*64, None)
    assert result['result'] == 'VISION_PRODUCTION_PASS'
    assert [s is None for s in switches] == [False, True, False]
    assert operator[-1] == ('systemctl', 'enable', 'ai-platform-radio.service')


def test_candidate_gpu_failure_never_changes_production_override(operator, monkeypatch):
    monkeypatch.setattr(deploy.subprocess, 'run', lambda args, **kw:
        subprocess.CompletedProcess(args, 1 if 'is-enabled' in args else 2, 'disabled', ''))
    monkeypatch.setattr(deploy, 'switch', lambda *a: pytest.fail('GPU failure must precede switch'))
    with pytest.raises(RuntimeError, match='candidate GPU pilot failed'):
        deploy.apply({}, 'a'*64, None)
    assert not deploy.DROPIN.exists()
    assert operator[-1] == ('systemctl', 'stop', 'ai-platform-radio.service')


def test_cutover_failure_restores_previous_gateway(operator, monkeypatch):
    calls = []
    def fail(*a): raise RuntimeError('candidate unhealthy')
    monkeypatch.setattr(deploy, 'switch', fail)
    monkeypatch.setattr(deploy, 'restore', lambda *a: calls.append('restored'))
    with pytest.raises(RuntimeError, match='candidate unhealthy'): deploy.apply({}, 'a'*64, None)
    assert calls == ['restored']
    assert not any(call[:2] == ('systemctl', 'enable') for call in operator)


def test_root_supervisor_remains_available_when_busy_rollback_is_deferred(operator, monkeypatch):
    def race(*a):
        deploy.DROPIN.write_text('candidate-active')
        raise RuntimeError('new work won maintenance window')
    def deferred(*a): raise RuntimeError('rollback deferred: live work must complete first')
    monkeypatch.setattr(deploy, 'switch', race)
    monkeypatch.setattr(deploy, 'restore', deferred)
    with pytest.raises(RuntimeError, match='rollback deferred'): deploy.apply({}, 'a'*64, None)
    assert deploy.DROPIN.exists()
    assert operator[-1] != ('systemctl', 'stop', 'ai-platform-radio.service')
