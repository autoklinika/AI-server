"""CPU-only security and lifecycle tests. No GPU or system service mutations."""
import importlib.util
import json
from pathlib import Path
from dataclasses import replace

import pytest

from ai_bridge.gateway.vision_lifecycle import VisionOwner, VisionSession
from ai_bridge.gateway.vision_radio_client import RadioExecutorClient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('radio_supervisor', ROOT / 'deploy/vision-radio/radio_supervisor.py')
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def evidence():
    return {'Id': 'ai-radio-' + 'a' * 32 + '.service', 'User': 'ai-vision', 'Group': 'ai-vision-rm',
        'InvocationID': 'b' * 32, 'MainPID': '0', 'ExecMainPID': '123',
        'ActiveState': 'active', 'SubState': 'exited', 'Result': 'success',
        'ExecMainCode': '1', 'ExecMainStatus': '0',
        'ControlGroup': '/system.slice/ai-radio-' + 'a' * 32 + '.service',
        'Delegate': 'no', 'KillMode': 'control-group', 'NoNewPrivileges': 'yes',
        'ProtectControlGroups': 'yes', 'PrivateNetwork': 'yes', 'RestrictNamespaces': 'yes',
        'ExecMainExitTimestampMonotonic': '100'}


def test_terminal_and_kernel_empty_are_both_required(tmp_path):
    data = evidence()
    group = tmp_path / data['ControlGroup'].lstrip('/')
    group.mkdir(parents=True)
    (group / 'cgroup.events').write_text('populated 0\nfrozen 0\n')
    (group / 'cgroup.procs').write_text('')
    assert supervisor.closed_scope(data, data, tmp_path)
    (group / 'cgroup.events').write_text('populated 1\nfrozen 0\n')
    with pytest.raises(RuntimeError, match='descendants'):
        supervisor.closed_scope(data, data, tmp_path)


@pytest.mark.parametrize('key,value', [
    ('InvocationID', 'stale'), ('ExecMainPID', '999'), ('User', 'root'),
    ('MainPID', '123'), ('Result', 'timeout'), ('ExecMainCode', '2'),
    ('ExecMainStatus', '1'), ('SubState', 'running'), ('Delegate', 'yes'),
    ('NoNewPrivileges', 'no'), ('PrivateNetwork', 'no'), ('KillMode', 'process'),
    ('ControlGroup', '/system.slice/other.service'), ('ExecMainExitTimestampMonotonic', '0'),
    ('RestrictNamespaces', 'no'), ('ProtectControlGroups', 'no'),
])
def test_uncertain_or_changed_terminal_never_authorizes(key, value, tmp_path):
    expected = evidence()
    altered = {**expected, key: value}
    (tmp_path / 'system.slice').mkdir()
    with pytest.raises(RuntimeError):
        supervisor.closed_scope(altered, expected, tmp_path)


def test_systemd_clears_removed_cgroup_only_after_same_terminal_invocation(tmp_path):
    expected = evidence()
    (tmp_path / 'system.slice').mkdir()
    # Observed with a REAL CPU transient service on the target host: active/
    # exited, status 0, same invocation, but ControlGroup is cleared by systemd.
    assert supervisor.closed_scope({**expected, 'ControlGroup': ''}, expected, tmp_path)
    with pytest.raises(RuntimeError):
        supervisor.closed_scope({**expected, 'ControlGroup': '', 'InvocationID': 'different'}, expected, tmp_path)


def test_missing_cgroup_mount_is_not_empty(tmp_path):
    expected = evidence()
    with pytest.raises(RuntimeError, match='filesystem unavailable'):
        supervisor.closed_scope(expected, expected, tmp_path)


@pytest.mark.parametrize('value', [None, {}, {'lease_id': 'x', 'use_id': 'x', 'job_id': 1},
    {'lease_id': 'a'*24, 'use_id': 'b'*24, 'job_id': True},
    {'lease_id': '../'*10, 'use_id': 'b'*24, 'job_id': 1}])
def test_invalid_owner(value):
    with pytest.raises(RuntimeError):
        supervisor.parse_owner(value)


def test_duplicate_json_cannot_override_identity():
    with pytest.raises(RuntimeError):
        supervisor.strict_json(b'{"op":"health","op":"prepare"}')


@pytest.mark.anyio
async def test_client_uses_root_proof_and_never_worker_sync_as_release(monkeypatch):
    client = RadioExecutorClient()
    owner = VisionOwner('a'*24, 'b'*24, 1)
    session = VisionSession('c'*32, 'worker', 'local-primary')
    calls = []
    def request(op, **fields):
        calls.append(op)
        if op == 'health': return {'ok': True, 'implementation': 'radio-legacy-exclusive-v1'}
        if op == 'prepare': return {'ok': True, 'session': session.__dict__}
        if op == 'verify': return {'ok': True, 'active': True}
        if op == 'inspect': return {'ok': True, 'result': {'image_id': 'pcb-1'}}
        return {'ok': True, 'proof': 'WORKER_LOCAL_SYNC', 'owner': owner.__dict__, 'session': session.__dict__}
    monkeypatch.setattr(client, '_call', request)
    assert client.available()
    assert await client.prepare(owner) == session
    assert client.verify(owner, session)
    assert not client.verify(replace(owner, job_id=2), session)
    assert (await client.inspect(owner, session, 'pcb-1'))['image_id'] == 'pcb-1'
    with pytest.raises(RuntimeError, match='closure proof'):
        await client.cleanup(owner, session)
    assert not client.closed


