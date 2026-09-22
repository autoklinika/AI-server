#!/usr/bin/env python3
"""SYNTHETIC/INTERNAL E2E. Never accepts or emits external platform updates.

Real pinned Hermes plugin dispatch/context/middleware, real localhost Gateway/RM,
Qwen and production media dispatchers/renderers. Only platform delivery is replaced
with an explicit recording sink. Run while ingress is quiesced by production gate.
"""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = 'http://127.0.0.1:11435'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fetch(path, payload=None, headers=None):
    request = Request(GATEWAY + path, data=None if payload is None else json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json', **(headers or {})})
    with urlopen(request, timeout=600) as response:
        return json.load(response), dict(response.headers)


def idle():
    doc, _ = fetch('/status')
    assert (doc['active_count'], doc['queued_count'], doc['resource_leases']['lease_count']) == (0, 0, 0)


def configured_hermes_model(path):
    # The Bridge's base model is not the Hermes runtime model. Read only the
    # configured local binding; never serialize the private configuration.
    import yaml
    config = yaml.safe_load(path.read_text())
    model = config.get('model', {})
    assert model.get('base_url', '').rstrip('/') == GATEWAY + '/clients/hermes/v1'
    value = model.get('default')
    assert isinstance(value, str) and value.strip()
    return value


def media_child(command, payload, worker=False):
    """Keep the actual dispatcher and worker; replace ONLY egress and worker launcher."""
    if command == 'foto':
        module = load('e2e_foto', ROOT / 'tools/local_image/hermes_foto_dispatch_global.py')
        base, resource = module.base, module.resource
    else:
        module = load('e2e_video', ROOT / 'tools/local_video/hermes_video_dispatch_global.py')
        base, resource = module.stage30.base, module.resource
    sink = Path(os.environ['AI_INTERNAL_SINK'])
    def record(target, message, **_):
        assert target.startswith(('telegram:synthetic-', 'discord:synthetic-'))
        item = {'target': target, 'kind': 'media' if message.startswith('MEDIA:') else 'notice'}
        if item['kind'] == 'media':
            artifact = Path(message[6:])
            assert artifact.is_file() and artifact.stat().st_size > 0
            item.update(path=str(artifact), sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
                        bytes=artifact.stat().st_size)
            if artifact.suffix == '.mp4':
                probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                    'stream=codec_type,width,height', '-of', 'json', artifact], text=True)
                assert any(s.get('codec_type') == 'video' for s in json.loads(probe)['streams'])
            else:
                from PIL import Image
                with Image.open(artifact) as image:
                    image.verify()
        with sink.open('a') as stream:
            stream.write(json.dumps(item) + '\n')
    base._send = record
    resource._notify = lambda target, message: record(target, message) if message else None
    if worker:
        return module.worker(Path(payload)) if command == 'foto' else module.run_worker(Path(payload))
    original = subprocess.Popen
    def launch(argv, **kwargs):
        # Production dispatch persists the request and chooses a worker; redirect
        # its child to the same production worker with the recording egress sink.
        assert '--worker' in argv
        return original([sys.executable, __file__, '--child-worker', command, argv[-1]], **kwargs)
    subprocess.Popen = launch
    try:
        print(module.dispatch(payload) if command == 'foto' else module.queue_job([payload]), flush=True)
    finally:
        subprocess.Popen = original
    return 0


