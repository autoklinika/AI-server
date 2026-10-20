#!/usr/bin/env python3
"""Operator pilot: exactly one existing Gateway RM instance at a time.

The original Gateway is stopped only to open this controlled test window, then
restored. Ollama/ComfyUI are never restarted during workload handoffs. No N1
policy changes or global GPU_REUSE_SAFE claims. Two single-image inspections
exercise both return paths; no archive or frozen benchmark is overwritten.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
MARKER = Path('/var/lib/ai-platform-gpu/residency.blocked')
REPORT = Path('/var/lib/ai-platform-radio/PILOT_RESULT.json')


def command(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=40)
    if p.returncode != 0:
        raise RuntimeError('system command failed: ' + args[0])
    return p.stdout.strip()


def request(method, path, body=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request('http://127.0.0.1:11435' + path, method=method,
                                 data=data, headers={'Content-Type': 'application/json'})
    with opener.open(req, timeout=4) as response:
        return json.load(response)


def read(path):
    return request('GET', path)


def reserve_window():
    # Reserve via the LIVE existing scheduler before stopping it. A racing
    # user job wins the slot; this pilot then aborts without interrupting it.
    lease = request('POST', '/resource/leases', {'workload': 'external',
                    'source': 'operator-radio-pilot-window', 'priority': -1000})
    path = '/resource/leases/' + lease['lease_id']
    try:
        require(lease.get('state') == 'active', 'another job won the maintenance window')
        status = read('/status')
        require(status.get('max_concurrency') == 1 and status.get('active_count') == 1
                and status.get('queued_count') == 0
                and status['active'][0]['job_id'] == lease['job_id']
                and status.get('resource_leases', {}).get('lease_count') == 1,
                'maintenance window not exclusive')
    except BaseException:
        request('DELETE', path)
        raise
    return path


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def production_marker(gateway_pid):
    environment = Path(f'/proc/{gateway_pid}/environ').read_bytes().split(b'\0')
    marker_values = [p.split(b'=', 1)[1].decode() for p in environment
                     if p.startswith(b'AI_BRIDGE_GATEWAY_GPU_MARKER=')]
    require(marker_values == [str(MARKER)], 'production marker path not pinned')


def idle_status(status):
    require(status.get('active_count') == 0 and status.get('queued_count') == 0
        and status.get('admission_blocked') is False
        and status.get('resource_leases', {}).get('lease_count') == 0
        and status.get('resource_manager', {}).get('state') == 'IDLE'
        and status.get('gpu_residency', {}).get('recovery_required') is False,
        'Gateway is busy or uncertain')


async def run_pilot():
    import httpx
    from ai_bridge.gateway.app import create_gateway_app
    from ai_bridge.gateway.vision_radio_client import RadioExecutorClient
    from ai_bridge.settings import Settings
    runtime = RadioExecutorClient()
    require(runtime.available(), 'fixed root supervisor not available')
    app = create_gateway_app(Settings(_env_file=None, gateway_gpu_marker=MARKER,
        gateway_gpu_transition_timeout=45, gateway_comfy_idle_reserve_bytes=67108864,
        gateway_max_concurrency=1, gateway_admission_strategy='legacy'), vision_executor=runtime)
    outputs = []
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
            base_url='http://operator-pilot.invalid', timeout=100, trust_env=False) as client:
            async def idle():
                idle_status((await client.get('/status')).json())
            async def ollama():
                response = await client.post('/api/embed', json={
                    'model': 'bge-m3:latest', 'input': 'Vision RADIO RM pilot', 'keep_alive': 0})
                require(response.status_code == 200, 'Ollama GPU handoff failed')
                values = response.json().get('embeddings')
                require(isinstance(values, list) and len(values) == 1 and len(values[0]) == 1024,
                        'Ollama result contract failed')
                await idle()
            async def comfy():
                response = await client.post('/resource/leases', json={'workload': 'media-image'})
                require(response.status_code == 201, 'ComfyUI lease failed')
                path = '/resource/leases/' + response.json()['lease_id']
                response = await client.post(path + '/uses', json={
                    'provider': 'comfyui-local', 'capability': 'image-generation'})
                require(response.status_code == 201, 'ComfyUI prepare failed')
                use = path + '/uses/' + response.json()['use_id']
                require((await client.get(use)).status_code == 200, 'ComfyUI verify failed')
                require((await client.delete(use)).json().get('released') is True, 'ComfyUI release failed')
                await client.delete(path)
                await idle()
            async def vision():
                response = await client.post('/resource/leases', json={'workload': 'vision-inspection'})
                require(response.status_code == 201, 'Vision lease failed')
                path = '/resource/leases/' + response.json()['lease_id']
                response = await client.post(path + '/uses', json={
                    'provider': 'vision-local', 'capability': 'pcb-inspection'})
                require(response.status_code == 201, 'Vision prepare failed closed')
                use = path + '/uses/' + response.json()['use_id']
                require((await client.get(use)).status_code == 200, 'Vision identity verification failed')
                response = await client.post(use + '/inspect', json={'image_id': 'visa-pcb2-normal-0000'})
                require(response.status_code == 200, 'RADIO inference failed closed')
                result = response.json()
                require(result.get('execution_kind') == 'GPU_INFERENCE', 'GPU execution not confirmed')
                require((await client.delete(use)).json().get('released') is True, 'RADIO cleanup unconfirmed')
                await client.delete(path)
                await idle()
                # Never publish lease/use IDs in the result intended for review.
                outputs.append(result)
            await idle()
            await ollama()
            await vision()
            await ollama()
            await comfy()
            await vision()
            await comfy()
            await idle()
    return outputs


def main():
    result = {'schema': 1, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'result': 'BLOCKED', 'gpu_reuse_safe': 'NOT_VERIFIED', 'n1_grant': 'NOT_ADMITTED',
        'production_install': 'NOT_PERFORMED', 'comfyui_image_generation': 'NOT_TESTED'}
    stopped = False
    window = None
    try:
        require(os.geteuid() == 0, 'operator authorization required')
        idle_status(read('/status'))
        require(not MARKER.exists(), 'GPU marker present')
        for unit in ('ai-gateway.service', 'ollama.service', 'comfyui.service', 'ai-bridge.service'):
            require(command('systemctl', 'is-active', unit) == 'active', 'service unavailable')
        timer = subprocess.run(['systemctl', 'is-active', 'ai-bridge-analysis.timer'], capture_output=True, text=True, timeout=5)
        require(timer.returncode == 3 and timer.stdout.strip() == 'inactive', 'analysis timer active or unknown')
        # Verify the production marker path rather than using a private marker
        # that the restored Gateway could ignore after a failed test.
        gateway_pid = int(command('systemctl', 'show', 'ai-gateway.service', '-p', 'MainPID', '--value'))
        production_marker(gateway_pid)
        window = reserve_window()
        stopped = True
        command('systemctl', 'stop', 'ai-gateway.service')
        result['radio_inspections'] = asyncio.run(run_pilot())
        result['result'] = 'GPU_PILOT_PASS'
        result['handoffs'] = ['Ollama-Vision-Ollama', 'ComfyUI-Vision-ComfyUI']
    except BaseException as error:
        result['error'] = type(error).__name__ + ': ' + str(error)[:200]
        diagnostic = Path('/var/lib/ai-platform-radio/LAST_ERROR.json')
        if diagnostic.is_file():
            try:
                detail = json.loads(diagnostic.read_text())
                result['supervisor_error'] = {key: str(detail[key])[:200] for key in ('type', 'reason')}
            except (OSError, ValueError, KeyError):
                pass
        if stopped:
            MARKER.parent.mkdir(parents=True, exist_ok=True)
            with MARKER.open('a') as stream:
                stream.write('Vision RADIO pilot unresolved; operator review required.\n')
                stream.flush()
                os.fsync(stream.fileno())
    finally:
        if stopped:
            try:
                # A failed pilot restores the original service in BLOCKED mode.
                # Never clear its GPU marker to make the smoke test pass.
                command('systemctl', 'start', 'ai-gateway.service')
                deadline = time.monotonic() + 35
                while True:
                    try:
                        snapshot = read('/status')
                        if result['result'] == 'GPU_PILOT_PASS':
                            idle_status(snapshot)
                        else:
                            require(snapshot.get('admission_blocked') is True, 'failed pilot did not restore BLOCKED')
                        result['prior_gateway_restored'] = True
                        break
                    except Exception:
                        if time.monotonic() > deadline:
                            raise
                        time.sleep(.3)
            except BaseException as error:
                result['result'] = 'BLOCKED'
                result['restore_error'] = type(error).__name__
        REPORT.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
        print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result['result'] == 'GPU_PILOT_PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
