from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "patch_hermes_discord_queue_voice_test",
    ROOT / "tools/patch_hermes_discord_queue_voice.py",
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def _fixture_source():
    return (
        "from gateway.config import Platform\n"
        "import asyncio\n"
        "import json\n\n"
        "class TurnRunner:\n"
        + mod.BASE_VOICE_ACK
        + "\n    def _wire_turn_agent_callbacks(self, agent):\n"
        + mod.WIRE_ANCHOR
        + "        return agent\n"
    )


def _legacy_fixture(block: str):
    return (
        "from gateway.config import Platform\n"
        "import asyncio\n"
        "import json\n\n"
        "class TurnRunner:\n"
        + block
        + "\n    def _wire_turn_agent_callbacks(self, agent):\n"
        + mod.WIRE_ANCHOR
        + "        return agent\n"
    )


def test_patcher_inserts_queue_voice_v3_path_once():
    patched = mod.patch_text(_fixture_source())
    assert patched.count(mod.MARKER) == 1
    assert not any(marker in patched for marker in mod.LEGACY_MARKERS)
    assert "def ai_server_queue_voice_status_callback" in patched
    assert '"queued": "Serwer AI jest zajęty. Dodałem pytanie do kolejki."' in patched
    assert "play_in_voice_channel(guild_id, actual_path)" in patched
    assert "voice_mixer_active" not in patched.split(mod.MARKER, 1)[1].split("def _wire_turn_agent_callbacks", 1)[0]
    assert "_ai_server_queue_voice_callback" in patched
    assert mod.patch_text(patched) == patched


def test_patcher_upgrades_v2_to_v3_and_restores_normal_ack():
    legacy = _legacy_fixture(mod.LEGACY_V2)
    patched = mod.patch_text(legacy)
    assert mod.MARKER in patched
    assert "__ai_server_queue_status__" not in patched
    assert patched.count(mod.BASE_VOICE_ACK) == 1
    assert mod.check_text(legacy) == "upgradeable-v2"


def test_patcher_upgrades_v1_to_v3():
    legacy = _legacy_fixture(mod.LEGACY_V1)
    patched = mod.patch_text(legacy)
    assert mod.MARKER in patched
    assert not any(marker in patched for marker in mod.LEGACY_MARKERS)
    assert mod.check_text(legacy) == "upgradeable-v1"


def test_queue_status_uses_active_voice_connection_not_ack_guild():
    patched = mod.patch_text(_fixture_source())
    method = patched.split("def ai_server_queue_voice_status_callback", 1)[1]
    method = method.split("def _wire_turn_agent_callbacks", 1)[0]
    assert "_voice_text_channels" in method
    assert "is_in_voice_channel" in method
    assert "ctx._voice_ack_guild" not in method
    assert "play_ack_in_voice" not in method
    assert "play_in_voice_channel" in method


def test_normal_ack_callback_remains_original():
    patched = mod.patch_text(_fixture_source())
    assert patched.count(mod.BASE_VOICE_ACK) == 1
    assert "ctx._voice_ack_fired[0] = True" in mod.BASE_VOICE_ACK


def test_check_rejects_unknown_layout():
    assert mod.check_text("class TurnRunner:\n    pass\n").startswith("unsupported:")
