"""Offline adapter contract/failure tests; not external transport evidence."""
import asyncio
from contextvars import ContextVar
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def plugin(monkeypatch):
    spec = importlib.util.spec_from_file_location('stage_f_test_plugin', ROOT / 'integrations/hermes/ai-platform-messaging/__init__.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_context_isolation_and_exception_cleanup(plugin, monkeypatch):
    identity = ContextVar('test_identity')
    monkeypatch.setitem(sys.modules, 'gateway.session_context', SimpleNamespace(get_session_env=lambda k, d='': identity.get().get(k, d)))
    leases, calls = [], []
    def acquire(**kw):
        lease = SimpleNamespace(lease_id=str(len(leases)), released=False)
        lease.release = lambda: setattr(lease, 'released', True)
        leases.append(lease)
        calls.append(kw)
        return lease
    monkeypatch.setattr(plugin, 'resource_helper', lambda: SimpleNamespace(should_manage_base_url=lambda _: True, acquire_resource=acquire, _json=lambda *a: {'job': {'request_id': 'req_test'}}))
    async def run(i):
        identity.set({'HERMES_SESSION_PLATFORM': 'telegram', 'HERMES_SESSION_CHAT_ID': str(i), 'HERMES_SESSION_THREAD_ID': str(i+10)})
        def downstream(request):
            assert request['extra_headers']['X-AI-Resource-Lease'] in {x.lease_id for x in leases}
            if i == 1:
                raise ValueError('controlled')
            return request
        return await asyncio.to_thread(plugin.execute, {'extra_headers': {'preserved': 'yes'}}, downstream, base_url='local')
    async def run_all():
        return await asyncio.gather(run(0), run(1), return_exceptions=True)
    result = asyncio.run(run_all())
    assert isinstance(result[1], ValueError)
    assert result[0]['extra_headers']['preserved'] == 'yes'
    assert {c['target'] for c in calls} == {'telegram:0:10', 'telegram:1:11'}
    assert all(l.released for l in leases)


def test_media_shell_payload_and_stale_env_are_isolated(plugin, monkeypatch, tmp_path):
    monkeypatch.setenv('HERMES_SESSION_CHAT_ID', 'wrong-user')
    monkeypatch.setenv('HERMES_VIDEO_INPUT_IMAGE', '/stale/image')
    monkeypatch.setenv('HERMES_RESOURCE_LEASE_ID', 'wrong-lease')
    monkeypatch.setitem(sys.modules, 'gateway.run', SimpleNamespace(_event_media_is_image=lambda e, i: e.media_types[i] == 'image/png'))
    calls = []
    async def spawn(*argv, **kw):
        calls.append((argv, kw))
        async def communicate():
            return b'accepted', b''
        return SimpleNamespace(returncode=0, communicate=communicate)
    monkeypatch.setattr(plugin.asyncio, 'create_subprocess_exec', spawn)
    async def run(i):
        source = SimpleNamespace(platform=SimpleNamespace(value='telegram'), chat_id=str(i), thread_id=str(i+10))
        event = SimpleNamespace(source=source, media_urls=[str(tmp_path / f'{i}.png')], media_types=['image/png'])
        plugin.observe(event, object())
        return await plugin.media('foto', 'literal $(touch /tmp/never); `false`')
    async def all_contexts():
        return await asyncio.gather(run(1), run(2))
    assert asyncio.run(all_contexts()) == ['accepted', 'accepted']
    for i, (argv, kwargs) in enumerate(calls, 1):
        assert argv == ('/usr/local/bin/hermes-foto-dispatch', 'literal $(touch /tmp/never); `false`')
        assert kwargs['env']['HERMES_SESSION_CHAT_ID'] == str(i)
        assert kwargs['env']['HERMES_FOTO_INPUT_IMAGE'] == str(tmp_path / f'{i}.png')
        assert 'HERMES_VIDEO_INPUT_IMAGE' not in kwargs['env']
        assert 'HERMES_RESOURCE_LEASE_ID' not in kwargs['env']
    assert calls[0][1]['env']['AI_PLATFORM_REQUEST_ID'] != calls[1][1]['env']['AI_PLATFORM_REQUEST_ID']


def test_voice_targets_invoking_guild_and_cleans_owned_artifact(plugin, monkeypatch):
    discord = object()
    monkeypatch.setitem(sys.modules, 'gateway.config', SimpleNamespace(Platform=SimpleNamespace(DISCORD=discord)))
    paths, played = [], []
    def tts(text, output_path):
        path = Path(output_path)
        path.write_bytes(b'internal test audio fixture')
        paths.append(path)
        return '{}'
    monkeypatch.setitem(sys.modules, 'tools.tts_tool', SimpleNamespace(text_to_speech_tool=tts))
    async def play(guild, path):
        assert Path(path).exists()
        played.append(guild)
        return True
    adapter = SimpleNamespace(_voice_text_channels={1: 'a', 2: 'b'}, is_in_voice_channel=lambda _: True, play_in_voice_channel=play)
    source = SimpleNamespace(platform=discord, chat_id='b')
    origin = SimpleNamespace(task=SimpleNamespace(done=lambda: False), event=SimpleNamespace(source=source), gateway=SimpleNamespace(adapters={discord: adapter}))
    asyncio.run(plugin.voice_notice(origin, 'queued'))
    assert played == [2]
    assert all(not path.exists() and not path.parent.exists() for path in paths)


def test_missing_context_refuses_media(plugin):
    assert 'kontekstu' in asyncio.run(plugin.media('foto', 'test'))


def gate_module():
    spec = importlib.util.spec_from_file_location('stage_f_gate', ROOT / 'deploy/stage-f/autopilot/gate.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_preflight_cannot_create_state(monkeypatch, tmp_path):
    gate = gate_module()
    monkeypatch.setattr(gate, 'STATE', tmp_path / 'never-created')
    monkeypatch.setattr(gate.e, 'git_run', lambda _: 'a' * 40)
    calls = []
    monkeypatch.setattr(gate, 'preflight', lambda: calls.append(True))
    gate.main('00_preflight')
    assert calls == [True]
    assert not gate.STATE.exists()


def test_failed_configuration_never_switches_or_reopens_ingress(monkeypatch, tmp_path):
    gate = gate_module()
    old = tmp_path / 'old'
    old.mkdir()
    current = tmp_path / 'current'
    current.symlink_to(old)
    monkeypatch.setattr(gate, 'BASE', old)
    monkeypatch.setattr(gate.e, 'CURRENT', current)
    monkeypatch.setattr(gate, 'verify_release', lambda _: {})
    monkeypatch.setattr(gate.e, 'clients', lambda: {})
    actions = []
    monkeypatch.setattr(gate.e, 'quiesce', lambda *a, **k: actions.append('quiesce'))
    monkeypatch.setattr(gate.e, 'require_hermes_stopped', lambda: None)
    monkeypatch.setattr(gate.e, 'comfy_idle', lambda: None)
    monkeypatch.setattr(gate, 'require_no_media_workers', lambda: None)
    monkeypatch.setattr(gate, 'recover_gpu_quiesced', lambda state: None)
    def fail(*a):
        raise RuntimeError('configuration validation failed')
    monkeypatch.setattr(gate, 'configure', fail)
    monkeypatch.setattr(gate.e, 'resume_ingress', lambda _: actions.append('unsafe-resume'))
    with pytest.raises(RuntimeError):
        gate.switch(tmp_path / 'candidate', tmp_path / 'candidate', tmp_path, {'clients': {}})
    assert current.resolve() == old
    assert actions == ['quiesce']


def test_media_cancel_kills_and_reaps_dispatch_process(plugin, monkeypatch):
    monkeypatch.setitem(sys.modules, 'gateway.run', SimpleNamespace(_event_media_is_image=lambda *a: False))
    actions = []
    async def communicate():
        raise asyncio.CancelledError()
    async def wait():
        actions.append('wait')
    async def spawn(*a, **k):
        return SimpleNamespace(returncode=None, communicate=communicate, kill=lambda: actions.append('kill'), wait=wait)
    monkeypatch.setattr(plugin.asyncio, 'create_subprocess_exec', spawn)
    async def scenario():
        source = SimpleNamespace(platform=SimpleNamespace(value='discord'), chat_id='a', thread_id=None)
        plugin.observe(SimpleNamespace(source=source, media_urls=[]), object())
        await plugin.media('wideo', '1s synthetic fixture')
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scenario())
    assert actions == ['kill', 'wait']


def test_interrupted_atomic_restore_preserves_original(monkeypatch, tmp_path):
    import os
    gate = gate_module()
    path = tmp_path / 'source.py'
    path.write_bytes(b'original')
    def fail(*_):
        raise OSError('controlled interruption before replace')
    monkeypatch.setattr(gate.os, 'replace', fail)
    with pytest.raises(OSError):
        gate.atomic_restore(path, b'candidate', 0o600, os.getuid(), os.getgid())
    assert path.read_bytes() == b'original'
    assert list(tmp_path.iterdir()) == [path]


def test_harness_uses_configured_hermes_model_not_bridge_default(tmp_path):
    spec = importlib.util.spec_from_file_location('internal_harness_test', ROOT / 'deploy/stage-f/internal_e2e.py')
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    config = tmp_path / 'config.yaml'
    config.write_text('model:\n  default: qwen3.6:35b-hermes64k\n  base_url: http://127.0.0.1:11435/clients/hermes/v1\n')
    assert harness.configured_hermes_model(config) == 'qwen3.6:35b-hermes64k'


def test_rollback_never_requires_healthy_candidate(monkeypatch, tmp_path):
    gate = gate_module()
    baseline, candidate = tmp_path / 'baseline', tmp_path / 'broken-candidate'
    baseline.mkdir()
    candidate.mkdir()
    current = tmp_path / 'current'
    current.symlink_to(candidate)
    monkeypatch.setattr(gate, 'BASE', baseline)
    monkeypatch.setattr(gate.e, 'CURRENT', current)
    actions = []
    monkeypatch.setattr(gate, 'verify_release', lambda p: actions.append(('verify', p)))
    monkeypatch.setattr(gate.e, 'clients', lambda: pytest.fail('failed candidate must not be inspected'))
    monkeypatch.setattr(gate.e, 'quiesce', lambda b, **kw: actions.append(('quiesce', kw)))
    monkeypatch.setattr(gate.e, 'require_hermes_stopped', lambda: None)
    monkeypatch.setattr(gate.e, 'comfy_idle', lambda: None)
    monkeypatch.setattr(gate, 'require_no_media_workers', lambda: None)
    monkeypatch.setattr(gate, 'recover_gpu_quiesced', lambda state: None)
    monkeypatch.setattr(gate, 'configure', lambda c, s, b, rollback: actions.append(('restore', rollback)))
    monkeypatch.setattr(gate, 'run', lambda *a, **kw: None)
    monkeypatch.setattr(gate.e, 'config', lambda: {})
    monkeypatch.setattr(gate.e, 'runtime', lambda target, *a: actions.append(('runtime', target)))
    monkeypatch.setattr(gate.e, 'resume_ingress', lambda b: actions.append(('resume', True)))
    gate.switch(baseline, candidate, tmp_path, {})
    assert current.resolve() == baseline
    assert ('verify', baseline) in actions and ('verify', candidate) not in actions
    assert ('quiesce', {'allow_gateway_unavailable': True}) in actions
    assert actions[-1] == ('resume', True)


def test_snapshot_closes_sqlite_before_inventory(tmp_path):
    import sqlite3
    from contextlib import closing
    source, target = tmp_path / 'live.sqlite', tmp_path / 'backup.sqlite'
    with closing(sqlite3.connect(source)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE evidence(value INTEGER)')
        db.execute('INSERT INTO evidence VALUES (42)')
        db.commit()
        gate_module().backup_database(source, target)
        assert target.exists()
        assert not target.with_name(target.name + '-wal').exists()
        assert not target.with_name(target.name + '-shm').exists()
        with closing(sqlite3.connect(target)) as restored:
            assert restored.execute('SELECT value FROM evidence').fetchall() == [(42,)]


def test_kernel_guard_does_not_match_successfully():
    spec = importlib.util.spec_from_file_location('gpu_watch_test', ROOT / 'deploy/stage-f/gpu_watch.py')
    watch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watch)
    assert not watch.GPU_ERROR.search('amdgpu 0000:c6:00.0: SMU is initialized successfully!')
    for message in ('amdgpu: MES ring buffer is full.', 'amdgpu: MES failed to respond',
                    'amdgpu: GPU reset begin', 'amdgpu: ring gfx timeout'):
        assert watch.GPU_ERROR.search(message)
