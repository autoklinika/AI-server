#!/usr/bin/env python3
"""Root-owned fixed RADIO executor for the EXISTING legacy-exclusive Gateway.

No queue, scheduling, arbitrary programs or N1 grants. A single owned execution
is contained by systemd, and only the trusted parent can attest scope closure.
GPU_REUSE_SAFE remains NOT_VERIFIED: this is per-execution lifecycle evidence.
"""
from __future__ import annotations
import hashlib
import grp
import importlib.util
import json
import math
import os
from pathlib import Path
import pwd
import re
import secrets
import socket
import socketserver
import struct
import subprocess
import time

STATE = Path('/var/lib/ai-platform-radio')
SOCKET = Path('/run/ai-platform-radio/executor.sock')
WORKER = Path(__file__).with_name('radio_worker.py')
RUNTIME = Path('/srv/ai-data/evaluation/vision-pcb-envs/anomalyvfm-radio-rocm714-py311/bin/python')
BASE_PYTHON = Path('/home/harrypotter/.local/share/uv/python/cpython-3.11.16-linux-x86_64-gnu')
OBSERVER = Path('/usr/local/libexec/ai-platform/vision-gpu-observer.py')
PCI = '0000:c6:00.0'
IMAGE_ID = 'visa-pcb2-normal-0000'
WEIGHT_SHA = '50a219ba436ed656ad3c0405f9e81df8ad00b2e715c98be66d7e2edb62a83a37'
IMAGE_SHA = 'b3f01fc1c1bd43df2c5a1afa63348097f7ecbcc9ebe2fd43bed6f2d074531a37'
FAULT = re.compile(r'amdgpu.*(fault|reset|timeout|hang)|MES.*(fault|timeout|failed)', re.I)
PROPS = ('Id', 'User', 'Group', 'InvocationID', 'MainPID', 'ExecMainPID',
         'ActiveState', 'SubState', 'Result', 'ExecMainCode', 'ExecMainStatus',
         'ControlGroup', 'Delegate', 'KillMode', 'NoNewPrivileges', 'ProtectControlGroups',
         'RestrictNamespaces', 'PrivateNetwork', 'RestrictAddressFamilies', 'ExecMainExitTimestampMonotonic')


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def command(*args):
    process = subprocess.run(args, capture_output=True, text=True, timeout=12)
    # Fixed administrative commands only; keep stderr, never request arguments.
    detail = ' '.join(process.stderr.split())[:400]
    require(process.returncode == 0, 'system command failed: ' + args[0] + ': ' + detail)
    return process.stdout


def worker_command(unit, data, token):
    props = {'User': 'ai-vision', 'Group': 'ai-vision-rm',
        'RemainAfterExit': 'yes', 'KillMode': 'control-group', 'Delegate': 'no',
        'NoNewPrivileges': 'yes', 'ProtectControlGroups': 'yes', 'RestrictNamespaces': 'yes',
        'ProtectSystem': 'strict', 'ProtectHome': 'tmpfs', 'PrivateTmp': 'yes', 'PrivateNetwork': 'yes',
        # The installed systemd transient-property API rejects the textual
        # "none" even though systemd.exec documents it for unit files.
        'RestrictAddressFamilies': 'AF_UNIX', 'DevicePolicy': 'closed',
        'DeviceAllow': '/dev/kfd rw', 'MemoryMax': '16G', 'TasksMax': '64',
        'RuntimeMaxSec': '240', 'TimeoutStopSec': '10', 'UMask': '0077',
        'BindReadOnlyPaths': str(BASE_PYTHON), 'ReadWritePaths': str(data),
        'Environment': 'HF_HUB_OFFLINE=1', 'LimitCORE': '0'}
    args = ['systemd-run', '--quiet', '--unit=' + unit, '--service-type=exec']
    args.extend('--property=' + key + '=' + value for key, value in props.items())
    args.append('--property=DeviceAllow=/dev/dri/renderD128 rw')
    return args + ['--', str(RUNTIME), '-I', '-u', str(WORKER), token]


