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
        'RestrictAddressFamilies': 'AF_UNIX',
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
    ('RestrictAddressFamilies', '~'),
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
    def failed_run():
        raise RuntimeError('simulated uncertain worker')
    monkeypatch.setattr(pilot, 'command', command)
    monkeypatch.setattr(pilot, 'read', lambda _: idle if not pilot.MARKER.exists() else {'admission_blocked': True})
    monkeypatch.setattr(pilot, 'production_marker', lambda _: None)
    monkeypatch.setattr(pilot, 'run_as_gateway', failed_run)
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


def test_gateway_child_is_launched_with_production_uid_and_groups(monkeypatch):
    import subprocess
    import types
    pilot = load_tool('vision_radio_hardware_pilot')
    account = types.SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_name='harrypotter', pw_dir='/home/harrypotter')
    monkeypatch.setattr(pilot.pwd, 'getpwnam', lambda _: account)
    monkeypatch.setattr(pilot.os, 'getgrouplist', lambda *args: [1000, 44, 990])
    launches = []
    def child(args, **kwargs):
        launches.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, json.dumps({'ok': True, 'gateway_uid': 1000, 'radio_inspections': []}), '')
    monkeypatch.setattr(pilot.subprocess, 'run', child)
    assert pilot.run_as_gateway() == []
    args, kwargs = launches[0]
    assert args[-1] == '--gateway-window'
    assert kwargs['user'] == 1000 and kwargs['group'] == 1000
    assert kwargs['extra_groups'] == [1000, 44, 990]


@pytest.mark.parametrize('uid', [0, 993, 994])
def test_gateway_window_never_runs_as_root_or_worker_account(uid, monkeypatch):
    pilot = load_tool('vision_radio_hardware_pilot')
    monkeypatch.setattr(pilot.os, 'getuid', lambda: uid)
    monkeypatch.setattr(pilot.os, 'geteuid', lambda: uid)
    assert pilot.gateway_window() == 2


def test_recovery_requires_zero_radio_sessions_and_no_ownership_marker(tmp_path, monkeypatch):
    recovery = load_tool('vision_radio_recover_prelaunch')
    recovery.STATE = tmp_path
    (tmp_path / 'sessions').mkdir()
    monkeypatch.setattr(recovery, 'command', lambda *args: '')
    recovery.no_radio_execution()
    (tmp_path / 'sessions' / 'any-attempt').mkdir()
    with pytest.raises(RuntimeError, match='session exists'):
        recovery.no_radio_execution()
    (tmp_path / 'sessions' / 'any-attempt').rmdir()
    (tmp_path / 'ownership.dirty').write_text('unknown')
    with pytest.raises(RuntimeError, match='ownership evidence'):
        recovery.no_radio_execution()


def test_recovery_never_archives_an_unknown_block_marker(tmp_path, monkeypatch):
    recovery = load_tool('vision_radio_recover_prelaunch')
    recovery.MARKER = tmp_path / 'gpu.blocked'
    recovery.MARKER.write_text('Unrelated driver failure')
    with pytest.raises(RuntimeError, match='not the exact prelaunch'):
        recovery.host_evidence({'observed_at': '2026-10-20T08:27:20+00:00'})
    assert recovery.MARKER.read_text() == 'Unrelated driver failure'


def test_recovery_archives_marker_and_restores_gateway_without_reset(tmp_path, monkeypatch):
    recovery = load_tool('vision_radio_recover_prelaunch')
    recovery.STATE = tmp_path / 'state'
    recovery.MARKER = tmp_path / 'gpu.blocked'
    recovery.MARKER.write_bytes(recovery.MARKER_BYTES)
    report = {'result': 'BLOCKED'}
    monkeypatch.setattr(recovery, 'no_radio_execution', lambda: None)
    monkeypatch.setattr(recovery, 'host_evidence', lambda _: {'radio_never_started': True})
    calls = []
    monkeypatch.setattr(recovery, 'command', lambda *args: calls.append(args))
    monkeypatch.setattr(recovery, 'get', lambda _: {'resource_manager': {'state': 'IDLE'}, 'admission_blocked': False})
    result = recovery.archive_and_restore({'report': report})
    assert result['prelaunch_recovery'] == 'PASS'
    assert result['driver_reset'] == 'NOT_PERFORMED'
    assert not recovery.MARKER.exists()
    archived = list((recovery.STATE / 'prelaunch-recovery').glob('*/residency.blocked'))
    assert len(archived) == 1 and archived[0].read_bytes() == recovery.MARKER_BYTES
    assert calls == [('systemctl','stop','ai-gateway.service'), ('systemctl','start','ai-gateway.service')]


