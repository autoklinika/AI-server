#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path

MARKER = "STAGE29_WIDEO_MEDIA_ENV"
STAGE26_ARGS = "STAGE26_WIDEO_QUICK_ARGS"
STAGE26_ROUTE = "STAGE26_WIDEO_ROUTE_ENV"
STAGE28_FOTO = "STAGE28_FOTO_MEDIA_ENV"
CURRENT_RETURN = "return True, await self._hm_run_exec_quick_command(command, exec_cmd), command"


class PatchError(RuntimeError):
    pass


def _return_match(text: str):
    matches = list(
        re.finditer(
            rf"^(?P<indent>[ \t]+){re.escape(CURRENT_RETURN)}$",
            text,
            re.MULTILINE,
        )
    )
    if len(matches) != 1:
        raise PatchError(f"expected one modern quick-command return, found {len(matches)}")
    match = matches[0]
    window = text[max(0, match.start() - 7000):match.start()]
    if 'if qtype == "exec":' not in window:
        raise PatchError("quick-command return not inside type:exec block")
    if STAGE26_ARGS not in window or STAGE26_ROUTE not in window:
        raise PatchError("Stage26 args/route bridge must already be installed before Stage29")
    if STAGE28_FOTO not in text:
        raise PatchError("Stage28 /foto media bridge must already be installed before Stage29")
    return match


def _block(indent: str) -> str:
    return (
        f'{indent}# {MARKER}: pass the exact current-message image path to deterministic /wideo.\n'
        f'{indent}if command == "wideo":\n'
        f'{indent}    from gateway.run import _event_media_is_image as _stage29_media_is_image\n'
        f'{indent}    _stage29_image_paths = [\n'
        f'{indent}        str(_path)\n'
        f'{indent}        for _idx, _path in enumerate(getattr(event, "media_urls", None) or [])\n'
        f'{indent}        if _stage29_media_is_image(event, _idx)\n'
        f'{indent}    ]\n'
        f'{indent}    if _stage29_image_paths:\n'
        f'{indent}        exec_cmd = (\n'
        f'{indent}            "HERMES_VIDEO_INPUT_IMAGE="\n'
        f'{indent}            + _stage26_shlex.quote(_stage29_image_paths[0])\n'
        f'{indent}            + " " + exec_cmd\n'
        f'{indent}        )\n'
    )


def patch_text(text: str) -> str:
    count = text.count(MARKER)
    if count > 1:
        raise PatchError("duplicate Stage29 wideo media marker")
    if count == 1:
        compile(text, "gateway/run_inbound.py", "exec")
        return text
    match = _return_match(text)
    patched = text[:match.start()] + _block(match.group("indent")) + text[match.start():]
    if patched.count(MARKER) != 1:
        raise PatchError("internal error: Stage29 marker not unique")
    compile(patched, "gateway/run_inbound.py", "exec")
    return patched


def check_text(text: str) -> str:
    if text.count(MARKER) > 1:
        return "unsupported:duplicate-marker"
    if text.count(MARKER) == 1:
        try:
            compile(text, "gateway/run_inbound.py", "exec")
        except SyntaxError as exc:
            return f"unsupported:{exc}"
        return "patched"
    try:
        patch_text(text)
    except (PatchError, SyntaxError) as exc:
        return f"unsupported:{exc}"
    return "patchable"


def atomic_write(path: Path, text: str) -> None:
    stat = path.stat()
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".stage29.", dir=str(path.parent), text=True)
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
    parser = argparse.ArgumentParser(description="Patch modern Hermes /wideo with exact current-turn image path")
    parser.add_argument("path", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        text = args.path.read_text(encoding="utf-8")
        if args.check:
            state = check_text(text)
            print(state)
            return 0 if state in {"patchable", "patched"} else 2
        patched = patch_text(text)
        if patched == text:
            print("already patched")
            return 0
        atomic_write(args.path, patched)
        print("patched")
        return 0
    except (OSError, PatchError, SyntaxError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
