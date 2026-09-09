from pathlib import Path
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "global_resource_patcher",
    ROOT / "tools/patch_hermes_global_resource_queue.py",
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture() -> str:
    return '''def _set_extra_header(api_kwargs, key, value):
    api_kwargs[key] = value

def build_api_request(agent, api_kwargs):
    logger = type("L", (), {"warning": lambda *a, **k: None})()
    api_call_count = 1
    # Private to the in-process MoA facade; added after middleware/hooks/debug dumps so
    return api_kwargs
'''


def test_patch_is_idempotent_and_sets_releasing_lease_headers():
    original = fixture()
    assert mod.check_text(original) == "patchable"
    patched = mod.patch_text(original)
    assert patched.count(mod.MARKER) == 1
    assert "X-AI-Resource-Lease" in patched
    assert "X-AI-Resource-Lease-Release" in patched
    assert "telegram-chat" in patched
    assert "gateway.session_context" in patched
    assert 'HERMES_SESSION_CHAT_ID' in patched
    assert 'getattr(agent, "_chat_id"' not in patched
    assert "api_call_count" in patched
    assert mod.check_text(patched) == "patched"
    assert mod.patch_text(patched) == patched
    compile(patched, "fixture.py", "exec")


def test_patch_refuses_unknown_layout():
    with pytest.raises(mod.PatchError):
        mod.patch_text("def unrelated():\n    pass\n")