def test_fixed_transient_command_preserves_network_and_device_limits(tmp_path):
    args = supervisor.worker_command('ai-radio-' + 'a'*32 + '.service', tmp_path, 'a'*32)
    assert '--property=RestrictAddressFamilies=AF_UNIX' in args
    assert '--property=PrivateNetwork=yes' in args
    assert '--property=DevicePolicy=closed' in args
    assert '--property=DeviceAllow=/dev/kfd rw' in args
    assert '--property=DeviceAllow=/dev/dri/renderD128 rw' in args
    assert not any('=none' in arg for arg in args)
    assert args[-6:] == ['--', str(supervisor.RUNTIME), '-I', '-u', str(supervisor.WORKER), 'a'*32]


def test_admin_command_error_includes_bounded_stderr_without_arguments(monkeypatch):
    import subprocess
    monkeypatch.setattr(supervisor.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 1, '', 'Failed to set unit properties: Invalid argument\n' + 'x'*1000))
    with pytest.raises(RuntimeError, match='Failed to set unit properties') as error:
        supervisor.command('systemd-run', 'PRIVATE_OWNER_TOKEN')
    assert 'PRIVATE_OWNER_TOKEN' not in str(error.value) and len(str(error.value)) < 450


@pytest.fixture
def rejected_attempt(tmp_path, monkeypatch):
    import os
    recovery = load_tool('vision_radio_recover_launch_rejected')
    recovery.base = base = load_tool('vision_radio_recover_prelaunch')
    base.STATE = tmp_path
    token = 'a'*32
    unit = 'ai-radio-' + token + '.service'
    data = tmp_path / 'sessions' / token / 'data'
    data.mkdir(parents=True)
    boot = tmp_path / 'boot'
    boot.write_text('test-boot')
    proc = tmp_path / 'proc'
    proc.mkdir()
    recovery.Path = lambda p: (proc if p == '/proc' else
        tmp_path / 'worker-cgroup' if p.startswith('/sys/fs/cgroup/') else boot)
    own = {'owner': {'lease_id': 'b'*24, 'use_id': 'c'*24, 'job_id': 1}, 'unit': unit,
           'session': {'generation': token, 'worker_id': unit, 'resource_id': 'local-primary'}, 'boot': 'test-boot'}
    (tmp_path / 'ownership.dirty').write_text(json.dumps(own))
    (tmp_path / 'LAST_ERROR.json').write_text(json.dumps({'type': 'RuntimeError', 'reason': 'system command failed: systemd-run'}))
    for path in (data, data.parent, data.parent.parent): path.chmod(0o750)
    for name in ('ownership.dirty', 'LAST_ERROR.json'): (tmp_path / name).chmod(0o640)
    original_stat = Path.stat
    def stat(path, **kwargs):
        result = original_stat(path, **kwargs)
        if path.is_relative_to(tmp_path):
            values = list(result)
            values[4] = 994 if path == data or path.parent == proc else 0
            return os.stat_result(values)
        return result
    monkeypatch.setattr(Path, 'stat', stat)
    replies = {'list-units': '', 'show': 'LoadState=not-found\nMainPID=0\nInvocationID=', 'journalctl': ''}
    monkeypatch.setattr(base, 'command', lambda *a: replies[a[1] if a[0] == 'systemctl' else a[0]])
    return recovery, own, data, replies, proc


def test_launch_recovery_requires_exact_unexecuted_session(rejected_attempt):
    recovery, own, *_ = rejected_attempt
    assert recovery.rejected_execution() == own


@pytest.mark.parametrize('artifact', ['ready.json', 'result.json', 'anything.tmp'])
def test_launch_recovery_refuses_any_worker_artifact(rejected_attempt, artifact):
    recovery, own, data, *_ = rejected_attempt
    (data / artifact).write_text('{}')
    with pytest.raises(RuntimeError, match='artifacts'):
        recovery.rejected_execution()


