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
    monkeypatch.setattr(gate, 'recover_gpu_quiesced', lambda state, **kw: None)
    monkeypatch.setattr(gate.e, 'identity', lambda unit: ['synthetic-pid', 'synthetic-start'])
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
        # Telegram keeps the production media subprocess path. Discord media is
        # intentionally blocked by the technical-only policy and therefore must
        # never reach this cancellation/subprocess test.
        source = SimpleNamespace(platform=SimpleNamespace(value='telegram'), chat_id='a', thread_id=None)
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
    monkeypatch.setattr(gate, 'recover_gpu_quiesced', lambda state, **kw: None)
    monkeypatch.setattr(gate.e, 'identity', lambda unit: ['synthetic-pid', 'synthetic-start'])
    monkeypatch.setattr(gate, 'configure', lambda c, s, b, rollback: actions.append(('restore', rollback)))
    monkeypatch.setattr(gate, 'run', lambda *a, **kw: None)
    monkeypatch.setattr(gate.e, 'config', lambda: {})
    monkeypatch.setattr(gate.e, 'runtime', lambda target, *a: actions.append(('runtime', target)))
    monkeypatch.setattr(gate.e, 'resume_ingress', lambda b: actions.append(('resume', True)))
    gate.switch(baseline, candidate, tmp_path, {})
    assert current.resolve() == baseline
    assert ('verify', baseline) in actions and ('verify', candidate) not in actions
    assert ('quiesce', {'allow_gateway_unavailable': True}) in actions
    assert ('resume', True) not in actions  # Legacy media ingress stays paused until F reactivation.


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


class _FakePlatform:
    def __init__(self, value):
        self.value = value


def _messaging_event(platform_value, *, text="Pytanie techniczne", message_type="text",
                     chat_id="chat-1", thread_id=None, media_urls=None, command=None):
    platform = _FakePlatform(platform_value)
    source = SimpleNamespace(
        platform=platform,
        chat_id=chat_id,
        thread_id=thread_id,
        user_id="user-1",
        user_name="Tester",
    )
    return SimpleNamespace(
        source=source,
        text=text,
        message_type=SimpleNamespace(value=message_type),
        media_urls=list(media_urls or []),
        media_types=[],
        message_id="msg-1",
        get_command=lambda: command,
    )


def _observe_in_loop(plugin, event, gateway):
    async def scenario():
        return plugin.observe(event, gateway)
    return asyncio.run(scenario())


def test_telegram_observe_keeps_existing_agent_path(plugin):
    event = _messaging_event("telegram")
    gateway = SimpleNamespace(
        _is_user_authorized_for_source=lambda _source: pytest.fail(
            "Telegram must not enter Discord-only policy"
        )
    )
    assert _observe_in_loop(plugin, event, gateway) is None


def test_discord_unauthorized_falls_through_to_native_auth(plugin):
    event = _messaging_event("discord")
    gateway = SimpleNamespace(_is_user_authorized_for_source=lambda _source: False)
    assert _observe_in_loop(plugin, event, gateway) is None


def test_discord_voice_command_keeps_native_gateway_control(plugin):
    event = _messaging_event("discord", text="/voice status", command="voice")
    gateway = SimpleNamespace(
        _is_user_authorized_for_source=lambda _source: pytest.fail(
            "/voice must remain on the native Hermes command path"
        )
    )
    assert _observe_in_loop(plugin, event, gateway) is None


def test_discord_authorized_turn_is_intercepted_before_general_agent(plugin, monkeypatch):
    calls = []

    async def fake_turn(event, gateway, request_id):
        calls.append((event.text, gateway, request_id))

    monkeypatch.setattr(plugin, "discord_technical_turn", fake_turn)
    gateway = SimpleNamespace(_is_user_authorized_for_source=lambda _source: True)
    event = _messaging_event("discord", text="Jaki był SPN w Hatz?")

    async def scenario():
        result = plugin.observe(event, gateway)
        await asyncio.sleep(0)
        return result

    result = asyncio.run(scenario())
    assert result == {"action": "skip", "reason": "discord-technical-only"}
    assert len(calls) == 1
    assert calls[0][0] == "Jaki był SPN w Hatz?"
    assert calls[0][1] is gateway
    assert calls[0][2]