async def exercise(output, media_enabled):
    from gateway.config import Platform
    from gateway.session import SessionSource
    from gateway.platforms.base import MessageEvent
    from gateway.run_inbound import GatewayInboundMixin
    from gateway.session_context import set_session_vars, clear_session_vars
    from hermes_cli.plugins import PluginContext, PluginManifest, PluginManager
    import hermes_cli.plugins as plugins
    from hermes_cli.middleware import run_llm_execution_middleware

    plugin = load('internal_messaging_plugin', ROOT / 'integrations/hermes/ai-platform-messaging/__init__.py')
    manager = PluginManager()
    # Use real registration and execution; isolate discovery from private profiles.
    plugins.get_plugin_manager = lambda *a, **k: manager
    plugins._delivery_manager = lambda: manager
    plugin.register(PluginContext(PluginManifest(name='ai-platform-messaging', version='1.0.0'), manager))
    helper = plugin.resource_helper()
    notices = []
    helper._notify = lambda target, message: notices.append((target, message)) if message else None
    os.environ['HERMES_RESOURCE_QUEUE_NOTICE_AFTER'] = '0'
    os.environ['HERMES_RESOURCE_POLL_SECONDS'] = '0.1'
    runner = GatewayInboundMixin()
    runner.adapters = {}
    runner._draining = False
    runner._hm_quick_commands = lambda: {}
    sources = [SessionSource(platform=p, chat_id=f'synthetic-{i}', user_id=f'synthetic-user-{i}',
                             thread_id=f'{100+i}')
               for i, p in enumerate((Platform.TELEGRAM, Platform.TELEGRAM, Platform.DISCORD, Platform.DISCORD))]
    model = configured_hermes_model(Path('/srv/ai-data/hermes/config.yaml'))

    records = []
    async def chat(source):
        event = MessageEvent(text='Return the word OK.', source=source)
        assert runner._hm_pre_gateway_dispatch_hook(event, source) is event
        tokens = set_session_vars(platform=source.platform.value, chat_id=source.chat_id,
                                  thread_id=source.thread_id, user_id=source.user_id)
        try:
            def terminal(request):
                headers = request.pop('extra_headers')
                result, response = fetch('/clients/hermes/v1/chat/completions', request, headers)
                assert result['choices'][0]['message']['content'].strip()
                response = {k.lower(): v for k, v in response.items()}
                assert response['x-ai-request-id'] == headers['X-Request-Id']
                records.append({'target': plugin.route(source), 'request_id': response['x-ai-request-id'],
                                'job_id': response['x-ai-job-id'], 'lease_id': headers['X-AI-Resource-Lease'], 'job_kind': 'resource reservation'})
                return result
            await asyncio.to_thread(run_llm_execution_middleware,
                {'model': model, 'messages': [{'role': 'user', 'content': 'Return the word OK.'}], 'stream': False, 'max_tokens': 32, 'reasoning_effort': 'none'},
                terminal, base_url=GATEWAY + '/clients/hermes/v1', api_call_count=1)
        finally:
            clear_session_vars(tokens)
    idle()
    blocker = await asyncio.to_thread(helper.acquire_resource, target=None, source='internal-e2e-blocker', workload='llm')
    tasks = [asyncio.create_task(chat(source)) for source in sources]
    try:
        deadline = time.monotonic() + 30
        while len(notices) < len(sources):
            assert time.monotonic() < deadline, 'all contexts must reach WAIT'
            if any(task.done() and task.exception() for task in tasks):
                await asyncio.gather(*tasks)
            await asyncio.sleep(.1)
    finally:
        blocker.release()
    await asyncio.gather(*tasks)
    assert len(records) == 4
    assert len({r['request_id'] for r in records}) == len({r['job_id'] for r in records}) == 4
    for source in sources:
        route = plugin.route(source)
        messages = [message for target, message in notices if target == route]
        assert len(messages) == 2 and messages[0].startswith('⏳') and messages[1].startswith('▶️')
    for record in records:
        job, _ = fetch('/api/v1/jobs/' + record['job_id'])
        assert job['job']['request_id'] == record['request_id'] and job['job']['state'] == 'completed'
    idle()
    # A failing provider call must release its reservation and heartbeat.
    tokens = set_session_vars(platform='telegram', chat_id='synthetic-failure')
    def fail(_):
        raise RuntimeError('controlled provider failure')
    try:
        try:
            await asyncio.to_thread(run_llm_execution_middleware, {}, fail, base_url=GATEWAY, api_call_count=2)
        except RuntimeError as exc:
            assert str(exc) == 'controlled provider failure'
        else:
            raise AssertionError('failure was swallowed')
    finally:
        clear_session_vars(tokens)
    idle()
    artifacts = []
    if media_enabled:
        actual_spawn = asyncio.create_subprocess_exec
        with tempfile.TemporaryDirectory(prefix='stage-f-internal-media-') as directory:
            root = Path(directory)
            async def spawn(binary, args, **kwargs):
                assert binary in ('/usr/local/bin/hermes-foto-dispatch', '/usr/local/bin/hermes-video-dispatch')
                command = 'foto' if 'foto' in binary else 'wideo'
                env = kwargs['env']
                assert env['HERMES_SESSION_CHAT_ID'].startswith('synthetic-')
                env.update(AI_INTERNAL_SINK=str(root / 'deliveries.jsonl'),
                           HERMES_FOTO_JOB_ROOT=str(root / 'foto'), HERMES_VIDEO_JOB_ROOT=str(root / 'wideo'))
                return await actual_spawn(sys.executable, __file__, '--child-dispatch', command, args, **kwargs)
            asyncio.create_subprocess_exec = spawn
            try:
                # Both platforms exercise both commands using independent origins.
                for index, source in enumerate(sources):
                    command = 'foto' if index % 2 == 0 else 'wideo'
                    prompt = 'A small metal gear on a clean workbench.'
                    args = prompt if command == 'foto' else '1s ' + prompt
                    media_paths = [previous_image] if command == 'wideo' else []
                    event = MessageEvent(text=f'/{command} {args}', source=source,
                                         media_urls=media_paths, media_types=['image/png'] if media_paths else [])
                    runner._hm_pre_gateway_dispatch_hook(event, source)
                    # Actual Hermes command handler dispatch, with quick commands
                    # empty as installed by Stage F; no fabricated inbound transport.
                    handled, reply, _ = await runner._hm_dispatch_quick_and_plugin_commands(event, source, command)
                    assert handled and reply and 'Przyjęto' in reply
                    deadline = time.monotonic() + 2400
                    while True:
                        results = list(root.glob('*/*/result.json'))
                        if len(results) == index + 1:
                            latest = max(results, key=lambda p: p.stat().st_mtime_ns)
                            result = json.loads(latest.read_text())
                            assert result.get('ok') is True, 'production media worker failed'
                            assert result.get('qwen_used') is True, 'prompt compiler fallback is not a PASS'
                            if command == 'foto':
                                previous_image = result['path']
                            else:
                                assert result['mode'] == 'i2v' and result.get('input_image')
                            assert result['target'] == plugin.route(source)
                            break
                        assert time.monotonic() < deadline, 'media worker timeout'
                        await asyncio.sleep(2)
                    for attempt in range(30):
                        try:
                            idle()
                            break
                        except AssertionError:
                            if attempt == 29:
                                raise
                            await asyncio.sleep(1)
                deliveries = [json.loads(line) for line in (root / 'deliveries.jsonl').read_text().splitlines()]
                artifacts = [d for d in deliveries if d['kind'] == 'media']
                assert len(artifacts) == 4 and {d['target'] for d in artifacts} == {plugin.route(s) for s in sources}
                # Only generated artifacts evidenced in this controlled run are removed.
                for artifact in artifacts:
                    path = Path(artifact.pop('path'))
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact['sha256']
                    path.unlink()
                    assert not path.exists()
            finally:
                asyncio.create_subprocess_exec = actual_spawn
        assert not root.exists()
    idle()
    evidence = {'evidence_class': 'SYNTHETIC/INTERNAL E2E', 'external_transport': 'DEFERRED/NOT TESTED',
                'status': 'PASS', 'chat_contexts': records, 'queue_wait_start': 'PASS',
                'provider_failure_cleanup': 'PASS', 'idle_recovery': 'PASS',
                'media': artifacts if media_enabled else 'NOT RUN',
                'delivery': 'internal recording sink; no external send or inbound update',
                'time': int(time.time())}
    with output.open('x') as stream:
        json.dump(evidence, stream, indent=2)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('--child-worker', '--child-dispatch'):
        raise SystemExit(media_child(sys.argv[2], sys.argv[3], sys.argv[1] == '--child-worker'))
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--media', action='store_true')
    args = parser.parse_args()
    # Private config is only read by the production media compiler/settings.
    # Hermes discovery/session stores are isolated; no credentials are copied.
    with tempfile.TemporaryDirectory(prefix='stage-f-hermes-profile-') as profile:
        os.environ['HERMES_HOME'] = profile
        asyncio.run(exercise(args.output, args.media))