@pytest.mark.parametrize('reason', ['execute', 'unit', 'cgroup', 'journal', 'ownership', 'other-session'])
def test_launch_recovery_preserves_uncertain_ownership(rejected_attempt, reason):
    recovery, own, data, replies, proc = rejected_attempt
    if reason == 'execute': (data.parent / 'execute').write_text('1\n')
    if reason == 'unit': replies['show'] = 'LoadState=loaded\nMainPID=123\nInvocationID=abc'
    if reason == 'cgroup': (recovery.base.STATE / 'worker-cgroup').mkdir()
    if reason == 'journal': replies['journalctl'] = '{"MESSAGE":"Started worker"}'
    if reason == 'ownership':
        own['session']['worker_id'] = 'different'
        (recovery.base.STATE / 'ownership.dirty').write_text(json.dumps(own))
    if reason == 'other-session': (data.parent.parent / ('d'*32)).mkdir()
    with pytest.raises(RuntimeError): recovery.rejected_execution()
    assert (recovery.base.STATE / 'ownership.dirty').exists()


@pytest.mark.parametrize('fail', [False, True])
def test_real_cpu_probe_precedes_recovery_and_preserves_block_on_failure(tmp_path, monkeypatch, fail):
    installer = load_tool('install_vision_radio_pilot')
    installer.STATE = tmp_path
    marker = tmp_path / 'ownership.dirty'
    marker.write_text('preserve previous failed attempt')
    monkeypatch.setattr(installer.os, 'chown', lambda *a: None)
    calls = []
    def run(*args):
        calls.append(args)
        if args[0] == 'systemd-run':
            if fail: raise RuntimeError('probe launch rejected')
            data = next(tmp_path.glob('config-probe-*/data'))
            (data / 'cpu-proof.json').write_text(json.dumps({'uid': 994, 'inet_denied': True}))
        if args[:2] == ('systemctl', 'show'):
            return 'ActiveState=active\nSubState=exited\nResult=success\nExecMainStatus=0'
        return ''
    monkeypatch.setattr(installer, 'command', run)
    files = {name: (ROOT / name).read_bytes() for name in
             ('deploy/vision-radio/radio_supervisor.py', 'deploy/vision-radio/radio_worker.py')}
    if fail:
        with pytest.raises(RuntimeError, match='probe launch rejected'): installer.worker_configuration_probe(files)
    else:
        installer.worker_configuration_probe(files)
    assert marker.read_text() == 'preserve previous failed attempt'
    assert not list(tmp_path.glob('config-probe-*'))
    assert '--property=User=ai-vision' in calls[0] and '--property=PrivateNetwork=yes' in calls[0]
    assert calls[-1][:2] == ('systemctl', 'stop')


def test_unrelated_ai_vision_cpu_process_does_not_identify_radio_worker(rejected_attempt):
    recovery, own, _, _, proc = rejected_attempt
    (proc / '123').mkdir()
    assert recovery.rejected_execution() == own


def test_cpu_processes_never_bypass_host_gpu_evidence(monkeypatch):
    recovery = load_tool('vision_radio_recover_launch_rejected')
    recovery.base = base = load_tool('vision_radio_recover_prelaunch')
    monkeypatch.setattr(recovery.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(base, 'previous_installation', lambda *a: 'unit')
    report = {'result': 'BLOCKED', 'prior_gateway_restored': True, 'production_install': 'NOT_PERFORMED',
              'error': 'RuntimeError: Gateway child failed: RuntimeError: Vision prepare failed closed',
              'supervisor_error': {'type': 'RuntimeError', 'reason': 'system command failed: systemd-run'},
              'observed_at': '2026-10-20T08:50:30+00:00'}
    monkeypatch.setattr(recovery, 'trusted_json', lambda *a: report)
    monkeypatch.setattr(recovery, 'rejected_execution', lambda *a: {})
    def foreign_gpu(*a): raise RuntimeError('unknown/foreign GPU owner')
    monkeypatch.setattr(base, 'host_evidence', foreign_gpu)
    with pytest.raises(RuntimeError, match='foreign GPU owner'): recovery.preflight()