def test_discord_authorization_error_fails_closed(plugin):
    event = _messaging_event("discord")
    gateway = SimpleNamespace(
        _is_user_authorized_for_source=lambda _source: (_ for _ in ()).throw(
            RuntimeError("controlled auth seam failure")
        )
    )
    assert _observe_in_loop(plugin, event, gateway) == {
        "action": "skip",
        "reason": "discord-technical-policy-error",
    }


def test_discord_knowledge_payload_is_ecu_repair_hybrid(plugin):
    payload = plugin._knowledge_payload("Jak sprawdzić SPN 107 FMI 3?", "abc")
    assert payload["query"] == "Jak sprawdzić SPN 107 FMI 3?"
    assert payload["mode"] == "hybrid"
    assert payload["context"]["domain"] == "ecu-repair"
    assert payload["context"]["request_id"] == "discord_abc"
    assert payload["priority_class"] == "interactive"


def test_discord_technical_turn_uses_knowledge_and_formats_citations(plugin, monkeypatch):
    sent = []
    knowledge_calls = []
    platform = _FakePlatform("discord")

    class Adapter:
        def max_message_length_for_chat(self, _chat):
            return 2000

        async def send_typing(self, chat_id, metadata=None):
            sent.append(("typing", chat_id, metadata))
            return None

        async def send(self, chat_id, content, reply_to=None, metadata=None):
            sent.append(("text", chat_id, content, reply_to, metadata))
            return SimpleNamespace(success=True)

        def _should_auto_tts_for_chat(self, _chat):
            return False

    adapter = Adapter()
    gateway = SimpleNamespace(
        adapters={platform: adapter},
        _thread_metadata_for_source=lambda source, reply: {
            "thread_id": source.thread_id,
            "reply_anchor": reply,
        },
    )
    event = _messaging_event(
        "discord",
        text="Co było przyczyną SPN 107 FMI 3?",
        chat_id="technical",
        thread_id="thread-7",
    )
    # Use the exact platform object that keys gateway.adapters.
    event.source.platform = platform

    def knowledge(query, request_id):
        knowledge_calls.append((query, request_id))
        return {
            "answer": "Przyczyną był uszkodzony przewód.",
            "insufficient_context": False,
            "citations": [
                {
                    "ref": "S1",
                    "document_id": "kdoc_case",
                    "page": None,
                    "section": "Root cause",
                    "source": {"title": "CASE-0001 — przebieg diagnostyki"},
                },
                {
                    "ref": "S2",
                    "document_id": "kdoc_oem",
                    "page": 22,
                    "section": None,
                    "source": {"title": "Hatz trouble codes"},
                },
            ],
        }

    monkeypatch.setattr(plugin, "_knowledge_ask", knowledge)
    monkeypatch.setattr(plugin, "_SOURCE_BASE_URL", "http://ai-server:8080/control")

    asyncio.run(plugin.discord_technical_turn(event, gateway, "req1"))

    assert knowledge_calls == [("Co było przyczyną SPN 107 FMI 3?", "req1")]
    text_messages = [item for item in sent if item[0] == "text"]
    assert len(text_messages) == 1
    reply = text_messages[0][2]
    assert "Przyczyną był uszkodzony przewód." in reply
    assert "**Źródła:**" in reply
    assert "[S1] CASE-0001 — przebieg diagnostyki — Root cause" in reply
    assert "[S2] Hatz trouble codes — str. 22" in reply
    assert "/knowledge/documents/kdoc_case/original" in reply
    assert text_messages[0][3] == "msg-1"
    assert text_messages[0][4]["thread_id"] == "thread-7"


def test_discord_photo_is_blocked_without_knowledge_or_media_dispatch(plugin, monkeypatch):
    sent = []
    platform = _FakePlatform("discord")

    class Adapter:
        async def send(self, chat_id, content, reply_to=None, metadata=None):
            sent.append(content)
            return SimpleNamespace(success=True)

        def max_message_length_for_chat(self, _chat):
            return 2000

    gateway = SimpleNamespace(adapters={platform: Adapter()})
    event = _messaging_event(
        "discord",
        text="Co jest na zdjęciu?",
        message_type="photo",
        media_urls=["/tmp/photo.jpg"],
    )
    event.source.platform = platform
    monkeypatch.setattr(
        plugin,
        "_knowledge_ask",
        lambda *a, **k: pytest.fail("Discord photo must not reach Knowledge/LLM"),
    )

    asyncio.run(plugin.discord_technical_turn(event, gateway, "req-photo"))
    assert len(sent) == 1
    assert "Foto, wideo i pozostałe załączniki są wyłączone" in sent[0]


