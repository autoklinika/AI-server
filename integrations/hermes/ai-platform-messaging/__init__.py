"""Supported Hermes plugin at pin 79445a496c86a19332ad786494b8384d2167e2d0.

No source patching or process-global session mutation. The pre-dispatch observer
only captures context; Hermes still performs authorization and command dispatch.
"""
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from uuid import uuid4

_origin = ContextVar('ai_platform_origin', default=None)
_helper_lock = threading.Lock()


@dataclass(frozen=True)
class Origin:
    event: object
    gateway: object
    loop: object
    request_id: str
    task: object


def observe(event, gateway, **_):
    _origin.set(Origin(event, gateway, asyncio.get_running_loop(), uuid4().hex, asyncio.current_task()))
    # None lets all observers run and retains Hermes authorization.


def resource_helper():
    name = '_ai_platform_resource_queue'
    with _helper_lock:
        if name not in sys.modules:
            path = '/usr/local/libexec/ai-server/hermes_resource_queue.py'
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
    return sys.modules[name]


def route(source):
    platform = source.platform.value
    if platform not in ('telegram', 'discord') or not source.chat_id:
        raise ValueError('unsupported messaging context')
    target = f'{platform}:{source.chat_id}'
    return target + (f':{source.thread_id}' if source.thread_id else '')


async def voice_notice(origin, event):
    from gateway.config import Platform
    source = origin.event.source
    if origin.task.done():
        return
    if source.platform != Platform.DISCORD:
        return
    adapter = origin.gateway.adapters.get(Platform.DISCORD)
    if adapter is None or not hasattr(adapter, 'play_in_voice_channel'):
        return
    channels = getattr(adapter, '_voice_text_channels', {})
    guild = next((g for g, c in channels.items()
                  if str(c) == str(source.chat_id) and adapter.is_in_voice_channel(g)), None)
    if guild is None:
        return
    phrase = {'queued': 'Serwer AI jest zajęty. Dodałem pytanie do kolejki.',
              'active': 'Zwolniły się zasoby. Zaczynam.'}.get(event)
    if not phrase:
        return
    from tools.tts_tool import text_to_speech_tool
    # Each invocation owns its directory. Never unlink a provider-supplied path
    # outside it (the old patch trusted arbitrary file_path from TTS).
    with tempfile.TemporaryDirectory(prefix='ai-platform-voice-') as directory:
        output = Path(directory) / 'queue.mp3'
        raw = await asyncio.to_thread(text_to_speech_tool, text=phrase, output_path=str(output))
        result = json.loads(raw) if isinstance(raw, str) else {}
        actual = Path(result.get('file_path') or output).resolve()
        if actual.parent != Path(directory).resolve() or not actual.is_file():
            raise RuntimeError('queue voice artifact missing or outside owned directory')
        if origin.task.done():
            return
        if not await adapter.play_in_voice_channel(guild, str(actual)):
            raise RuntimeError('queue voice playback failed')


def execute(request, next_call, base_url='', api_call_count=1, **_):
    helper = resource_helper()
    from gateway.session_context import get_session_env
    platform = get_session_env('HERMES_SESSION_PLATFORM', '')
    chat = get_session_env('HERMES_SESSION_CHAT_ID', '')
    thread = get_session_env('HERMES_SESSION_THREAD_ID', '')
    if platform not in ('telegram', 'discord') or not chat or not helper.should_manage_base_url(base_url):
        return next_call(request)
    target = f'{platform}:{chat}' + (f':{thread}' if thread else '')
    origin = _origin.get()
    # Never reuse inherited inbound context for another session/delegated turn.
    if origin is not None and route(origin.event.source) != target:
        origin = None
    first = int(api_call_count or 0) <= 1
    def status(event):
        if origin is not None and platform == 'discord' and first:
            future = asyncio.run_coroutine_threadsafe(voice_notice(origin, event), origin.loop)
            # Consume errors without interrupting admission; text notice is independent.
            future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
    lease = helper.acquire_resource(
        target=target, source=platform + '-chat', priority=50,
        queue_message='⏳ Serwer AI jest teraz zajęty. Twoje zapytanie czeka w kolejce.' if first else None,
        start_message='▶️ Zwolniły się zasoby. Rozpoczynam Twoje zapytanie.' if first else None,
        status_callback=status if first else None)
    try:
        headers = dict(request.get('extra_headers') or {})
        headers.update({'X-AI-Resource-Lease': lease.lease_id,
                        'X-AI-Resource-Lease-Release': '1'})
        # Per provider call: retries/tool loops cannot alias request/job identities.
        reservation = helper._json('GET', f'/resource/leases/{lease.lease_id}')
        headers['X-Request-Id'] = reservation['job']['request_id']
        return next_call({**request, 'extra_headers': headers})
    finally:
        # Hermes _perform_api_call consumes its stream before returning. Also
        # covers transport exceptions and cancellation before Gateway sees it.
        lease.release()


async def media(command, args):
    origin = _origin.get()
    if origin is None:
        return 'Polecenie wymaga kontekstu wiadomości Telegram lub Discord.'
    source = origin.event.source
    route(source)  # validate before subprocess creation
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith('HERMES_SESSION_') or key in ('HERMES_FOTO_INPUT_IMAGE', 'HERMES_VIDEO_INPUT_IMAGE', 'HERMES_RESOURCE_LEASE_ID'):
            env.pop(key)
    env.update(HERMES_SESSION_PLATFORM=source.platform.value,
               HERMES_SESSION_CHAT_ID=str(source.chat_id),
               HERMES_SESSION_THREAD_ID=str(source.thread_id or ''),
               AI_PLATFORM_REQUEST_ID=origin.request_id)
    from gateway.run import _event_media_is_image
    images = [str(path) for i, path in enumerate(origin.event.media_urls or [])
              if _event_media_is_image(origin.event, i)]
    if images:
        env['HERMES_FOTO_INPUT_IMAGE' if command == 'foto' else 'HERMES_VIDEO_INPUT_IMAGE'] = images[0]
    binary = '/usr/local/bin/hermes-foto-dispatch' if command == 'foto' else '/usr/local/bin/hermes-video-dispatch'
    proc = await asyncio.create_subprocess_exec(binary, args, env=env,
                                                stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), 30)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise
    if proc.returncode:
        return f'Nie udało się uruchomić /{command}.'
    return stdout.decode().strip()


def register(ctx):
    ctx.register_hook('pre_gateway_dispatch', observe)
    ctx.register_middleware('llm_execution', execute)
    for command in ('foto', 'wideo'):
        async def handler(args, command=command):
            return await media(command, args)
        ctx.register_command(command, handler, description='AI Platform media', args_hint='<prompt>')
