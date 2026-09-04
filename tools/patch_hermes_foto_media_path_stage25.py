#!/usr/bin/env python3
"""Safely patch pinned Hermes slash-skill dispatch for Stage 25 /foto media paths.

The pinned Hermes gateway/run.py contains more than one assignment of
``user_instruction = event.get_command_args().strip()``.  The Stage-25 bridge
must be inserted only at the assignment that feeds
``build_skill_invocation_message(cmd_key, user_instruction, ...)``.
"""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path

ANCHOR = "                    user_instruction = event.get_command_args().strip()\n"
PATCH_BEGIN = "# AI_SERVER_STAGE25_FOTO_MEDIA_PATH_BEGIN"
PATCH_END = "# AI_SERVER_STAGE25_FOTO_MEDIA_PATH_END"

SKILL_CALL_RE = re.compile(
    r"build_skill_invocation_message\(\s*cmd_key\s*,\s*user_instruction\b",
    re.DOTALL,
)

PATCH = '''                    user_instruction = event.get_command_args().strip()\n                    # AI_SERVER_STAGE25_FOTO_MEDIA_PATH_BEGIN\n                    # /foto image editing needs the exact cached path from THIS inbound\n                    # event. Inject it into the skill instruction before normal media\n                    # enrichment, then consume the image attachment so Qwen does not\n                    # waste a vision pass merely to route a deterministic local edit.\n                    if cmd_key == "/foto":\n                        _foto_image_paths = [\n                            str(_path)\n                            for _idx, _path in enumerate(getattr(event, "media_urls", None) or [])\n                            if _event_media_is_image(event, _idx)\n                        ]\n                        if _foto_image_paths:\n                            _foto_path = _foto_image_paths[0]\n                            user_instruction = (\n                                f"{user_instruction}\\n\\n"\n                                "[HERMES_FOTO_INPUT_IMAGE]\\n"\n                                f"path={_foto_path}\\n"\n                                "[/HERMES_FOTO_INPUT_IMAGE]"\n                            )\n                            event.media_urls = []\n                            event.media_types = []\n                            event.media_text_inlined = []\n                    # AI_SERVER_STAGE25_FOTO_MEDIA_PATH_END\n'''


def _anchor_positions(text: str) -> list[int]:
    positions: list[int] = []
    start = 0
    while True:
        pos = text.find(ANCHOR, start)
        if pos < 0:
            return positions
        positions.append(pos)
        start = pos + len(ANCHOR)


def find_skill_dispatch_anchor(text: str) -> int:
    """Return the unique anchor whose following block calls the skill builder.

    Each candidate is bounded by the next identical anchor, so a later skill
    call cannot accidentally make an earlier unrelated assignment match.
    """

    positions = _anchor_positions(text)
    candidates: list[int] = []

    for index, pos in enumerate(positions):
        block_end = positions[index + 1] if index + 1 < len(positions) else len(text)
        block = text[pos:block_end]
        if SKILL_CALL_RE.search(block):
            candidates.append(pos)

    if len(candidates) != 1:
        line_numbers = [text.count("\n", 0, pos) + 1 for pos in positions]
        candidate_lines = [text.count("\n", 0, pos) + 1 for pos in candidates]
        raise RuntimeError(
            "expected exactly one semantic slash-skill anchor feeding "
            "build_skill_invocation_message(cmd_key, user_instruction, ...); "
            f"raw anchors={len(positions)} at lines={line_numbers}, "
            f"semantic candidates={len(candidates)} at lines={candidate_lines}"
        )

    return candidates[0]


def build_patched_text(text: str) -> tuple[str, str]:
    has_begin = PATCH_BEGIN in text
    has_end = PATCH_END in text
    if has_begin or has_end:
        if has_begin and has_end and text.count(PATCH_BEGIN) == 1 and text.count(PATCH_END) == 1:
            return text, "already-patched"
        raise RuntimeError("partial or duplicate Stage25 Hermes patch marker found")

    pos = find_skill_dispatch_anchor(text)
    patched = text[:pos] + PATCH + text[pos + len(ANCHOR) :]

    if patched.count(PATCH_BEGIN) != 1 or patched.count(PATCH_END) != 1:
        raise RuntimeError("internal error: Stage25 patch markers are not unique after patching")

    # Validate the complete Python module before touching the production file.
    compile(patched, "gateway/run.py", "exec")
    return patched, "patched"


def atomic_write(path: Path, text: str) -> None:
    stat = path.stat()
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".stage25.", dir=str(path.parent), text=True)
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


def patch_file(path: Path, check_only: bool = False) -> str:
    original = path.read_text(encoding="utf-8")
    patched, state = build_patched_text(original)
    if state == "patched" and not check_only:
        atomic_write(path, patched)
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    try:
        state = patch_file(args.target, check_only=args.check_only)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    if state == "already-patched":
        print("INFO: Stage25 Hermes media-path patch already present and unique")
    elif args.check_only:
        print("PASS: unique semantic slash-skill patch point resolved; no file modified")
    else:
        print("PASS: patched semantic slash-skill dispatch for exact-current-turn /foto media path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