def trusted_file(path):
    require(path.is_absolute() and not path.is_symlink(), 'untrusted source path')
    for p in (path, *path.parents):
        info = p.stat()
        require(info.st_uid == 0 and not info.st_mode & 0o022, 'source writable or not root-owned')


def properties(unit):
    require(re.fullmatch(r'ai-radio-[0-9a-f]{32}\.service', unit) is not None, 'invalid unit')
    raw = command('systemctl', 'show', unit, '--no-pager', *['--property=' + p for p in PROPS])
    result = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    require(set(PROPS) <= set(result), 'incomplete systemd evidence')
    return result


def birth(pid):
    return int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19])


def parse_owner(value):
    require(type(value) is dict and set(value) == {'lease_id', 'use_id', 'job_id'}, 'invalid owner')
    require(type(value['job_id']) is int and 0 < value['job_id'] < 2**63, 'invalid job')
    for key in ('lease_id', 'use_id'):
        require(type(value[key]) is str and re.fullmatch(r'[A-Za-z0-9_-]{16,64}', value[key]), 'invalid owner token')
    return value


def closed_scope(props, expected, cgroup_root=Path('/sys/fs/cgroup')):
    """Terminal invocation AND kernel-empty cgroup. Missing data is not success.

    Kernel removal of this exact non-delegated cgroup is accepted only after
    systemd proves that same invocation exited naturally and successfully.
    """
    for key in ('Id', 'User', 'Group', 'InvocationID', 'ExecMainPID'):
        require(props.get(key) == expected.get(key) and bool(props.get(key)), 'changed invocation')
    require(props['User'] == 'ai-vision' and props['Group'] == 'ai-vision-rm', 'changed worker identity')
    require(props['Delegate'] == 'no' and props['KillMode'] == 'control-group'
            and props['NoNewPrivileges'] == 'yes' and props['ProtectControlGroups'] == 'yes'
            and props['PrivateNetwork'] == 'yes' and props['RestrictNamespaces'] == 'yes', 'containment changed')
    require(props['RestrictAddressFamilies'] == 'AF_UNIX', 'network containment changed')
    require(props['MainPID'] == '0' and props['ActiveState'] == 'active' and props['SubState'] == 'exited'
            and props['Result'] == 'success' and props['ExecMainCode'] == '1'
            and props['ExecMainStatus'] == '0'
            and int(props['ExecMainExitTimestampMonotonic']) > 0, 'worker not naturally completed')
    group = expected['ControlGroup']
    require(group == '/system.slice/' + props['Id'], 'unexpected cgroup path')
    require(props['ControlGroup'] in (group, ''), 'changed cgroup path')
    path = cgroup_root / group.lstrip('/')
    if path.exists():
        require(props['ControlGroup'] == group, 'detached cgroup evidence')
        events = dict(line.split() for line in (path / 'cgroup.events').read_text().splitlines())
        require(events.get('populated') == '0', 'execution descendants remain')
        require(not (path / 'cgroup.procs').read_text().strip(), 'cgroup still has processes')
    else:
        require(path.parent.is_dir(), 'cgroup filesystem unavailable')
    return True


