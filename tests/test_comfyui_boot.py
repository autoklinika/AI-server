"""Boot readiness and refusal boundaries; no systemd or GPU changes."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'deploy/comfyui-boot'


def load(name):
    spec = importlib.util.spec_from_file_location('boot_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('change', [
    {'cleanup_pending': True}, {'loaded_models': 1}, {'queue_running': 1},
    {'queue_pending': 1}, {'loaded_models': False}, {'schema_version': True},
])
def test_comfy_start_cannot_finish_with_unusable_or_busy_runtime(change):
    ready = load('wait_ready')
    value = {'schema_version': 1, 'loaded_models': 0, 'queue_running': 0,
             'queue_pending': 0, 'cleanup_pending': False, **change}
    with patch.object(ready, 'fetch', return_value=value):
        assert ready.ready('comfyui') is False


def test_hermes_waits_through_connection_failure_until_gateway_ready():
    ready = load('wait_ready')
    health = {'status': 'ok', 'scheduler': {'admission_blocked': False},
              'gpu_residency': {'recovery_required': False}}
    with patch.object(ready, 'fetch', side_effect=[ConnectionRefusedError(), health]) as fetch, \
            patch.object(ready.time, 'sleep'):
        ready.wait('gateway', 2)
    assert fetch.call_count == 2


def test_unavailable_service_has_a_bounded_wait():
    ready = load('wait_ready')
    with patch.object(ready, 'fetch', side_effect=ConnectionRefusedError()), \
            patch.object(ready.time, 'monotonic', side_effect=[0, 0, 4]), \
            patch.object(ready.time, 'sleep'):
        with pytest.raises(RuntimeError, match='readiness timeout'):
            ready.wait('gateway', 3)


def blocked():
    return {'queued_count': 0, 'active_count': 1, 'admission_blocked': True,
            'gpu_residency': {'state': 'blocked', 'recovery_required': True, 'cleanup_evidence': None},
            'resource_leases': {'lease_count': 1, 'leases': [{
                'source': 'telegram-foto', 'in_use': 0, 'release_when_idle': True,
                'external_in_use': True,
                'external_workload': {'provider': 'comfyui-local', 'node': 'ai-node-01',
                                      'capability': 'image-generation'},
                'job': {'job_id': load('install').RECOVERY_JOB}}]}}


@pytest.mark.parametrize('fault', ['another_job', 'queued', 'active_call', 'another_provider',
                                  'another_boot', 'no_marker', 'extra_lease'])
def test_recorded_recovery_cannot_discard_other_work(tmp_path, fault):
    module = load('install')
    marker = tmp_path / 'blocked'
    marker.write_text('preserved')
    value = copy.deepcopy(blocked())
    lease = value['resource_leases']['leases'][0]
    boot = module.RECOVERY_BOOT
    if fault == 'another_job':
        lease['job']['job_id'] = 'job_other'
    elif fault == 'queued':
        value['queued_count'] = 1
    elif fault == 'active_call':
        lease['in_use'] = 1
    elif fault == 'another_provider':
        lease['external_workload']['provider'] = 'vision-local'
    elif fault == 'another_boot':
        boot = 'different-boot'
    elif fault == 'no_marker':
        marker.unlink()
    else:
        value['resource_leases']['lease_count'] = 2
    with patch.object(module, 'MARKER', marker), patch.object(module.Path, 'read_text', return_value=boot):
        with pytest.raises(RuntimeError):
            module.admissible(value)
    assert marker.exists() == (fault != 'no_marker')


def test_incomplete_package_cannot_install(tmp_path):
    module = load('install')
    (tmp_path / 'SHA256.json').write_text('{}\n')
    digest = module.hashlib.sha256((tmp_path / 'SHA256.json').read_bytes()).hexdigest()
    with patch.object(module, 'HERE', tmp_path):
        with pytest.raises(RuntimeError, match='unexpected package files'):
            module.verify_sources(digest)


@pytest.mark.parametrize('state', ['inactive', 'failed'])
def test_stopped_hermes_may_retain_failed_exit_result(state):
    module = load('install')
    props = f'ActiveState={state}\nMainPID=0\nControlPID=0\nControlGroup='
    with patch.object(module, 'userctl', return_value=props):
        module.hermes_stopped()


@pytest.mark.parametrize('props', [
    'ActiveState=failed\nMainPID=5\nControlPID=0\nControlGroup=',
    'ActiveState=failed\nMainPID=0\nControlPID=5\nControlGroup=',
    'ActiveState=failed\nMainPID=0\nControlPID=0\nControlGroup=/user.slice/test',
    'ActiveState=deactivating\nMainPID=0\nControlPID=0\nControlGroup=',
])
def test_live_or_incompletely_stopped_hermes_blocks_recovery(props):
    module = load('install')
    with patch.object(module, 'userctl', return_value=props):
        with pytest.raises(RuntimeError, match='process or cgroup remains'):
            module.hermes_stopped()


def test_preinstall_resume_preserves_original_evidence(tmp_path):
    module = load('install')
    marker = tmp_path / 'live-marker'
    marker.write_text('keep marker')
    state = tmp_path / 'state'
    status = blocked()
    with patch.object(module, 'STATE', state), patch.object(module, 'MARKER', marker), \
            patch.object(module, 'command', return_value='system unit'), \
            patch.object(module, 'userctl', return_value='user unit'):
        module.record_before(status)
        original = {p.name: p.read_bytes() for p in state.iterdir()}
        actual_stat = module.Path.stat
        def root_checkpoint(path, *args, **kwargs):
            value = actual_stat(path, *args, **kwargs)
            return SimpleNamespace(st_uid=0, st_mode=value.st_mode) if path == state else value
        with patch.object(module.Path, 'stat', root_checkpoint):
            module.record_before(status)
            assert {p.name: p.read_bytes() for p in state.iterdir()} == original
            changed = copy.deepcopy(status)
            changed['resource_leases']['leases'][0]['job']['job_id'] = 'job_other'
            with pytest.raises(RuntimeError, match='differs from saved'):
                module.record_before(changed)
            (state / 'RESULT.json').write_text('{}')
            with pytest.raises(RuntimeError, match='progressed past'):
                module.record_before(status)
    assert marker.read_text() == 'keep marker'
