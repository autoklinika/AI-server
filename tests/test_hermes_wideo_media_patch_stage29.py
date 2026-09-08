from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "patch_hermes_wideo_quick_media_stage29.py"
spec = importlib.util.spec_from_file_location("patch_wideo_stage29_test", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FIXTURE = '''async def demo(self, event, source, command, qcmd):
    qtype = qcmd.get("type")
    if qtype == "exec":
        exec_cmd = qcmd.get("command", "")
        if not exec_cmd:
            return True, "missing", command
        # STAGE26_WIDEO_QUICK_ARGS
        import shlex as _stage26_shlex
        _stage26_user_args = event.get_command_args().strip()
        if _stage26_user_args:
            exec_cmd = f"{exec_cmd} {_stage26_shlex.quote(_stage26_user_args)}"
        # STAGE26_WIDEO_ROUTE_ENV
        _stage26_platform = source.platform.value if source.platform else ""
        _stage26_chat_id = str(source.chat_id or "")
        _stage26_thread_id = str(source.thread_id or "")
        if _stage26_platform and _stage26_chat_id:
            _stage26_route_env = " ".join((
                "HERMES_SESSION_PLATFORM=" + _stage26_shlex.quote(_stage26_platform),
                "HERMES_SESSION_CHAT_ID=" + _stage26_shlex.quote(_stage26_chat_id),
                "HERMES_SESSION_THREAD_ID=" + _stage26_shlex.quote(_stage26_thread_id),
            ))
            exec_cmd = f"{_stage26_route_env} {exec_cmd}"
        # STAGE28_FOTO_MEDIA_ENV
        if command == "foto":
            pass
        return True, await self._hm_run_exec_quick_command(command, exec_cmd), command
'''


def test_patch_adds_exact_current_image_env_only_for_wideo():
    patched = mod.patch_text(FIXTURE)
    assert mod.MARKER in patched
    assert 'if command == "wideo":' in patched
    assert 'HERMES_VIDEO_INPUT_IMAGE=' in patched
    assert '_event_media_is_image' in patched
    assert patched.index(mod.MARKER) < patched.index(mod.CURRENT_RETURN)
    compile(patched, "fixture.py", "exec")


def test_patch_is_idempotent():
    once = mod.patch_text(FIXTURE)
    twice = mod.patch_text(once)
    assert once == twice
    assert twice.count(mod.MARKER) == 1


def test_patch_requires_existing_stage28_bridge():
    broken = FIXTURE.replace("STAGE28_FOTO_MEDIA_ENV", "REMOVED_STAGE28")
    assert mod.check_text(broken).startswith("unsupported:")
