"""One specific recovery: failed root-Gateway prepare, before any RADIO worker.

Not a generic GPU reset/marker remover. Unknown ownership, any worker/session,
changed release or driver fault refuses recovery and preserves the block.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import urllib.request

OLD_SHA = '389beaa97b11783361ff8ec49e60dfbe15e3ca7da70d327626c4ee47eca46acf'
OLD = Path('/opt/ai-platform/vision-radio/releases') / OLD_SHA[:16]
STATE = Path('/var/lib/ai-platform-radio')
MARKER = Path('/var/lib/ai-platform-gpu/residency.blocked')
UNIT = Path('/etc/systemd/system/ai-platform-radio.service')
MARKER_BYTES = (b'GPU ownership uncertain; verify workers stopped and both providers free before recovery.\n'
                b'Vision RADIO pilot unresolved; operator review required.\n')
FAULT = re.compile(r'amdgpu.*(fault|reset|timeout|hang)|MES.*(fault|timeout|failed)', re.I)


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def command(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=15)
    require(p.returncode == 0, 'recovery system command failed: ' + args[0])
    return p.stdout.strip()


def get(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as response:
        return json.load(response)


def no_radio_execution():
    require(not (STATE / 'ownership.dirty').exists() and not (STATE / 'ownership.tmp').exists(),
            'RADIO ownership evidence exists; automatic prelaunch recovery forbidden')
    require(not (STATE / 'LAST_ERROR.json').exists(), 'supervisor received a failing operation; needs review')
    sessions = STATE / 'sessions'
    require(sessions.is_dir() and not sessions.is_symlink() and not any(sessions.iterdir()),
            'a RADIO session exists; cannot prove no worker started')
    units = command('systemctl', 'list-units', '--all', '--no-legend', '--plain', 'ai-radio-*')
    require(not units, 'RADIO unit exists; cannot perform prelaunch recovery')


def previous_installation():
    require(not OLD.is_symlink() and OLD.stat().st_uid == 0, 'old package identity invalid')
    manifest = OLD / 'SOURCE_SHA256.json'
    require(hashlib.sha256(manifest.read_bytes()).hexdigest() == OLD_SHA, 'old package manifest changed')
    for name, expected in json.loads(manifest.read_text()).items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'invalid old manifest path')
        path = OLD / relative
        info = path.stat()
        require(not path.is_symlink() and info.st_uid == 0 and not info.st_mode & 0o022
                and hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'old source changed')
    content = (OLD / 'deploy/vision-radio/ai-platform-radio.service').read_text().replace('@PACKAGE@', str(OLD))
    require(not UNIT.is_symlink() and UNIT.stat().st_uid == 0 and UNIT.read_text() == content,
            'executor service differs from failed installation')
    state = subprocess.run(['systemctl', 'is-active', 'ai-platform-radio.service'],
                           capture_output=True, text=True, timeout=5)
    require(state.returncode == 3 and state.stdout.strip() == 'inactive', 'executor is not stopped')
    return content


def host_evidence(report):
    require(MARKER.is_file() and not MARKER.is_symlink() and MARKER.read_bytes() == MARKER_BYTES,
            'GPU block marker is not the exact prelaunch failure')
    for path in (Path('/var/lib/ai-platform-gpu/managed-worker.dirty'),
                 Path('/home/harrypotter/.local/state/ai-platform/gpu-residency.blocked')):
        require(not path.exists(), 'independent GPU block exists')
    status = get('http://127.0.0.1:11435/status')
    require(status.get('active_count') == 0 and status.get('queued_count') == 0
            and status.get('resource_leases', {}).get('lease_count') == 0
            and status.get('admission_blocked') is True
            and status.get('resource_manager', {}).get('state') == 'BLOCKED', 'Gateway not safely blocked/empty')
    require(get('http://127.0.0.1:11434/api/ps').get('models') == [], 'Ollama models remain')
    comfy = get('http://127.0.0.1:8188/ai-platform/residency')
    require(comfy.get('schema_version') == 1 and comfy.get('cleanup_pending') is False
            and all(comfy.get(key) == 0 for key in ('loaded_models', 'queue_running', 'queue_pending')),
            'ComfyUI not clean')
    pid = int(command('systemctl', 'show', 'comfyui.service', '-p', 'MainPID', '--value'))
    proc = Path(f'/proc/{pid}')
    require(pid > 1 and proc.stat().st_uid == 1000, 'ComfyUI identity changed')
    birth = int((proc / 'stat').read_text().rsplit(')', 1)[1].split()[19])
    expected = frozenset({(pid, birth)})
    observer = Path('/usr/local/libexec/ai-platform/vision-gpu-observer.py')
    info = observer.stat()
    require(info.st_uid == 0 and not info.st_mode & 0o022, 'observer not trusted')
    spec = importlib.util.spec_from_file_location('_recovery_observer', observer)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for _ in range(3):
        clients = module.snapshot_gpu_clients()
        require(clients is not None and frozenset(clients) <= expected, 'unknown/foreign GPU owner')
        kfd = {int(p.name) for p in Path('/sys/class/kfd/kfd/proc').iterdir() if p.name.isdecimal()}
        require(kfd <= {pid}, 'unexpected KFD client')
        time.sleep(.1)
    since = datetime.fromisoformat(report['observed_at']).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    records = command('journalctl', '-k', '--since', since, '--no-pager', '-o', 'json')
    require(not any(FAULT.search(json.loads(line).get('MESSAGE', '')) for line in records.splitlines()),
            'driver fault since failed pilot; prelaunch recovery refused')
    return {'comfy_pid': pid, 'comfy_birth': birth, 'gateway_empty_and_blocked': True,
            'ollama_models_empty': True, 'comfy_clean': True, 'radio_never_started': True,
            'driver_errors_observed': False}


def preflight():
    require(os.geteuid() == 0, 'operator authorization required')
    previous_content = previous_installation()
    no_radio_execution()
    report = json.loads((STATE / 'PILOT_RESULT.json').read_text())
    require(report.get('result') == 'BLOCKED' and report.get('prior_gateway_restored') is True
            and report.get('error') == 'RuntimeError: Vision prepare failed closed'
            and report.get('production_install') == 'NOT_PERFORMED'
            and not report.get('radio_inspections'), 'failure does not match known prelaunch case')
    evidence = host_evidence(report)
    return {'previous_unit': previous_content, 'report': report, 'evidence': evidence,
            'marker_sha256': hashlib.sha256(MARKER_BYTES).hexdigest(), 'old_manifest_sha256': OLD_SHA}


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def archive_and_restore(proof):
    # Recheck after installing the fixed executor. It must still have no job.
    no_radio_execution()
    current = host_evidence(proof['report'])
    archive = STATE / 'prelaunch-recovery' / secrets.token_hex(12)
    archive.mkdir(parents=True, mode=0o700)
    (archive / 'PILOT_RESULT.json').write_text(json.dumps(proof['report'], sort_keys=True, indent=2) + '\n')
    with (archive / 'RECOVERY.json').open('x') as stream:
        json.dump({'reason': 'ROOT_GATEWAY_UID_MISMATCH_BEFORE_RADIO_START',
                   'old_manifest_sha256': OLD_SHA, 'evidence': current}, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    command('systemctl', 'stop', 'ai-gateway.service')
    try:
        require(MARKER.read_bytes() == MARKER_BYTES, 'marker changed before archive')
        os.rename(MARKER, archive / 'residency.blocked')
        sync_dir(archive)
        sync_dir(MARKER.parent)
    finally:
        command('systemctl', 'start', 'ai-gateway.service')
    deadline = time.monotonic() + 35
    while True:
        try:
            status = get('http://127.0.0.1:11435/status')
            require(status.get('resource_manager', {}).get('state') == 'IDLE'
                    and status.get('admission_blocked') is False, 'Gateway did not recover to idle')
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(.2)
    return {'prelaunch_recovery': 'PASS', 'old_block_marker': 'ARCHIVED', 'driver_reset': 'NOT_PERFORMED'}
