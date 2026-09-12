from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "patch_hermes_global_resource_queue_v3_test",
    ROOT / "tools/patch_hermes_global_resource_queue.py",
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def _base_source():
    return '''def _set_extra_header(api_kwargs, key, value):\n    pass\n\ndef build_api_request(agent, api_kwargs, api_call_count):\n    # Private to the in-process MoA facade; added after middleware/hooks/debug dumps so\n    return api_kwargs\n'''


def test_v3_injects_discord_voice_status_callback():
    patched = mod.patch_text(_base_source())
    assert patched.count(mod.MARKER) == 1
    assert '"__ai_server_queue_status__"' in patched
    assert '"queued": "Serwer AI jest zajęty. Dodałem pytanie do kolejki."' in patched
    assert '"active": "Zwolniły się zasoby. Zaczynam."' in patched
    assert "status_callback=_rq_status_callback" in patched
    assert mod.patch_text(patched) == patched


def test_v2_block_is_upgradeable_to_v3():
    legacy = _base_source().replace(
        mod.ANCHOR,
        '''    # AI_SERVER_GLOBAL_RESOURCE_QUEUE_V2: old block\n    old = True\n''' + mod.ANCHOR,
    )
    assert mod.check_text(legacy) == "upgradeable-legacy"
    patched = mod.patch_text(legacy)
    assert mod.MARKER in patched
    assert "AI_SERVER_GLOBAL_RESOURCE_QUEUE_V2" not in patched


def test_v1_block_is_upgradeable_to_v3():
    legacy = _base_source().replace(
        mod.ANCHOR,
        '''    # AI_SERVER_GLOBAL_RESOURCE_QUEUE_V1: old block\n    old = True\n''' + mod.ANCHOR,
    )
    assert mod.check_text(legacy) == "upgradeable-legacy"
    patched = mod.patch_text(legacy)
    assert mod.MARKER in patched
    assert "AI_SERVER_GLOBAL_RESOURCE_QUEUE_V1" not in patched