def validate_result(result, map_path):
    expected = {'schema', 'image_id', 'execution_kind', 'model', 'weights_sha256',
                'image_sha256', 'image_score', 'map_shape', 'map_sha256',
                'inference_and_load_seconds', 'pci_bdf', 'worker_local_sync'}
    require(type(result) is dict and set(result) == expected and type(result['schema']) is int
            and result['schema'] == 1, 'unexpected result schema')
    require(result['image_id'] == IMAGE_ID and result['execution_kind'] == 'GPU_INFERENCE'
            and result['model'] == 'anomalyvfm-radio' and result['weights_sha256'] == WEIGHT_SHA
            and result['image_sha256'] == IMAGE_SHA and result['pci_bdf'] == PCI
            and result['worker_local_sync'] is True, 'result provenance mismatch')
    for key in ('image_score', 'inference_and_load_seconds'):
        require(type(result[key]) in (float, int) and math.isfinite(result[key]), 'nonfinite result')
    require(0 <= result['image_score'] <= 1 and 0 < result['inference_and_load_seconds'] <= 90
            and result['map_shape'] == [768, 768], 'invalid prediction contract')
    require(not map_path.is_symlink() and map_path.is_file()
            and map_path.stat().st_size == 2359424, 'invalid map file')
    require(hashlib.sha256(map_path.read_bytes()).hexdigest() == result['map_sha256'], 'map digest mismatch')
    return result


