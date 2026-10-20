#!/usr/bin/env python3
"""Install approved boot ordering, with explicit quiesced RM recovery.

No reboot, driver reset, second RM, inference, or automatic marker removal at boot.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = Path(__file__).resolve().parent
OVERLAY = Path('/opt/ai-platform/gateway-overlays/vision-radio-5d9d267489609ccb')
MARKER = Path('/var/lib/ai-platform-gpu/residency.blocked')
STATE = Path('/var/lib/ai-platform/comfyui-boot')
USER_DROPIN = Path('/home/harrypotter/.config/systemd/user/hermes-gateway.service.d/50-platform-ready.conf')
CONFIGS = {
    'comfyui.conf': Path('/etc/systemd/system/comfyui.service.d/20-ai-platform-ready.conf'),
    'gateway.conf': Path('/etc/systemd/system/ai-gateway.service.d/98-comfyui-ready.conf'),
    'hermes.conf': USER_DROPIN,
}
FAULT = re.compile(r'\b(?:amdgpu|kfd|MES|ring)\b.*\b(?:fault|failed|full|reset|timeout|hang)\b', re.I)
RECOVERY_JOB = 'job_45783f09b4d141bc93bf9833f4a19896'
RECOVERY_BOOT = '074cd2c7-3a21-4347-b99b-fbe012d0a4e5'


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def command(*args, timeout=40):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    require(result.returncode == 0, args[0] + ': ' + result.stderr.strip()[:300])
    return result.stdout.strip()


def userctl(*args):
    return command('runuser', '-u', 'harrypotter', '--', 'env',
                   'XDG_RUNTIME_DIR=/run/user/1000',
                   'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus',
                   'systemctl', '--user', *args, timeout=90)


def fetch(port, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request('http://127.0.0.1:' + str(port) + path, data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=90) as reply:
        return json.load(reply)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    path.chmod(0o600)


def hermes_stopped():
    values = dict(line.split('=', 1) for line in userctl(
        'show', 'hermes-gateway.service', '-p',
        'ActiveState,MainPID,ControlPID,ControlGroup').splitlines())
    # A service can be stopped while retaining a failed exit result.
    require(values.get('ActiveState') in ('inactive', 'failed')
            and values.get('MainPID') == values.get('ControlPID') == '0'
            and values.get('ControlGroup') == '', 'Hermes process or cgroup remains')


def record_before(status):
    if STATE.exists():
        expected = {'before.json', 'gateway-before.txt', 'comfyui-before.txt',
                    'hermes-before.txt', 'residency.blocked.before'}
        require(not STATE.is_symlink() and STATE.stat().st_uid == 0
                and not STATE.stat().st_mode & 0o077, 'untrusted installation evidence')
        require({p.name for p in STATE.iterdir()} == expected,
                'previous installation progressed past the pre-install checkpoint')
        before = json.loads((STATE / 'before.json').read_text())
        for key in ('admission_blocked', 'active_count', 'queued_count',
                    'resource_leases', 'gpu_residency'):
            require(before[key] == status[key], 'RM differs from saved pre-install evidence')
        require(MARKER.read_bytes() == (STATE / 'residency.blocked.before').read_bytes(),
                'GPU marker differs from saved evidence')
        for name, content in (
            ('gateway-before.txt', command('systemctl', 'cat', 'ai-gateway.service')),
            ('comfyui-before.txt', command('systemctl', 'cat', 'comfyui.service')),
            ('hermes-before.txt', userctl('cat', 'hermes-gateway.service')),
        ):
            require((STATE / name).read_text() == content, 'service configuration changed since first attempt')
        print('PRE_INSTALL_RESUME=PASS; original evidence preserved', flush=True)
        return
    STATE.mkdir(parents=True, mode=0o700)
    save(STATE / 'before.json', status)
    (STATE / 'gateway-before.txt').write_text(command('systemctl', 'cat', 'ai-gateway.service'))
    (STATE / 'comfyui-before.txt').write_text(command('systemctl', 'cat', 'comfyui.service'))
    (STATE / 'hermes-before.txt').write_text(userctl('cat', 'hermes-gateway.service'))
    shutil.copy2(MARKER, STATE / 'residency.blocked.before')


def verify_sources(expected):
    raw = (HERE / 'SHA256.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, 'package manifest changed')
    files = {}
    inventory = json.loads(raw)
    require(set(inventory) == {'install.py', 'wait_ready.py', 'comfyui.conf',
                              'gateway.conf', 'hermes.conf', 'gateway-source.json'}, 'unexpected package files')
    for name, sha in inventory.items():
        require(not (HERE / name).is_symlink(), 'package symlink')
        files[name] = (HERE / name).read_bytes()
        require(hashlib.sha256(files[name]).hexdigest() == sha, 'changed package file: ' + name)
    for name, sha in json.loads(files['gateway-source.json']).items():
        path = OVERLAY / name
        require(path.resolve().is_relative_to(OVERLAY) and not path.is_symlink(), 'invalid Gateway source path')
        require(path.stat().st_uid == 0 and not path.stat().st_mode & 0o022,
                'Gateway source is not protected')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == sha, 'Gateway source changed: ' + name)
    return files


def admissible(status):
    require(status['queued_count'] == 0, 'queued work exists')
    if not status['admission_blocked']:
        require(status['active_count'] == status['resource_leases']['lease_count'] == 0
                and not status['gpu_residency']['recovery_required']
                and not MARKER.exists(), 'platform busy or dirty')
        return False
    leases = status['resource_leases']['leases']
    require(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == RECOVERY_BOOT,
            'recorded recovery belongs to another boot')
    require(status['active_count'] == status['resource_leases']['lease_count'] == len(leases) == 1
            and MARKER.is_file(), 'unknown blocked state')
    lease = leases[0]
    require(lease['job']['job_id'] == RECOVERY_JOB and lease['source'] == 'telegram-foto'
            and lease['in_use'] == 0 and lease['release_when_idle'] is True
            and lease['external_in_use'] is True
            and lease['external_workload'] == {'provider': 'comfyui-local', 'node': 'ai-node-01',
                                               'capability': 'image-generation'}, 'another job owns the GPU')
    return True


def kernel_clear():
    text = command('journalctl', '-b', '-k', '--no-pager', '-o', 'cat')
    require(not any(FAULT.search(line) for line in text.splitlines()), 'GPU kernel fault; recovery refused')


def no_workers():
    require(not command('systemctl', 'list-units', '--all', '--no-legend', '--plain', 'ai-radio-*'),
            'RADIO worker unit exists')
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            args = (proc / 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        require(not any(any(term in arg for term in (b'hermes_foto', b'hermes_video',
                    b'generate_image.py', b'generate_video.py', b'generate_ltx23')) for arg in args),
                'media producer process remains')


def no_gpu_owners():
    deadline = time.monotonic() + 30
    devices = ['/dev/kfd'] + [str(p.resolve()) for p in Path('/dev/dri/by-path').glob('pci-0000:c6:00.0-*')]
    require(len(devices) >= 3, 'expected GPU device nodes missing')
    while True:
        holders = subprocess.run(['fuser', *devices], capture_output=True, text=True, timeout=10)
        require(holders.returncode in (0, 1), 'GPU ownership observation failed')
        kfd = list(Path('/sys/class/kfd/kfd/proc').iterdir())
        require(holders.returncode != 1 or not holders.stderr.strip(), 'GPU ownership observation error')
        if holders.returncode == 1 and not holders.stdout.strip() and not kfd:
            return
        require(time.monotonic() < deadline, 'GPU owner remains after unload')
        time.sleep(.5)


def apply(files, sha):
    require(os.geteuid() == 0, 'run in operator terminal with sudo')
    status = fetch(11435, '/status')
    recovering = admissible(status)
    require(recovering, 'this one-time installation expects the recorded blocked Telegram request')
    require(command('systemctl', 'show', 'comfyui.service', '-p', 'ActiveState', '--value') == 'inactive',
            'ComfyUI already active; inspect current work first')
    for unit in ('ollama-preload.service', 'ai-bridge-analysis.timer', 'ai-bridge-analysis.service'):
        require(command('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'inactive',
                'another producer active: ' + unit)
    require(json.loads(Path('/srv/ai-data/hermes/gateway_state.json').read_text()).get('active_agents') == 0,
            'Hermes is processing work')
    require(all(not path.exists() for path in CONFIGS.values()), 'boot drop-in already exists')
    kernel_clear()
    record_before(status)
    userctl('stop', 'hermes-gateway.service')
    hermes_stopped()
    status = fetch(11435, '/status')
    require(admissible(status) == recovering, 'RM state changed during quiesce')
    no_workers()
    command('systemctl', 'stop', 'ai-gateway.service')
    for model in fetch(11434, '/api/ps')['models']:
        fetch(11434, '/api/generate', {'model': model['name'], 'keep_alive': 0, 'stream': False})
    require(fetch(11434, '/api/ps')['models'] == [], 'Ollama model remains')
    no_gpu_owners()
    package = Path('/opt/ai-platform/comfyui-boot') / sha[:16]
    package.mkdir(parents=True, mode=0o755)
    for name, content in files.items():
        (package / name).write_bytes(content)
        (package / name).chmod(0o644)
    for name, path in CONFIGS.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files[name].decode().replace('@PACKAGE@', str(package)))
        path.chmod(0o644)
        if path == USER_DROPIN:
            os.chown(path, 1000, 1000)
    command('systemctl', 'daemon-reload')
    userctl('daemon-reload')
    command('systemd-analyze', 'verify', 'comfyui.service', 'ai-gateway.service')
    command('systemctl', 'enable', 'comfyui.service')
    command('systemctl', 'start', 'comfyui.service', timeout=160)
    # Use the already deployed controller, with the existing 64 MiB idle limit.
    script = '''import sys,asyncio
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import httpx
from ai_bridge.gateway.residency import GPUResidency
async def recover():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:11434",trust_env=False,timeout=90) as ollama, httpx.AsyncClient(base_url="http://127.0.0.1:8188",trust_env=False,timeout=10) as comfy:
        gpu=GPUResidency(ollama,comfy,Path(sys.argv[2]),idle_reserve_bytes=67108864)
        await gpu.enter_media()
        await gpu.leave_media()
asyncio.run(recover())
'''
    command('/opt/ai-platform/current/services/ai-gateway/.venv/bin/python', '-I', '-c', script,
            str(OVERLAY / 'src'), str(STATE / 'cleanup-check.blocked'), timeout=210)
    kernel_clear()
    no_workers()
    if recovering:
        require(MARKER.read_bytes() == (STATE / 'residency.blocked.before').read_bytes(), 'marker changed')
        MARKER.unlink()
    command('systemctl', 'start', 'ai-gateway.service')
    command('/usr/bin/python3', '-I', str(package / 'wait_ready.py'), 'gateway', timeout=190)
    final = fetch(11435, '/status')
    require(not admissible(final), 'RM did not recover')
    require(command('systemctl', 'is-enabled', 'comfyui.service') == 'enabled', 'autostart not enabled')
    for unit in ('ollama-preload.service', 'ai-bridge-analysis.timer'):
        require(command('systemctl', 'show', unit, '-p', 'UnitFileState', '--value') == 'disabled',
                'producer autostart changed')
    userctl('start', 'hermes-gateway.service')
    save(STATE / 'RESULT.json', {'result': 'COMFYUI_BOOT_CONFIG_PASS', 'observed_at': datetime.now(timezone.utc).isoformat(),
         'recovery_performed': recovering, 'package': str(package),
         'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
         'post_reboot_acceptance': 'PENDING', 'gpu_cycle': 'PENDING'})
    print(json.dumps({'result': 'COMFYUI_BOOT_CONFIG_PASS', 'recovery_performed': recovering,
                     'post_reboot_acceptance': 'PENDING', 'gpu_cycle': 'PENDING'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        files = verify_sources(args.manifest_sha256)
        if args.apply:
            apply(files, args.manifest_sha256)
        else:
            print('PACKAGE_AND_GATEWAY_SOURCE_CHECK=PASS; no changes made')
    except Exception as error:
        # Ingress stays closed after a failed recovery. Never force it green.
        print(json.dumps({'result': 'BLOCKED', 'error': type(error).__name__ + ': ' + str(error)[:400]}), flush=True)
        raise SystemExit(1)
