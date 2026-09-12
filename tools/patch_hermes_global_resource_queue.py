#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path


MARKER = "AI_SERVER_GLOBAL_RESOURCE_QUEUE_V2"
LEGACY_MARKER = "AI_SERVER_GLOBAL_RESOURCE_QUEUE_V1"
LEGACY_BLOCK_START = "    # AI_SERVER_GLOBAL_RESOURCE_QUEUE_V1:"
ANCHOR = (
    "    # Private to the in-process MoA facade; added after middleware/hooks/debug dumps so"
)
EXPECTED_BUILD = "def build_api_request("
EXPECTED_HEADER_HELPER = "def _set_extra_header("


class PatchError(RuntimeError):
    pass


def _block() -> str:
    return '''    # AI_SERVER_GLOBAL_RESOURCE_QUEUE_V2: reserve the global local-AI slot
    # for interactive Hermes turns on Telegram and Discord. Session ContextVars
    # are authoritative on the concurrent gateway; process-global HERMES_SESSION_*
    # values are not used.
    _rq_platform = ""
    try:
        from gateway.session_context import get_session_env as _rq_get_session_env
        _rq_platform = str(
            _rq_get_session_env("HERMES_SESSION_PLATFORM", "") or ""
        ).strip().lower()
        _rq_chat = str(
            _rq_get_session_env("HERMES_SESSION_CHAT_ID", "") or ""
        ).strip()
        _rq_thread = str(
            _rq_get_session_env("HERMES_SESSION_THREAD_ID", "") or ""
        ).strip()
        if _rq_platform in {"telegram", "discord"} and _rq_chat:
            import importlib.util as _rq_importlib
            import os as _rq_os
            import sys as _rq_sys

            _rq_name = "_ai_server_resource_queue"
            _rq_mod = _rq_sys.modules.get(_rq_name)
            if _rq_mod is None:
                _rq_path = _rq_os.environ.get(
                    "HERMES_RESOURCE_HELPER",
                    "/usr/local/libexec/ai-server/hermes_resource_queue.py",
                )
                _rq_spec = _rq_importlib.spec_from_file_location(_rq_name, _rq_path)
                if _rq_spec is None or _rq_spec.loader is None:
                    raise RuntimeError("global resource helper unavailable")
                _rq_mod = _rq_importlib.module_from_spec(_rq_spec)
                _rq_sys.modules[_rq_name] = _rq_mod
                _rq_spec.loader.exec_module(_rq_mod)

            if _rq_mod.should_manage_base_url(
                str(getattr(agent, "base_url", "") or "")
            ):
                _rq_target = _rq_platform + ":" + _rq_chat
                if _rq_thread:
                    _rq_target += ":" + _rq_thread
                _rq_source = {
                    "telegram": "telegram-chat",
                    "discord": "discord-chat",
                }[_rq_platform]

                # One user-facing queue transition per incoming turn is enough.
                # Tool-loop follow-up calls still use the global scheduler, but
                # remain silent instead of sending repetitive wait/start notices.
                try:
                    _rq_first_call = int(api_call_count or 0) <= 1
                except (TypeError, ValueError):
                    _rq_first_call = True
                _rq_queue_message = (
                    "⏳ Serwer AI jest teraz zajęty. Twoje zapytanie czeka w kolejce. "
                    "Powiadomię Cię, gdy rozpocznie się przetwarzanie."
                    if _rq_first_call
                    else None
                )
                _rq_start_message = (
                    "▶️ Zwolniły się zasoby. Rozpoczynam Twoje zapytanie."
                    if _rq_first_call
                    else None
                )
                _rq_lease = _rq_mod.acquire_resource(
                    target=_rq_target,
                    source=_rq_source,
                    priority=50,
                    queue_message=_rq_queue_message,
                    start_message=_rq_start_message,
                )
                _set_extra_header(
                    api_kwargs,
                    "X-AI-Resource-Lease",
                    _rq_lease.lease_id,
                )
                _set_extra_header(
                    api_kwargs,
                    "X-AI-Resource-Lease-Release",
                    "1",
                )
    except Exception as _rq_exc:
        # Fail open to the existing AI Gateway scheduler. Queue UX must never
        # make an otherwise valid Hermes request unusable.
        logger.warning(
            "Global resource queue unavailable for %s request: %s",
            _rq_platform or "unknown-platform",
            _rq_exc,
        )

'''


def _validate_layout(text: str) -> None:
    if EXPECTED_BUILD not in text or EXPECTED_HEADER_HELPER not in text:
        raise PatchError("unsupported Hermes turn_api_request layout")
    if text.count(ANCHOR) != 1:
        raise PatchError(
            f"expected one insertion anchor, found {text.count(ANCHOR)}"
        )


def patch_text(text: str) -> str:
    if text.count(MARKER) > 1:
        raise PatchError("duplicate global resource queue v2 marker")
    if text.count(LEGACY_MARKER) > 1:
        raise PatchError("duplicate global resource queue v1 marker")
    if MARKER in text and LEGACY_MARKER in text:
        raise PatchError("mixed v1/v2 global resource queue markers")
    if MARKER in text:
        compile(text, "agent/turn_api_request.py", "exec")
        return text

    _validate_layout(text)
    if LEGACY_MARKER in text:
        start = text.find(LEGACY_BLOCK_START)
        anchor = text.find(ANCHOR, start)
        if start < 0 or anchor < 0:
            raise PatchError("legacy v1 queue block boundaries not found")
        patched = text[:start] + _block() + text[anchor:]
    else:
        patched = text.replace(ANCHOR, _block() + ANCHOR, 1)

    if patched.count(MARKER) != 1 or LEGACY_MARKER in patched:
        raise PatchError("v2 marker migration failed")
    compile(patched, "agent/turn_api_request.py", "exec")
    return patched


def check_text(text: str) -> str:
    had_legacy = LEGACY_MARKER in text and MARKER not in text
    try:
        patched = patch_text(text)
    except (PatchError, SyntaxError) as exc:
        return f"unsupported:{exc}"
    if patched == text:
        return "patched"
    return "upgradeable-v1" if had_legacy else "patchable"


def atomic_write(path: Path, text: str) -> None:
    stat = path.stat()
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".resource.",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, stat.st_mode)
        try:
            os.chown(tmp_name, stat.st_uid, stat.st_gid)
        except PermissionError:
            pass
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        text = args.path.read_text(encoding="utf-8")
        if args.check:
            state = check_text(text)
            print(state)
            return 0 if state in {"patched", "patchable", "upgradeable-v1"} else 2

        patched = patch_text(text)
        if patched == text:
            print("already patched")
            return 0
        atomic_write(args.path, patched)
        print("patched v2")
        return 0
    except (OSError, PatchError, SyntaxError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