class Supervisor:
    def __init__(self):
        require(os.geteuid() == 0, 'root-owned supervisor required')
        trusted_file(WORKER)
        trusted_file(Path(__file__))
        trusted_file(OBSERVER)
        spec = importlib.util.spec_from_file_location('_trusted_gpu_observer', OBSERVER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Reuse the installed read-only collector; do not broaden its socket
        # authorization or modify its intentionally non-approving N1 protocol.
        self.collect_clients = module.snapshot_gpu_clients
        self.active = None
        self.marker = STATE / 'ownership.dirty'
        self.blocked = self.marker.exists() or (STATE / 'ownership.tmp').exists()
        mountinfo = Path('/proc/self/mountinfo').read_text().splitlines()
        require(any(line.split()[4] == '/sys/fs/cgroup' and line.split(' - ')[1].split()[0] == 'cgroup2'
                    for line in mountinfo), 'cgroup v2 mount not available')
        require(Path('/sys/fs/cgroup/cgroup.controllers').is_file(), 'cgroup v2 evidence missing')
        self.boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.worker_uid = pwd.getpwnam('ai-vision').pw_uid
        self.worker_gid = grp.getgrnam('ai-vision-rm').gr_gid
        require(self.worker_uid == 994 and self.worker_gid == 972, 'account provisioning changed')

    def persist(self, value):
        temp = self.marker.with_name('ownership.tmp')
        with temp.open('x') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, self.marker)
        self.sync_dir(STATE)

    @staticmethod
    def sync_dir(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def snapshot(self):
        observed = self.collect_clients()
        require(observed is not None, 'root GPU inventory incomplete')
        root = Path('/sys/class/kfd/kfd/proc')
        kfd = frozenset(int(p.name) for p in root.iterdir() if p.name.isdecimal())
        return frozenset(observed), kfd

    def no_driver_errors(self, cursor):
        require(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == self.boot, 'host rebooted')
        lines = command('journalctl', '-k', '--after-cursor=' + cursor, '--no-pager', '-o', 'json')
        require(not any(FAULT.search(json.loads(line).get('MESSAGE', '')) for line in lines.splitlines()), 'driver error observed')

    def check_active(self):
        require(self.active is not None and not self.blocked, 'execution unavailable')
        props = properties(self.active['unit'])
        require(props['InvocationID'] == self.active['properties']['InvocationID']
                and props['ControlGroup'] == self.active['properties']['ControlGroup']
                and props['MainPID'] == str(self.active['pid'])
                and props['ActiveState'] == 'active' and props['SubState'] == 'running', 'worker restarted or exited')
        pid = self.active['pid']
        require(birth(pid) == self.active['birth'] and Path(f'/proc/{pid}').stat().st_uid == 994
                and Path(f'/proc/{pid}/exe').resolve() == RUNTIME.resolve(), 'worker incarnation changed')
        return props

    def own(self, request):
        parse_owner(request.get('owner'))
        require(self.active is not None and request['owner'] == self.active['owner']
                and request.get('session') == self.active['session'], 'wrong owner or stale session')

    def prepare(self, owner):
        require(self.active is None and not self.blocked, 'previous execution unresolved')
        parse_owner(owner)
        mem = next(line for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
        require(int(mem.split()[1]) * 1024 >= 20 * (1 << 30), 'insufficient available host memory')
        baseline = self.snapshot()
        # Only previously accepted, idle production service contexts may remain.
        allowed = set()
        for unit in ('comfyui.service', 'ollama.service'):
            pid = int(command('systemctl', 'show', unit, '--property=MainPID', '--value').strip())
            require(pid > 1, 'provider not running')
            allowed.add((pid, birth(pid)))
        require(baseline[0] <= allowed and baseline[1] <= {p for p, _ in baseline[0]}, 'foreign GPU owner')
        cursor = json.loads(command('journalctl', '-k', '-n', '1', '--no-pager', '-o', 'json').strip())['__CURSOR']
        token = secrets.token_hex(32 // 2)
        unit = 'ai-radio-' + token + '.service'
        folder = STATE / 'sessions' / token
        folder.mkdir(mode=0o750)
        os.chown(folder, 0, self.worker_gid)
        folder.chmod(0o750)
        data = folder / 'data'
        data.mkdir(mode=0o750)
        os.chown(data, self.worker_uid, self.worker_gid)
        active = {'owner': owner, 'unit': unit, 'token': token,
                  'session': {'generation': token, 'worker_id': unit, 'resource_id': 'local-primary'},
                  'cursor': cursor, 'baseline': baseline, 'folder': folder, 'phase': 'prepare'}
        self.persist({'owner': owner, 'unit': unit, 'session': active['session'], 'boot': self.boot})
        self.active = active
        command(*worker_command(unit, data, token))
        deadline = time.monotonic() + 20
        while not (data / 'ready.json').is_file():
            require(time.monotonic() < deadline, 'parked worker readiness timeout')
            require(properties(unit)['ActiveState'] not in ('failed', 'inactive'), 'worker failed before readiness')
            time.sleep(.1)
        ready = json.loads((data / 'ready.json').read_text())
        p = properties(unit)
        pid = int(p['MainPID'])
        require(ready == {'pid': pid, 'uid': self.worker_uid}, 'worker readiness identity mismatch')
        require(p['ControlGroup'] == '/system.slice/' + unit and re.fullmatch('[0-9a-f]{32}', p['InvocationID']), 'invalid service identity')
        active.update(properties=p, pid=pid, birth=birth(pid), phase='ready')
        self.check_active()
        require(self.snapshot() == baseline, 'parked worker opened GPU before execute')
        return active['session']

    @staticmethod
    def control(folder, name):
        path = folder / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        try:
            os.write(fd, b'1\n')
            os.fchown(fd, 0, 972)
            os.fchmod(fd, 0o640)
            os.fsync(fd)
        finally:
            os.close(fd)

    def inspect(self, request):
        require(request.get('image_id') == IMAGE_ID, 'only pinned calibration image is admitted')
        self.check_active()
        active = self.active
        require(active['phase'] == 'ready', 'one inspection per execution')
        require(self.snapshot() == active['baseline'], 'GPU owners changed before execute')
        active['phase'] = 'executing'
        self.control(active['folder'], 'execute')
        result_path = active['folder'] / 'data/result.json'
        deadline = time.monotonic() + 85
        while not result_path.is_file():
            self.check_active()
            require(time.monotonic() < deadline, 'RADIO inference timeout')
            time.sleep(.2)
        require(not result_path.is_symlink() and result_path.stat().st_size <= 4096, 'invalid worker result file')
        result = validate_result(json.loads(result_path.read_text()), active['folder'] / 'data/anomaly.map.npy')
        live = self.snapshot()
        require(live[0] == active['baseline'][0] | {(active['pid'], active['birth'])}
                and live[1] == active['baseline'][1] | {active['pid']}, 'GPU worker ownership mismatch')
        self.no_driver_errors(active['cursor'])
        active['phase'] = 'done'
        return result

    def cleanup(self):
        self.check_active()
        active = self.active
        require(active['phase'] == 'done', 'no completed inspection')
        self.control(active['folder'], 'release')
        deadline = time.monotonic() + 20
        while properties(active['unit'])['MainPID'] != '0':
            require(time.monotonic() < deadline, 'worker did not exit')
            time.sleep(.2)
        terminal = properties(active['unit'])
        closed_scope(terminal, active['properties'])
        for _ in range(3):
            require(self.snapshot() == active['baseline'], 'GPU handles remain or foreign owner appeared')
            time.sleep(.15)
        self.no_driver_errors(active['cursor'])
        proof = {'ok': True, 'proof': 'SUPERVISED_SCOPE_CLOSED', 'owner': active['owner'],
                 'session': active['session'], 'gpu_reuse_safe': 'NOT_VERIFIED'}
        audit = active['folder'] / 'CLOSURE.json'
        with audit.open('x') as stream:
            json.dump({**proof, 'pid': active['pid'], 'birth': active['birth'],
                       'invocation_id': terminal['InvocationID'], 'cgroup': terminal['ControlGroup']}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        command('systemctl', 'stop', active['unit'])
        self.marker.unlink()
        self.sync_dir(STATE)
        self.active = None
        return proof

    def dispatch(self, request):
        require(type(request) is dict, 'JSON object required')
        operation = request.get('op')
        if operation == 'health' and set(request) == {'op'}:
            return {'ok': not self.blocked, 'implementation': 'radio-legacy-exclusive-v1'}
        if operation == 'prepare' and set(request) == {'op', 'owner'}:
            # Busy/invalid callers cannot poison or replace another owner.
            parse_owner(request['owner'])
            require(self.active is None and not self.blocked, 'busy or blocked')
            try:
                return {'ok': True, 'session': self.prepare(request['owner'])}
            except BaseException:
                if self.active is not None or self.marker.exists():
                    self.blocked = True
                raise
        require(operation in ('verify', 'inspect', 'cleanup'), 'invalid fixed operation')
        expected = {'op', 'owner', 'session'} | ({'image_id'} if operation == 'inspect' else set())
        require(set(request) == expected, 'unexpected operation fields')
        self.own(request)
        try:
            if operation == 'verify':
                self.check_active()
                return {'ok': True, 'active': True}
            if operation == 'inspect':
                return {'ok': True, 'result': self.inspect(request)}
            return self.cleanup()
        except BaseException:
            self.blocked = True  # No automatic kill, reset or marker removal.
            raise


def strict_json(data):
    def unique(pairs):
        result = dict(pairs)
        require(len(result) == len(pairs), 'duplicate JSON fields')
        return result
    return json.loads(data, object_pairs_hook=unique)


def main():
    supervisor = Supervisor()
    gateway_uid = pwd.getpwnam('harrypotter').pw_uid
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(5)
            _, uid, _ = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            try:
                require(uid in (0, gateway_uid), 'peer not authorized')
                line = self.rfile.readline(4097)
                require(len(line) <= 4096 and line.endswith(b'\n'), 'request too large')
                reply = supervisor.dispatch(strict_json(line))
            except Exception as error:
                reply = {'ok': False, 'error': type(error).__name__, 'reason': str(error)[:600]}
                try:
                    (STATE / 'LAST_ERROR.json').write_text(json.dumps({'type': type(error).__name__, 'reason': str(error)[:600]}) + '\n')
                except OSError:
                    pass
            self.wfile.write(json.dumps(reply, allow_nan=False).encode() + b'\n')
    require(not SOCKET.exists(), 'stale supervisor socket')
    with socketserver.UnixStreamServer(str(SOCKET), Handler) as server:
        os.chown(SOCKET, 0, pwd.getpwnam('harrypotter').pw_gid)
        os.chmod(SOCKET, 0o660)
        server.serve_forever(poll_interval=.2)


if __name__ == '__main__':
    main()
