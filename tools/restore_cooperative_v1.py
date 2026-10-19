#!/usr/bin/env python3
"""Operator-only restoration; no inference, deployment, or automatic rollback."""
import argparse
import hashlib
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

RELEASE = '/opt/ai-platform/releases/stage-o-28e3ea214660'
START = ('ollama.service', 'ai-gateway.service', 'ai-bridge.service')
OFF = ('comfyui.service', 'ai-bridge-analysis.timer', 'ai-bridge-analysis.service',
       'ollama-preload.service', 'gdm.service')
MANIFEST = Path(__file__).with_suffix('.baseline.json')
ROLLBACK = ('Operator: inspect journal and this report; keep ingress paused. '
            'If rollback is needed: sudo systemctl stop ai-bridge.service; '
            'sudo systemctl stop ai-gateway.service; sudo systemctl stop ollama.service. '
            'Stopping Ollama can stop Gateway. Do not clear markers or start ComfyUI/preload.')


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def run(*args, allowed=(0,)):
    p = subprocess.run(args, text=True, capture_output=True, timeout=25)
    require(p.returncode in allowed, 'command failed: ' + ' '.join(args))
    return p.stdout.strip()


def prop(unit, key):
    return run('systemctl', 'show', unit, '--value', '-p', key)


def files():
    paths = []
    for unit in START + OFF:
        p = Path('/etc/systemd/system') / unit
        if p.is_file():
            paths.append(p)
        paths.extend(sorted(p.parent.glob(unit + '.d/*.conf')))
    paths.extend(Path(p) for p in ('/etc/ai-gateway/ai-gateway.env',
                                  '/etc/ai-bridge/ai-bridge.env'))
    paths.extend(Path(RELEASE).glob('services/ai-gateway/src/ai_bridge/**/*.py'))
    for service in ('ai-gateway', 'ai-bridge'):
        p = Path(RELEASE) / 'services' / service / '.env'
        if p.exists():
            paths.append(p)
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def baseline(started=()):
    require(Path('/opt/ai-platform/current').resolve() == Path(RELEASE), 'release mismatch')
    require(files() == json.loads(MANIFEST.read_text()), 'production configuration/source drift')
    require(run('systemctl', 'get-default') == 'multi-user.target', 'not headless baseline')
    for unit in START + OFF:
        require(prop(unit, 'LoadState') == 'loaded', 'missing unit: ' + unit)
        require(prop(unit, 'NeedDaemonReload') == 'no', 'pending daemon reload: ' + unit)
        require(prop(unit, 'ActiveState') == ('active' if unit in started else 'inactive'),
                'unexpected service state: ' + unit)
    for unit in ('ssh.service', 'tailscaled.service'):
        require(prop(unit, 'ActiveState') == 'active', unit + ' not active')
    with socket.create_connection(('127.0.0.1', 22), timeout=2):
        pass
    require(json.loads(run('tailscale', 'status', '--json'))['BackendState'] == 'Running',
            'Tailscale unavailable')
    require(not run('systemctl', 'list-units', 'ai-rm-*', '--state=active,activating,deactivating,failed',
                    '--no-legend', '--plain'), 'RM pilot active or unresolved')
    require(not run('systemctl', 'list-jobs', '--no-legend'), 'pending systemd jobs')
    for marker in ('/var/lib/ai-platform-gpu/residency.blocked',
                   '/home/harrypotter/.local/state/ai-platform/gpu-residency.blocked'):
        p = Path(marker)
        # Listing parent must succeed: inaccessible is not absent.
        require(p.name not in os.listdir(p.parent), 'residency DIRTY marker: ' + marker)
    for unit in START:
        deps = run('systemctl', 'list-dependencies', '--plain', '--no-legend', unit).split()
        require(not set(deps).intersection(OFF), 'unsafe start dependency: ' + unit)
    # This pinned production release predates N2 selection and uses PriorityScheduler + GPUResidency.
    env = prop('ai-gateway.service', 'Environment') + Path('/etc/ai-gateway/ai-gateway.env').read_text()
    require('GATEWAY_ADMISSION_STRATEGY' not in env, 'unexpected strategy override')


def idle(privileged):
    require(Path('/sys/bus/pci/devices/0000:c6:00.0/vendor').read_text().strip() == '0x1002'
            and Path('/sys/bus/pci/devices/0000:c6:00.0/device').read_text().strip() == '0x150e',
            'GPU identity mismatch')
    require(not os.listdir('/sys/class/kfd/kfd/proc'), 'KFD owners present')
    if not privileged:
        return 'READ_ONLY_KFD_CHECK_FULL_FUSER_NOT_VERIFIED'
    p = subprocess.run(('sudo', '-n', '/usr/bin/fuser', '/dev/kfd', '/dev/dri/renderD128'),
                       capture_output=True, text=True, timeout=10)
    require(p.returncode == 1 and not p.stdout.strip() and not p.stderr.strip(),
            'GPU owners present or fuser inspection ambiguous')


def ready(port, path, gateway=False):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(20):
        try:
            with opener.open(f'http://127.0.0.1:{port}{path}', timeout=2) as r:
                data = json.load(r)
            if (data.get('status') == 'ok' and data.get('ollama') == 'ok') if gateway else bool(data.get('version')):
                return
        except (OSError, ValueError):
            pass
        time.sleep(.5)
    raise RuntimeError('readiness timeout: ' + path)


def restore(apply=False):
    require(os.geteuid() != 0, 'run as ordinary operator, never sudo this script')
    baseline()
    if apply:
        require(sys.stdin.isatty() and sys.stdout.isatty(), '--apply requires interactive operator terminal')
        run('sudo', '-k')
        run('sudo', '-v')
    for _ in range(3):
        idle(apply)
        time.sleep(.25)
    if not apply:
        return
    baseline()
    idle(True)
    started = []
    for unit in START:
        baseline(started)
        run('sudo', '-n', 'systemctl', 'start', unit)
        started.append(unit)
        if unit == 'ollama.service':
            ready(11434, '/api/version')
        if unit == 'ai-gateway.service':
            ready(11435, '/health', True)
    baseline(started)
    ready(11435, '/health', True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    # A unique local report remains BLOCKED even on interruption or abrupt termination.
    import tempfile
    fd, name = tempfile.mkstemp(prefix='cooperative-restore-', suffix='.json', dir=Path.cwd())
    report = {'status': 'BLOCKED', 'apply': args.apply, 'rollback': ROLLBACK}
    def save():
        Path(name).write_text(json.dumps(report, indent=2) + '\n')
    os.close(fd)
    save()
    print('REPORT=' + name, flush=True)
    try:
        # One restoration at a time, regardless of invocation directory.
        lock_path = Path(__file__).resolve().with_suffix('.lock')
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            restore(args.apply)
        report['status'] = 'RESTORED_BASE_AI_ONLY' if args.apply else 'READ_ONLY_PREFLIGHT_PASS'
        report['gpu_owner_visibility'] = 'ROOT_FUSER_CHECKED' if args.apply else 'PARTIAL_OPERATOR_APPLY_REQUIRED'
        report['comfyui'] = 'INACTIVE_NOT_RESTORED'
    except (Exception, KeyboardInterrupt) as exc:
        report['reason'] = str(exc) or 'interrupted'
    save()
    print(json.dumps(report, indent=2))
    return 0 if report['status'] != 'BLOCKED' else 2


if __name__ == '__main__':
    sys.exit(main())
