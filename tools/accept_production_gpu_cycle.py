#!/usr/bin/env python3
"""One production RM cycle; no second RM, service changes or marker recovery."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'docs/reports/GPU_PRODUCTION_CYCLE_2026-10-20.json'
GATEWAY = 'http://127.0.0.1:11435'
OLLAMA = 'http://127.0.0.1:11434'
COMFY = 'http://127.0.0.1:8188'
MODEL = 'qwen3.8:27b-p4-64k-gpu-p511'
OVERLAY = Path('/opt/ai-platform/gateway-overlays/vision-radio-5d9d267489609ccb')
UNITS = ('ai-gateway.service', 'ai-platform-radio.service', 'ollama.service', 'comfyui.service')
FAULT = re.compile(r'amdgpu.*(fault|reset|timeout|hang)|MES.*(fault|timeout|failed)|ring.*timeout', re.I)


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def now():
    return datetime.now(timezone.utc).isoformat()


def command(*args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=20)
    require(result.returncode == 0, 'command failed: ' + args[0])
    return result.stdout.strip()


def request(base, path, body=None, method=None, lease=None, timeout=15):
    data = None if body is None else json.dumps(body).encode()
    headers = {'Content-Type': 'application/json'}
    if lease:
        headers['x-ai-resource-lease'] = lease
    req = urllib.request.Request(base + path, data=data, headers=headers,
                                 method=method or ('POST' if data is not None else 'GET'))
    # HTTP errors intentionally omit token-bearing request URLs from reports.
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as reply:
            return json.load(reply)
    except urllib.error.HTTPError as error:
        raise RuntimeError('HTTP ' + str(error.code) + ' during ' + req.method) from None


def services():
    return {unit: command('systemctl', 'show', unit, '-p', 'MainPID', '--value') for unit in UNITS}


def snapshot():
    status = request(GATEWAY, '/status')
    return {'observed_at': now(), 'active_count': status['active_count'],
            'queued_count': status['queued_count'], 'admission_blocked': status['admission_blocked'],
            'resource_manager': status['resource_manager'], 'gpu_residency': status['gpu_residency'],
            'lease_count': status['resource_leases']['lease_count'],
            'ollama': request(OLLAMA, '/api/ps'),
            'comfyui': request(COMFY, '/ai-platform/residency'),
            'comfyui_devices': request(COMFY, '/system_stats')['devices'],
            'kfd_pids': sorted(p.name for p in Path('/sys/class/kfd/kfd/proc').iterdir() if p.name.isdecimal())}


def idle():
    value = snapshot()
    require(value['active_count'] == value['queued_count'] == value['lease_count'] == 0
            and not value['admission_blocked']
            and value['resource_manager']['state'] == 'IDLE'
            and value['gpu_residency']['state'] == 'llm'
            and value['gpu_residency']['recovery_required'] is False, 'RM busy or blocked')
    return value


def models_free(value):
    comfy = value['comfyui']
    require(value['ollama']['models'] == [] and comfy['schema_version'] == 1
            and all(comfy[k] == 0 for k in ('queue_running', 'queue_pending', 'loaded_models'))
            and comfy['cleanup_pending'] is False, 'runtime models or work remain')


def workflow():
    # Use the installed project workflow without importing its executing CLI.
    tree = ast.parse((ROOT / 'tools/local_image/generate_image.py').read_text())
    value = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'workflow' for t in n.targets))
    values = {'prompt': 'A simple green printed circuit board on a white background, studio photograph.',
              'width': 512, 'height': 512, 'seed': 20261020}
    class Constants(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.copy_location(ast.Constant(values[node.id]), node)
    graph = ast.literal_eval(Constants().visit(value))
    graph['13']['inputs']['filename_prefix'] = 'RM-GPU-cycle-20261020'
    return graph


class Cycle:
    def __init__(self):
        self.lease = None
        self.use = None
        self.stop = threading.Event()
        self.heartbeat_error = False
        self.thread = threading.Thread(target=self.heartbeat, daemon=True)

    def heartbeat(self):
        while not self.stop.wait(5):
            current = self.lease
            if current:
                try:
                    request(GATEWAY, '/resource/leases/' + current + '/heartbeat', {}, timeout=10)
                except Exception:
                    # A lease released during the HTTP call can legitimately disappear.
                    if self.lease == current:
                        self.heartbeat_error = True

    def acquire(self, workload):
        require(self.lease is None, 'previous lease still owned')
        idle()
        data = request(GATEWAY, '/resource/leases', {'workload': workload,
                       'source': 'operator-production-gpu-cycle', 'priority': -1000})
        self.lease = data['lease_id']
        require(data['state'] == 'active', 'another task won admission')
        value = snapshot()
        require(value['active_count'] == value['lease_count'] == 1
                and value['queued_count'] == 0 and not value['admission_blocked'], 'test not exclusive')

    def begin(self, provider, capability):
        require(self.use is None, 'previous external use still owned')
        self.use = request(GATEWAY, '/resource/leases/' + self.lease + '/uses',
                           {'provider': provider, 'capability': capability}, timeout=120)['use_id']
        require(request(GATEWAY, self.use_path()) == {'provider': provider, 'capability': capability},
                'external ownership mismatch')

    def use_path(self):
        return '/resource/leases/' + self.lease + '/uses/' + self.use

    def end(self):
        require(request(GATEWAY, self.use_path(), method='DELETE', timeout=120)['released'] is True,
                'external cleanup unconfirmed')
        self.use = None

    def release(self):
        require(self.use is None, 'external use still active')
        current, self.lease = self.lease, None
        require(request(GATEWAY, '/resource/leases/' + current, method='DELETE')['released'] is True,
                'lease release failed')

    def llm(self, label, report):
        print(label + ': START', flush=True)
        started = time.monotonic()
        body = {'model': MODEL, 'prompt': 'Reply with exactly: GPU_HANDOFF_OK', 'stream': False,
                'think': False, 'keep_alive': '5m',
                'options': {'num_ctx': 2048, 'num_predict': 32, 'temperature': 0, 'seed': 20261020}}
        response = request(GATEWAY, '/api/generate', body, lease=self.lease, timeout=600)
        require(response.get('done') is True and response.get('response', '').strip()
                and response.get('eval_count', 0) > 0, 'no generated LLM answer')
        state = snapshot()
        resident = state['ollama']['models']
        require(len(resident) == 1 and resident[0]['name'] == MODEL
                and resident[0].get('size_vram', 0) > 0, 'Ollama GPU residency not observed')
        report['steps'].append({'engine': label, 'seconds': time.monotonic() - started,
            'response': response['response'][:512], 'eval_count': response['eval_count'],
            'done_reason': response.get('done_reason'), 'model': MODEL, 'observation': state})
        print(label + ': PASS', flush=True)


def preflight():
    require(os.geteuid() == 1000, 'run as production Gateway user UID 1000')
    initial = idle()
    models_free(initial)
    require(next(e for e in initial['resource_manager']['engines'] if e['id'] == 'vision')
            ['execution_available'] is True, 'Vision unavailable')
    for marker in ('/var/lib/ai-platform-gpu/residency.blocked',
                   '/var/lib/ai-platform-gpu/managed-worker.dirty',
                   '/home/harrypotter/.local/state/ai-platform/gpu-residency.blocked'):
        require(not Path(marker).exists(), 'GPU block marker exists')
    pids = services()
    for unit in UNITS:
        require(command('systemctl', 'is-active', unit) == 'active' and int(pids[unit]) > 1,
                'service inactive')
    environment = Path('/proc/' + pids['ai-gateway.service'] + '/environ').read_bytes().split(b'\0')
    require(('PYTHONPATH=' + str(OVERLAY / 'src')).encode() in environment,
            'unexpected production overlay')
    manifest = json.loads((ROOT / 'deploy/vision-radio/GATEWAY_PRODUCTION_SOURCE_SHA256.json').read_text())
    require(len(manifest) == 239 and all(hashlib.sha256((OVERLAY / name).read_bytes()).hexdigest() == sha
            for name, sha in manifest.items()), 'production manifest mismatch')
    graph = workflow()
    info = request(COMFY, '/object_info', timeout=60)
    require(all(n['class_type'] in info for n in graph.values()), 'workflow nodes unavailable')
    for node, field, expected in (('UNETLoader', 'unet_name', 'flux-2-klein-4b-fp8.safetensors'),
        ('CLIPLoader', 'clip_name', 'qwen_3_4b.safetensors'), ('VAELoader', 'vae_name', 'flux2-vae.safetensors')):
        require(expected in info[node]['input']['required'][field][0], 'image model missing')
    cursor = json.loads(command('journalctl', '-k', '-n', '1', '--no-pager', '-o', 'json'))['__CURSOR']
    return initial, pids, graph, cursor


def main():
    initial, pids, graph, cursor = preflight()
    if sys.argv[1:] == ['--preflight']:
        print('PRODUCTION_CYCLE_PREFLIGHT=PASS; no GPU inference started')
        return 0
    require(not sys.argv[1:] and not REPORT.exists(), 'invalid arguments or existing report')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    report = {'schema': 1, 'started_at': now(), 'result': 'IN_PROGRESS', 'steps': [],
              'gpu_reuse_safe': 'NOT_VERIFIED', 'n1_grant': 'NOT_ADMITTED',
              'scope': 'one production Ollama-Vision-ComfyUI-Ollama cycle',
              'preflight': initial, 'service_pids_before': pids,
              'workflow_sha256': hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()}
    cycle = Cycle()
    cycle.thread.start()
    try:
        cycle.acquire('llm')
        cycle.llm('ollama_before', report)
        cycle.release()
        cycle.acquire('vision-inspection')
        print('vision: START', flush=True)
        cycle.begin('vision-local', 'pcb-inspection')
        require(request(OLLAMA, '/api/ps')['models'] == [], 'Ollama not unloaded before Vision')
        result = request(GATEWAY, cycle.use_path() + '/inspect',
                         {'image_id': 'visa-pcb2-normal-0000'}, timeout=120)
        require(result.get('execution_kind') == 'GPU_INFERENCE'
                and result.get('map_sha256') == '95d773a6aed28e0e19a3b7973a6c78542ae85c668104a36dfc70405bbd0af187',
                'RADIO result mismatch')
        cycle.end()
        cycle.release()
        after_vision = idle()
        models_free(after_vision)
        report['steps'].append({'engine': 'vision', 'result': result, 'after_cleanup': after_vision})
        print('vision: PASS; supervised cleanup confirmed', flush=True)
        cycle.acquire('media-image')
        cycle.begin('comfyui-local', 'image-generation')
        print('comfyui: START (FLUX.2 Klein 512x512, 4 steps)', flush=True)
        started = time.monotonic()
        submit = request(COMFY, '/prompt', {'prompt': graph}, timeout=60)
        require(not submit.get('node_errors') and submit.get('prompt_id'), 'ComfyUI rejected workflow')
        prompt_id = submit['prompt_id']
        max_loaded, max_reserved = 0, 0
        while True:
            require(time.monotonic() - started < 600, 'ComfyUI execution timeout; ownership retained')
            require(not cycle.heartbeat_error, 'lease heartbeat failed')
            entry = request(COMFY, '/history/' + prompt_id).get(prompt_id)
            state = request(COMFY, '/ai-platform/residency')
            stats = request(COMFY, '/system_stats')['devices']
            max_loaded = max(max_loaded, state['loaded_models'])
            max_reserved = max([max_reserved] + [d.get('torch_vram_total', 0) for d in stats])
            if entry:
                require(entry.get('status', {}).get('status_str') == 'success'
                        and entry['status'].get('completed') is True, 'ComfyUI execution failed')
                images = [im for out in entry['outputs'].values() for im in out.get('images', [])]
                require(len(images) == 1, 'expected exactly one generated image')
                image = images[0]
                output_root = Path('/srv/ai-data/comfyui-output').resolve()
                path = (output_root / image.get('subfolder', '') / image['filename']).resolve()
                require(path.is_relative_to(output_root) and path.is_file(), 'invalid output image')
                check = command('/opt/comfyui/venv/bin/python', '-c',
                    'from PIL import Image; import sys,json; im=Image.open(sys.argv[1]); '
                    'print(json.dumps({"size":list(im.size),"format":im.format})); im.verify()', str(path))
                require(json.loads(check) == {'size': [512, 512], 'format': 'PNG'}
                        and max_loaded > 0 and max_reserved > 0, 'image/GPU evidence incomplete')
                break
            time.sleep(1)
        generated = {'engine': 'comfyui', 'seconds': time.monotonic() - started,
                     'image_path': str(path), 'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                     'image_size': [512, 512], 'max_loaded_models': max_loaded,
                     'max_torch_reserved_bytes': max_reserved, 'execution_status': entry['status']['status_str']}
        cycle.end()
        generated['after_cleanup'] = snapshot()
        models_free(generated['after_cleanup'])
        require(all(d['torch_vram_total'] <= 67108864 for d in generated['after_cleanup']['comfyui_devices']),
                'ComfyUI memory remains above accepted idle reserve')
        report['steps'].append(generated)
        print('comfyui: PASS; image verified and models freed', flush=True)
        cycle.llm('ollama_after', report)
        request(GATEWAY, '/api/generate', {'model': MODEL, 'keep_alive': 0, 'stream': False},
                lease=cycle.lease, timeout=120)
        deadline = time.monotonic() + 30
        while request(OLLAMA, '/api/ps')['models']:
            require(time.monotonic() < deadline, 'final Ollama unload unconfirmed')
            time.sleep(.3)
        cycle.release()
        final = idle()
        models_free(final)
        require(services() == pids, 'service restarted during cycle')
        require(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot, 'host rebooted')
        lines = command('journalctl', '-k', '--after-cursor=' + cursor, '--no-pager', '-o', 'json')
        faults = [json.loads(line).get('MESSAGE', '') for line in lines.splitlines()
                  if FAULT.search(json.loads(line).get('MESSAGE', ''))]
        require(not faults, 'new GPU driver error observed')
        require(not cycle.heartbeat_error, 'heartbeat failed during cycle')
        report.update(result='PRODUCTION_GPU_CYCLE_PASS', final=final,
                      service_pids_after=services(), driver_error_matches=faults,
                      comfyui_image_generation='PASS')
    except Exception as error:
        report.update(result='BLOCKED', error=type(error).__name__ + ': ' + str(error)[:200],
                      external_ownership_retained=cycle.use is not None)
        # Never release an uncertain external use, interrupt work, clear a
        # marker, reset the driver or restart services to force this test green.
        if cycle.lease and cycle.use is None:
            try:
                cycle.release()
            except Exception:
                report['lease_release_unconfirmed'] = True
    finally:
        cycle.stop.set()
        cycle.thread.join(timeout=15)
        report['finished_at'] = now()
        REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print(json.dumps({key: report[key] for key in ('result', 'gpu_reuse_safe', 'finished_at')}, sort_keys=True), flush=True)
    return 0 if report['result'] == 'PRODUCTION_GPU_CYCLE_PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
