from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "patch_hermes_global_resource_queue_v4_test",
    ROOT / "tools/patch_hermes_global_resource_queue.py",
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def _base_source():
    return '''def _set_extra_header(api_kwargs, key, value):\n    pass\n\ndef build_api_request(agent, api_kwargs, api_call_count):\n    # Private to the in-process MoA facade; added after middleware/hooks/debug dumps so\n    return api_kwargs\n'''


def test_v4_injects_dedicated_discord_voice_callback():
    patched = mod.patch_text(_base_source())
    assert patched.count(mod.MARKER) == 1
    assert 'getattr(\n                        agent,\n                        "_ai_server_queue_voice_callback"' in patched
    assert "status_callback=_rq_status_callback" in patched
    assert "__ai_server_queue_status__" not in patched
    assert "_rq_voice_phrases" not in patched
    assert mod.patch_text(patched) == patched


def test_v4_preserves_telegram_and_discord_platforms():
    patched = mod.patch_text(_base_source())
    assert '_rq_platform in {"telegram", "discord"}' in patched
    assert '"telegram": "telegram-chat"' in patched
    assert '"discord": "discord-chat"' in patched
    assert "priority=50" in patched


def _legacy_source(marker: str):
    return _base_source().replace(
        mod.ANCHOR,
        f'''    # {marker}: old block\n    old = True\n''' + mod.ANCHOR,
    )


def test_v3_block_is_upgradeable_to_v4():
    legacy = _legacy_source("AI_SERVER_GLOBAL_RESOURCE_QUEUE_V3")
    assert mod.check_text(legacy) == "upgradeable-legacy"
    patched = mod.patch_text(legacy)
    assert mod.MARKER in patched
    assert "AI_SERVER_GLOBAL_RESOURCE_QUEUE_V3" not in patched


def test_v2_block_is_upgradeable_to_v4():
    legacy = _legacy_source("AI_SERVER_GLOBAL_RESOURCE_QUEUE_V2")
    assert mod.check_text(legacy) == "upgradeable-legacy"
    patched = mod.patch_text(legacy)
    assert mod.MARKER in patched
    assert "AI_SERVER_GLOBAL_RESOURCE_QUEUE_V2" not in patched


def test_v1_block_is_upgradeable_to_v4():
    legacy = _legacy_source("AI_SERVER_GLOBAL_RESOURCE_QUEUE_V1")
    assert mod.check_text(legacy) == "upgradeable-legacy"
    patched = mod.patch_text(legacy)
    assert mod.MARKER in patched
    assert "AI_SERVER_GLOBAL_RESOURCE_QUEUE_V1" not in patched


def test_check_rejects_unknown_layout():
    assert mod.check_text("def something_else():\n    pass\n").startswith("unsupported:")