@pytest.mark.anyio
async def test_valid_supervisor_proof_is_bound_and_reusable_for_next_session(monkeypatch):
    client = RadioExecutorClient()
    owner = VisionOwner('a'*24, 'b'*24, 1)
    session = VisionSession('c'*32, 'worker', 'local-primary')
    def request(op, **fields):
        if op == 'prepare': return {'ok': True, 'session': session.__dict__}
        if op == 'verify': return {'ok': True, 'active': True}
        return {'ok': True, 'proof': 'SUPERVISED_SCOPE_CLOSED',
                'owner': owner.__dict__, 'session': session.__dict__, 'gpu_reuse_safe': 'NOT_VERIFIED'}
    monkeypatch.setattr(client, '_call', request)
    await client.prepare(owner)
    assert (await client.cleanup(owner, session)).release_authorized
    assert not client.verify(owner, session)
    await client.prepare(replace(owner, job_id=2))
    assert not client.closed


def test_worker_import_inert_and_wrong_uid_or_arguments_cannot_launch(monkeypatch):
    spec = importlib.util.spec_from_file_location('radio_worker', ROOT / 'deploy/vision-radio/radio_worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    monkeypatch.setattr(worker.sys, 'argv', ['worker', '../../x'])
    assert worker.main() == 2
    monkeypatch.setattr(worker.sys, 'argv', ['worker', 'a'*32])
    monkeypatch.setattr(worker.os, 'getuid', lambda: 1000)
    with pytest.raises(RuntimeError, match='ai-vision UID'):
        worker.main()


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / ('tools/' + name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_manifest_rejects_path_escape_and_wrong_digest(tmp_path):
    import hashlib
    installer = load_tool('install_vision_radio_pilot')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'../escape.py': 'x'}))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError, match='manifest digest'):
        installer.verified_files(tmp_path, manifest, 'wrong')
    with pytest.raises(RuntimeError, match='unsafe manifest'):
        installer.verified_files(tmp_path, manifest, digest)


def test_pilot_failure_restores_prior_gateway_blocked_and_keeps_marker(tmp_path, monkeypatch):
    import subprocess
    pilot = load_tool('vision_radio_hardware_pilot')
    pilot.MARKER = tmp_path / 'gpu.blocked'
    pilot.REPORT = tmp_path / 'report.json'
    idle = {'active_count': 0, 'queued_count': 0, 'admission_blocked': False,
            'resource_leases': {'lease_count': 0}, 'resource_manager': {'state': 'IDLE'},
            'gpu_residency': {'recovery_required': False}}
    calls = []
    def command(*args):
        calls.append(args)
        return '123' if 'MainPID' in args else 'active'
    async def failed_run():
        raise RuntimeError('simulated uncertain worker')
    monkeypatch.setattr(pilot, 'command', command)
    monkeypatch.setattr(pilot, 'read', lambda _: idle if not pilot.MARKER.exists() else {'admission_blocked': True})
    monkeypatch.setattr(pilot, 'production_marker', lambda _: None)
    monkeypatch.setattr(pilot, 'run_pilot', failed_run)
    monkeypatch.setattr(pilot, 'reserve_window', lambda: '/resource/leases/test-window')
    monkeypatch.setattr(pilot.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(pilot.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 3, 'inactive\n', ''))
    assert pilot.main() == 2
    assert pilot.MARKER.exists()
    result = json.loads(pilot.REPORT.read_text())
    assert result['result'] == 'BLOCKED' and result['prior_gateway_restored'] is True
    assert ('systemctl', 'stop', 'ai-gateway.service') in calls
    assert ('systemctl', 'start', 'ai-gateway.service') in calls
    assert result['n1_grant'] == 'NOT_ADMITTED'


def test_busy_host_never_stops_production_gateway(tmp_path, monkeypatch):
    pilot = load_tool('vision_radio_hardware_pilot')
    pilot.REPORT = tmp_path / 'report.json'
    calls = []
    monkeypatch.setattr(pilot, 'read', lambda _: {'active_count': 1})
    monkeypatch.setattr(pilot, 'command', lambda *a: calls.append(a))
    monkeypatch.setattr(pilot.os, 'geteuid', lambda: 0)
    assert pilot.main() == 2
    assert calls == []


def test_wrong_rpc_owner_cannot_change_or_poison_another_execution():
    instance = object.__new__(supervisor.Supervisor)
    owner = {'lease_id': 'a'*24, 'use_id': 'b'*24, 'job_id': 1}
    instance.active = {'owner': owner, 'session': {'generation': 'c'*32}}
    instance.blocked = False
    with pytest.raises(RuntimeError, match='wrong owner'):
        instance.dispatch({'op': 'cleanup', 'owner': {**owner, 'use_id': 'd'*24}, 'session': {'generation': 'c'*32}})
    assert instance.blocked is False and instance.active['owner'] == owner


def test_racing_job_wins_window_and_queued_pilot_is_cancelled(monkeypatch):
    pilot = load_tool('vision_radio_hardware_pilot')
    calls = []
    def request(method, path, body=None):
        calls.append((method, path))
        return {'lease_id': 'our-window', 'state': 'queued', 'job_id': 2}
    monkeypatch.setattr(pilot, 'request', request)
    with pytest.raises(RuntimeError, match='another job won'):
        pilot.reserve_window()
    assert calls == [('POST', '/resource/leases'), ('DELETE', '/resource/leases/our-window')]


def test_control_is_readable_by_fixed_worker_group_even_under_private_umask(tmp_path, monkeypatch):
    import os
    import stat
    chowns = []
    monkeypatch.setattr(supervisor.os, 'fchown', lambda fd, uid, gid: chowns.append((uid, gid)))
    prior = os.umask(0o077)
    try:
        supervisor.Supervisor.control(tmp_path, 'execute')
    finally:
        os.umask(prior)
    assert stat.S_IMODE((tmp_path / 'execute').stat().st_mode) == 0o640
    assert (tmp_path / 'execute').read_text() == '1\n'
    assert chowns == [(0, 972)]
