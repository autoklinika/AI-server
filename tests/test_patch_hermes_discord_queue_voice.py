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
    return "from gateway.config import Platform\n\nclass TurnRunner:\n" + mod.OLD


def test_patcher_inserts_queue_voice_path_once():
    patched = mod.patch_text(_fixture_source())
    assert patched.count(mod.MARKER) == 1
    assert 'tool_name == "__ai_server_queue_status__"' in patched
    assert 'phrase=phrase' in patched
    assert mod.patch_text(patched) == patched


def test_queue_status_does_not_consume_normal_ack_flag():
    patched = mod.patch_text(_fixture_source())
    queue_branch = patched.split('if tool_name == "__ai_server_queue_status__":', 1)[1]
    queue_branch = queue_branch.split('if ctx._voice_ack_fired[0]', 1)[0]
    assert "ctx._voice_ack_fired[0] = True" not in queue_branch


def test_check_rejects_unknown_layout():
    assert mod.check_text("class TurnRunner:\n    pass\n").startswith("unsupported:")
