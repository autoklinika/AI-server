from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/patch_hermes_foto_quick_media_stage28.py"
spec = importlib.util.spec_from_file_location("patch_foto_stage28", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


FIXTURE = '''async def demo(self, event, source, command, qcmd):
    qtype = qcmd.get("type")
    if qtype == "exec":
        exec_cmd = qcmd.get("command", "")
        if not exec_cmd:
            return True, "missing", command
        # STAGE26_WIDEO_QUICK_ARGS: pass the complete slash-command payload as ONE shell-quoted argv item.
        import shlex as _stage26_shlex
        _stage26_user_args = event.get_command_args().strip()
        if _stage26_user_args:
            exec_cmd = f"{exec_cmd} {_stage26_shlex.quote(_stage26_user_args)}"
        # STAGE26_WIDEO_ROUTE_ENV: bind the exact invoking chat to THIS quick-command process.
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
        return True, await self._hm_run_exec_quick_command(command, exec_cmd), command
'''


def test_patch_injects_exact_current_image_env():
    patched = mod.patch_text(FIXTURE)
    assert mod.MARKER in patched
    assert 'if command == "foto":' in patched
    assert 'getattr(event, "media_urls", None)' in patched
    assert '_event_media_is_image' in patched
    assert 'HERMES_FOTO_INPUT_IMAGE=' in patched
    assert patched.index(mod.MARKER) < patched.index(mod.CURRENT_RETURN)
    compile(patched, "fixture.py", "exec")


def test_patch_is_idempotent():
    once = mod.patch_text(FIXTURE)
    twice = mod.patch_text(once)
    assert once == twice
    assert twice.count(mod.MARKER) == 1


def test_check_requires_stage26_route_bridge():
    broken = FIXTURE.replace("STAGE26_WIDEO_ROUTE_ENV", "REMOVED_ROUTE_MARKER")
    state = mod.check_text(broken)
    assert state.startswith("unsupported:")


def test_check_reports_patchable_then_patched():
    assert mod.check_text(FIXTURE) == "patchable"
    assert mod.check_text(mod.patch_text(FIXTURE)) == "patched"
