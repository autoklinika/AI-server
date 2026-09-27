#!/usr/bin/env python3
"""Internal smoke for installed Discord technical-only policy."""
from __future__ import annotations
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from urllib.request import urlopen

HERMES = Path("/srv/ai-data/hermes")
PLUGIN = Path(
    os.environ.get(
        "AI_PLATFORM_DISCORD_PLUGIN_PATH",
        str(HERMES / "plugins/ai-platform-messaging/__init__.py"),
    )
)
HERMES_SOURCE = HERMES / "hermes-agent"
PLATFORM = "http://127.0.0.1:11435/api/v1"


def load_plugin():
    spec = importlib.util.spec_from_file_location("discord_technical_live_plugin", PLUGIN)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load installed plugin")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def jobs():
    with urlopen(PLATFORM + "/jobs", timeout=15) as response:
        return json.load(response)["jobs"]


class Registration:
    def __init__(self):
        self.hooks, self.middleware, self.commands = {}, {}, {}
    def register_hook(self, name, callback):
        self.hooks[name] = callback
    def register_middleware(self, name, callback):
        self.middleware[name] = callback
    def register_command(self, name, callback, **metadata):
        self.commands[name] = (callback, metadata)


async def wait_tasks(plugin, timeout=180):
    deadline = time.monotonic() + timeout
    while plugin._discord_tasks:
        if time.monotonic() >= deadline:
            raise RuntimeError("Discord technical task timeout")
        await asyncio.sleep(0.1)


async def main():
    sys.path.insert(0, str(HERMES_SOURCE))
    from gateway.config import Platform
    from gateway.platforms.base import MessageEvent, MessageType
    from gateway.session import SessionSource

    plugin = load_plugin()
    reg = Registration()
    plugin.register(reg)
    assert reg.hooks.get("pre_gateway_dispatch") is plugin.observe
    assert reg.middleware.get("llm_execution") is plugin.execute
    assert {"foto", "wideo"} <= set(reg.commands)

    sent, spoken = [], []

    class Adapter:
        def max_message_length_for_chat(self, _chat):
            return 2000
        async def send_typing(self, *_args, **_kwargs):
            return None
        async def send(self, chat_id, content, reply_to=None, metadata=None):
            sent.append(str(content))
            return SimpleNamespace(success=True)
        def _should_auto_tts_for_chat(self, _chat):
            return False

    gateway = SimpleNamespace(
        adapters={Platform.DISCORD: Adapter()},
        _is_user_authorized_for_source=lambda _source: True,
        _thread_metadata_for_source=lambda source, reply: {
            "thread_id": source.thread_id, "reply_anchor": reply,
        },
    )

    telegram = SessionSource(
        platform=Platform.TELEGRAM, chat_id="synthetic-telegram", user_id="synthetic"
    )
    assert plugin.observe(MessageEvent(text="telegram pass", source=telegram), gateway) is None

    discord = SessionSource(
        platform=Platform.DISCORD, chat_id="synthetic-discord",
        thread_id="9001", user_id="synthetic",
    )
    assert plugin._PLATFORM_TURN_URL.endswith("/api/v1/conversation/turn")
    conversation_id = plugin._conversation_id(discord)
    assert conversation_id.startswith("conv_discord_")
    payload = plugin._technical_payload("test", "synthetic", discord)
    assert payload["conversation_id"] == conversation_id
    assert payload["context"]["session_id"] == conversation_id
    assert payload["client_id"] == "discord"

    before = {item["job_id"] for item in jobs()}
    text_event = MessageEvent(
        text="Jaki procesor jest w sterowniku Scania S6?",
        source=discord, message_id="synthetic-1",
    )
    assert plugin.observe(text_event, gateway) == {
        "action": "skip", "reason": "discord-technical-only",
    }
    await wait_tasks(plugin)
    text_reply = "\n".join(sent)
    assert "MPC555LF8MZP40" in text_reply
    assert "**Źródła:**" in text_reply and "[S" in text_reply

    new_jobs = [item for item in jobs() if item["job_id"] not in before]
    assert any(
        item.get("domain") == "ecu-repair"
        and item.get("capability") == "structured-generation"
        and item.get("state") == "completed"
        for item in new_jobs
    ), new_jobs
    assert not any(item.get("capability") == "chat" for item in new_jobs), new_jobs

    before_general = {item["job_id"] for item in jobs()}
    general_event = MessageEvent(
        text="Jaka jest stolica Francji?",
        source=discord,
        message_id="synthetic-general",
    )
    assert plugin.observe(general_event, gateway)["action"] == "skip"
    await wait_tasks(plugin)
    assert "Brak wystarczającej wiedzy" in sent[-1]
    assert {item["job_id"] for item in jobs()} == before_general

    before_media = {item["job_id"] for item in jobs()}
    photo = MessageEvent(
        text="Co jest na zdjęciu?", source=discord, message_type=MessageType.PHOTO,
        media_urls=["/tmp/synthetic-never-read.jpg"], media_types=["image/jpeg"],
        message_id="synthetic-2",
    )
    assert plugin.observe(photo, gateway)["action"] == "skip"
    await wait_tasks(plugin)
    assert "Foto, wideo i pozostałe załączniki są wyłączone" in sent[-1]
    assert {item["job_id"] for item in jobs()} == before_media

    help_event = MessageEvent(
        text="/help", source=discord, message_type=MessageType.COMMAND,
        message_id="synthetic-3",
    )
    assert plugin.observe(help_event, gateway)["action"] == "skip"
    await wait_tasks(plugin)
    assert "technicznym kanałem AI Platform" in sent[-1]

    voice_cmd = MessageEvent(
        text="/voice status", source=discord, message_type=MessageType.COMMAND,
        message_id="synthetic-4",
    )
    assert plugin.observe(voice_cmd, gateway) is None

    original_voice = plugin._play_voice_text
    async def capture_voice(_adapter, _source, text, **_kwargs):
        spoken.append(str(text))
    plugin._play_voice_text = capture_voice
    try:
        voice = MessageEvent(
            text="Jaki SPN był przy naprawie Hatz?", source=discord,
            message_type=MessageType.VOICE, message_id="synthetic-5",
        )
        assert plugin.observe(voice, gateway)["action"] == "skip"
        await wait_tasks(plugin)
    finally:
        plugin._play_voice_text = original_voice
    assert spoken and "http://" not in spoken[-1] and "https://" not in spoken[-1]

    with tempfile.TemporaryDirectory(prefix="discord-policy-tts-") as directory:
        paths = await plugin._tts_artifact("Test technicznej odpowiedzi głosowej.", directory)
        assert paths and all(p.is_file() and p.stat().st_size > 0 for p in paths)

    print(json.dumps({
        "status": "PASS",
        "telegram_passthrough": True,
        "discord_general_agent_bypassed": True,
        "discord_knowledge_rag": True,
        "discord_conversation_layer": True,
        "scania_s6_quality": True,
        "discord_out_of_domain_blocked": True,
        "discord_citations": True,
        "discord_media_blocked": True,
        "discord_voice_command_passthrough": True,
        "discord_voice_rag": True,
        "tts": True,
        "new_job_capabilities": sorted({str(x.get("capability")) for x in new_jobs}),
    }, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
