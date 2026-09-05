#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER = "STAGE26_WIDEO_QUICK_ARGS"

# The pinned Hermes 0.21.0 gateway has one exec quick-command dispatch block.
# We intentionally patch only that gateway path; CLI/TUI are outside Stage-26 scope.
PATTERN = re.compile(
    r'(?P<indent>^[ \t]+)exec_cmd = qcmd\.get\("command", ""\)\n'
    r'(?P=indent)if exec_cmd:\n'
    r'(?P=indent)    try:\n',
    re.MULTILINE,
)

INSERT = (
    '{indent}exec_cmd = qcmd.get("command", "")\n'
    '{indent}if exec_cmd:\n'
    '{indent}    try:\n'
    '{indent}        # {marker}: forward the complete slash-command argument string\n'
    '{indent}        # as ONE shell-quoted argv item to the local dispatcher.\n'
    '{indent}        import shlex as _stage26_shlex\n'
    '{indent}        _stage26_user_args = event.get_command_args().strip()\n'
    '{indent}        if _stage26_user_args:\n'
    '{indent}            exec_cmd = f"{{exec_cmd}} {{_stage26_shlex.quote(_stage26_user_args)}}"\n'
)


class PatchError(RuntimeError):
    pass


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    matches = list(PATTERN.finditer(text))
    if len(matches) != 1:
        raise PatchError(
            f"expected exactly one Hermes gateway exec quick-command block, found {len(matches)}"
        )
    match = matches[0]
    indent = match.group("indent")
    replacement = INSERT.format(indent=indent, marker=MARKER)
    return text[: match.start()] + replacement + text[match.end() :]


def check_text(text: str) -> str:
    if MARKER in text:
        return "patched"
    matches = list(PATTERN.finditer(text))
    if len(matches) == 1:
        return "patchable"
    return f"unsupported:{len(matches)}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Patch pinned Hermes gateway exec quick_commands to forward user args")
    p.add_argument("path", type=Path, help="path to Hermes gateway/run.py")
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
        args.path.write_text(patched, encoding="utf-8")
        print("patched")
        return 0
    except (OSError, PatchError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
