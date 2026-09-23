"""Bounded admitted video after cold recovery, before production acceptance."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from uuid import uuid4


CHILD = '''
import os, subprocess, sys
sys.path.insert(0, '/usr/local/libexec/ai-server')
import hermes_resource_queue as helper
lease = helper.acquire_resource(target=None, source='stage-g-isolated-video', workload='media-video')
os.environ['HERMES_RESOURCE_LEASE_ID'] = lease.lease_id
try:
    subprocess.run(['/usr/local/bin/generate-video-ltx23', '--duration-seconds', '1',
        '--width', '640', '--height', '384', '--seed', '20260923', '--timeout', '600',
        '--prompt', 'A small metal gear on a clean workbench, static camera.',
        '--output-dir', sys.argv[1]], check=True, timeout=650)
finally:
    lease.release()
'''


def validate(g):
    e, f, run, require = g.e, g.f, g.run, g.require
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    accepted = g.STATE / ('isolated-video-' + boot + '.json')
    identities = {u: e.identity(u) for u in ('ollama.service', 'comfyui.service')}
    if accepted.exists():
        previous = e.read(accepted)
        require(previous['providers'] == {k: list(v) for k, v in identities.items()})
        return
    f.require_kernel_clear()
    e.require_hermes_stopped()
    f.require_no_media_workers()
    e.idle()
    state = g.STATE / ('isolated-video-evidence-' + uuid4().hex)
    state.mkdir(mode=0o700)
    name, uid, home = e.hermes_account()
    # Only the artifact directory is writable by the worker; gate evidence stays root-owned.
    output = Path(tempfile.mkdtemp(prefix='stage-g-isolated-video-'))
    os.chown(output, uid, Path(home).stat().st_gid)
    watch = e.load_module('stage_g_isolated_watch', g.ROOT / 'deploy/stage-f/gpu_watch.py')
    def contain():
        (g.STATE / 'gpu-blocked.json').write_text(json.dumps({'boot_id': boot,
            'status': 'BLOCKED_GPU', 'release': str(e.CURRENT.resolve()), 'time': time.time()}))
        run(['systemctl', 'stop', 'ai-gateway.service', 'ai-bridge-analysis.timer'], timeout=180)
        e.user_systemctl(['stop', 'hermes-gateway.service'])
    process = None
    try:
        with watch.KernelGuard(run, contain, state / 'kernel.log') as guard:
            inventory = e.fetch('http://127.0.0.1:11434/api/ps')['models']
            for model in inventory:
                e.fetch('http://127.0.0.1:11434/api/generate', {'model': model['name'], 'keep_alive': 0, 'stream': False})
            empty = e.fetch('http://127.0.0.1:11434/api/ps')
            require(empty['models'] == [])
            e.write_once(state / 'ollama-empty-before.json', empty)
            with (state / 'render.log').open('x') as log:
                process = subprocess.Popen([str(x) for x in ['runuser', '-u', name, '--',
                    'env', f'HOME={home}', e.CURRENT / 'services/ai-bridge/.venv/bin/python',
                    '-c', CHILD, output]], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                deadline = time.monotonic() + 700
                while process.poll() is None:
                    guard.check()
                    require(time.monotonic() < deadline)
                    time.sleep(.5)
                require(process.returncode == 0)
            e.idle()
            residency = e.fetch('http://127.0.0.1:8188/ai-platform/residency')
            require(residency == {'schema_version': 1, 'queue_running': 0, 'queue_pending': 0,
                                 'loaded_models': 0, 'cleanup_pending': False})
            stats = e.fetch('http://127.0.0.1:8188/system_stats')
            require(all(0 <= d['torch_vram_total'] <= 67108864 for d in stats['devices']))
            require(e.fetch('http://127.0.0.1:11434/api/ps')['models'] == [])
            status = e.fetch(e.GATEWAY + '/status')
            require(status['gpu_residency']['state'] == 'llm' and not status['admission_blocked'])
            e.write_once(state / 'clean-after.json', {'residency': residency, 'devices': stats['devices'], 'gateway': status})
            artifacts = list(output.glob('*.mp4'))
            require(len(artifacts) == 1)
            probe = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', artifacts[0]]))
            require(any(s['codec_type'] == 'video' and s['width'] == 640 and s['height'] == 384 for s in probe['streams']))
            require(0.9 <= float(probe['format']['duration']) <= 1.2)
            e.write_once(state / 'ffprobe.json', probe)
            require(identities == {u: e.identity(u) for u in identities})
        e.write_once(accepted, {'status': 'PASS', 'boot_id': boot, 'providers': identities,
                               'evidence': str(state), 'artifacts': str(output),
                               'release': str(e.CURRENT.resolve())})
        print('ISOLATED_VIDEO=PASS evidence=' + str(state), flush=True)
    except BaseException:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=30)
        raise
