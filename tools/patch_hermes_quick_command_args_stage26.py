#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

MARKER = "STAGE26_WIDEO_QUICK_ARGS"

# Hermes 0.21.x has existed in two relevant layouts:
# - legacy monolithic gateway/run.py
# - modular gateway/run_inbound.py (including 79445a4)
# Patch semantically and fail closed instead of hard-coding a line number.
CURRENT_RETURN = "return True, await self._hm_run_exec_quick_command(command, exec_cmd), command"
LEGACY_PATTERN = re.compile(
    r'(?P<indent>^[ \t]+)exec_cmd = qcmd\.get\("command", ""\)\n'
    r'(?P=indent)if exec_cmd:\n'
    r'(?P=indent)    try:\n',
    re.MULTILINE,
)


class PatchError(RuntimeError):
    pass


def _current_dispatch_patch(text: str) -> str | None:
    matches = list(
        re.finditer(
            rf"^(?P<indent>[ \t]+){re.escape(CURRENT_RETURN)}$",
            text,
            re.MULTILINE,
        )
    )
    if not matches:
        return None
    if len(matches) != 1:
        raise PatchError(f"expected one modern Hermes quick-command return, found {len(matches)}")

    match = matches[0]
    # Prove this return belongs to the type:exec quick-command block.
    window = text[max(0, match.start() - 900):match.start()]
    if 'if qtype == "exec":' not in window or 'exec_cmd = qcmd.get("command", "")' not in window:
        raise PatchError("modern quick-command return found outside expected type:exec block")

    indent = match.group("indent")
    insert = (
        f'{indent}# {MARKER}: pass the complete slash-command payload as ONE shell-quoted argv item.\n'
        f'{indent}# The local dispatcher reparses only the optional leading hq token.\n'
        f'{indent}import shlex as _stage26_shlex\n'
        f'{indent}_stage26_user_args = event.get_command_args().strip()\n'
        f'{indent}if _stage26_user_args:\n'
        f'{indent}    exec_cmd = f"{{exec_cmd}} {{_stage26_shlex.quote(_stage26_user_args)}}"\n'
    )
    return text[:match.start()] + insert + text[match.start():]


def _legacy_dispatch_patch(text: str) -> str | None:
    matches = list(LEGACY_PATTERN.finditer(text))
    if not matches:
        return None
    if len(matches) != 1:
        raise PatchError(f"expected one legacy Hermes quick-command block, found {len(matches)}")

    match = matches[0]
    indent = match.group("indent")
    replacement = (
        f'{indent}exec_cmd = qcmd.get("command", "")\n'
        f'{indent}if exec_cmd:\n'
        f'{indent}    try:\n'
        f'{indent}        # {MARKER}: forward the complete slash-command argument string\n'
        f'{indent}        # as ONE shell-quoted argv item to the local dispatcher.\n'
        f'{indent}        import shlex as _stage26_shlex\n'
        f'{indent}        _stage26_user_args = event.get_command_args().strip()\n'
        f'{indent}        if _stage26_user_args:\n'
        f'{indent}            exec_cmd = f"{{exec_cmd}} {{_stage26_shlex.quote(_stage26_user_args)}}"\n'
    )
    return text[:match.start()] + replacement + text[match.end():]


def patch_text(text: str) -> str:
    marker_count = text.count(MARKER)
    if marker_count:
        if marker_count != 1:
            raise PatchError("duplicate Stage26 quick-command marker")
        return text

    patched = _current_dispatch_patch(text)
    if patched is None:
        patched = _legacy_dispatch_patch(text)
    if patched is None:
        raise PatchError("no supported Hermes gateway exec quick-command dispatch layout found")

    if patched.count(MARKER) != 1:
        raise PatchError("internal error: Stage26 marker is not unique after patching")
    compile(patched, "hermes-gateway-dispatch.py", "exec")
    return patched


def check_text(text: str) -> str:
    marker_count = text.count(MARKER)
    if marker_count == 1:
        return "patched"
    if marker_count:
        return "unsupported:duplicate-marker"
    try:
        patched = patch_text(text)
    except PatchError as exc:
        return f"unsupported:{exc}"
    return "patchable" if patched != text else "patched"


def atomic_write(path: Path, text: str) -> None:
    stat = path.stat()
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".stage26.", dir=str(path.parent), text=True)
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
    p = argparse.ArgumentParser(description="Patch Hermes gateway exec quick_commands to forward /wideo args")
    p.add_argument("path", type=Path, help="Hermes gateway dispatch module (run_inbound.py or legacy run.py)")
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)

    try:
        text = args.path.read_text(encoding="utf-8")
        if args.check:
            state = check_text(text)
            print(state)
            return 0 if state in {"patched", "patchable"} else 2
        patched = patch_text(text)
        if patched == text:
            print("already patched")
            return 0
        atomic_write(args.path, patched)
        print("patched")
        return 0
    except (OSError, PatchError, SyntaxError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