def test_discord_media_command_is_defense_in_depth_blocked(plugin, monkeypatch):
    event = _messaging_event("discord", text="/foto test", command="foto")
    # Set origin directly: the pre-dispatch policy normally prevents this command
    # from reaching plugin command dispatch at all.
    plugin._origin.set(
        SimpleNamespace(
            event=event,
            request_id="req-media",
            gateway=object(),
            task=SimpleNamespace(done=lambda: False),
        )
    )
    monkeypatch.setattr(
        plugin.asyncio,
        "create_subprocess_exec",
        lambda *a, **k: pytest.fail("Discord media must never spawn a worker"),
    )
    result = asyncio.run(plugin.media("foto", "test"))
    assert "Foto, wideo i pozostałe załączniki są wyłączone" in result


def test_discord_voice_turn_speaks_answer_but_not_source_urls(plugin, monkeypatch):
    sent = []
    spoken = []
    platform = _FakePlatform("discord")

    class Adapter:
        def max_message_length_for_chat(self, _chat):
            return 2000

        async def send_typing(self, chat_id, metadata=None):
            return None

        async def send(self, chat_id, content, reply_to=None, metadata=None):
            sent.append(content)
            return SimpleNamespace(success=True)

    gateway = SimpleNamespace(adapters={platform: Adapter()})
    event = _messaging_event(
        "discord",
        text="Jaki był kod błędu?",
        message_type="voice",
    )
    event.source.platform = platform

    monkeypatch.setattr(
        plugin,
        "_knowledge_ask",
        lambda *a, **k: {
            "answer": "Kod błędu to SPN 107 FMI 3.",
            "insufficient_context": False,
            "citations": [
                {
                    "ref": "S1",
                    "document_id": "kdoc_hatz",
                    "page": 22,
                    "section": None,
                    "source": {"title": "Hatz trouble codes"},
                }
            ],
        },
    )
    monkeypatch.setattr(plugin, "_SOURCE_BASE_URL", "http://ai-server/control")

    async def fake_voice(adapter, source, text, **kwargs):
        spoken.append(text)

    monkeypatch.setattr(plugin, "_play_voice_text", fake_voice)
    asyncio.run(plugin.discord_technical_turn(event, gateway, "req-voice"))

    assert len(sent) == 1 and "[S1]" in sent[0]
    assert spoken == ["Kod błędu to SPN 107 FMI 3."]
    assert "http://" not in spoken[0]


def test_discord_source_link_is_optional_and_points_to_original(plugin, monkeypatch):
    citation = {"document_id": "kdoc_test", "page": 7}
    monkeypatch.setattr(plugin, "_SOURCE_BASE_URL", "")
    assert plugin._source_link(citation) is None
    monkeypatch.setattr(plugin, "_SOURCE_BASE_URL", "https://ai.example/control")
    assert plugin._source_link(citation) == (
        "https://ai.example/control/api/v1/knowledge/documents/kdoc_test/original#page=7"
    )


def test_stage_f_contract_is_channel_specific_after_discord_technical_cutover():
    internal = (ROOT / "deploy/stage-f/internal_e2e.py").read_text()
    gate = (ROOT / "deploy/stage-f/autopilot/gate.py").read_text()
    runtime_builder = (ROOT / "deploy/runtime/build_release.sh").read_text()

    assert "Discord=Knowledge-only pre-dispatch RAG" in internal
    assert "general_agent_bypassed" in internal
    assert "for index, source in enumerate(telegram_sources)" in internal
    assert "len(artifacts) == 2" in internal
    assert "discord_technical_rag" in gate
    assert "len(evidence['media']) == 2" in gate
    assert "technical_discord = e.discord_technical_policy_active()" in gate
    assert "ai-platform-messaging-1.1.0" in runtime_builder


def test_discord_source_link_falls_back_to_canonical_github_document(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_SOURCE_BASE_URL", "")
    citation = {
        "document_id": "kdoc_hatz",
        "source": {
            "uri": (
                "github://autoklinika/EcuRepairService/"
                "sources/hatz/H50/originals/HATZ_05653402.pdf"
            )
        },
    }
    assert plugin._source_link(citation) == (
        "https://github.com/autoklinika/EcuRepairService/blob/main/"
        "sources/hatz/H50/originals/HATZ_05653402.pdf"
    )
