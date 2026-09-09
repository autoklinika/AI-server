#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import qwen_prompt_compiler as base
except ImportError:
    base_path = Path(__file__).with_name("qwen_prompt_compiler.py")
    spec = importlib.util.spec_from_file_location("qwen_prompt_compiler_stage29", base_path)
    if spec is None or spec.loader is None:
        raise
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)


MOTION_LEVELS = {"subtle", "normal", "strong"}
DEFAULT_MOTION_LEVEL = "normal"


def normalize_motion_level(value: str | None) -> str:
    level = (value or DEFAULT_MOTION_LEVEL).strip().casefold()
    if level not in MOTION_LEVELS:
        raise ValueError(
            "motion_level must be one of: subtle, normal, strong"
        )
    return level


def _motion_instruction(level: str) -> str:
    if level == "subtle":
        return (
            "Motion level is SUBTLE: use only small, natural subject motion with low amplitude. "
            "Prefer micro-movements, one small gesture, or a gentle posture change. "
            "Keep the camera locked unless camera movement is explicitly requested."
        )
    if level == "strong":
        return (
            "Motion level is STRONG: a larger subject movement is allowed, but preserve identity, "
            "proportions, rigid geometry, colors, scene layout and temporal continuity. "
            "Use one main action rather than several competing actions."
        )
    return (
        "Motion level is NORMAL: use one clear natural subject action with moderate amplitude. "
        "Do not add secondary actions that the user did not request."
    )


def _i2v_system_prompt(duration_seconds: int, motion_level: str) -> str:
    motion = _motion_instruction(motion_level)
    return f"""You compile prompts for local LTX-2.3 IMAGE-TO-VIDEO generation.
Return only the final English production prompt. No markdown, JSON, labels, commentary, or analysis.

The starting image is authoritative for all appearance facts. Preserve the visible subject identity, face, rigid-object geometry, proportions, colors, materials, composition, lighting identity and background scene unless the user explicitly requests a change.
Do not re-invent or embellish the subject's appearance. Do not invent details that are not requested.
Describe primarily WHAT CHANGES AFTER THE FIRST FRAME: the requested motion, timing and temporal continuity.

The requested clip duration is about {duration_seconds} seconds. Fit the requested action naturally inside that duration.
{motion}

CAMERA POLICY:
- Default to a locked/static camera.
- Never invent orbit, pan, tilt, dolly, zoom, focal-length change or reframing.
- Add camera movement only when the user's description explicitly requests it.
- If camera movement is explicitly requested, use at most one simple camera move and describe natural parallax; do not simultaneously demand that the background remain pixel-identical.

FIDELITY POLICY:
- Preserve subject identity and recognizable details throughout.
- Preserve rigid geometry and proportions; no morphing, melting, stretching or redesign.
- Preserve the original color palette and material appearance.
- Preserve the background scene and scene topology; no new scenery or objects.
- No new characters, logos, text or props unless requested.
- Avoid appearance changes caused only by motion.
- Prefer one primary action. Do not silently add walking, turning, waving, facial expression changes or camera motion.
- For a face, preserve facial structure and identity; use only the requested expression/head motion.
- For a rigid object or robot, preserve panel layout, joints, silhouette and mechanical structure.

PROMPT STYLE:
Use concise cinematic English. State the requested motion first, then only the minimum continuity/camera constraints needed.
Avoid excessive adjectives, conflicting instructions and impossible combinations.
If sound is requested or clearly implied, append a concise [SOUNDS]: section. Otherwise do not invent sound.
"""


def _request_i2v(
    original_prompt: str,
    timeout: int,
    *,
    duration_seconds: int,
    motion_level: str,
) -> str:
    model = (
        os.environ.get("HERMES_VIDEO_QWEN_MODEL", base.QWEN_MODEL_DEFAULT).strip()
        or base.QWEN_MODEL_DEFAULT
    )
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": _i2v_system_prompt(duration_seconds, motion_level),
                },
                {
                    "role": "user",
                    "content": (
                        f"DURATION_SECONDS: {duration_seconds}\n"
                        "STARTING_IMAGE: yes\n"
                        f"MOTION_LEVEL: {motion_level}\n"
                        "USER VIDEO DESCRIPTION:\n<<<\n"
                        + original_prompt
                        + "\n>>>"
                    ),
                },
            ],
            "stream": False,
            "temperature": 0.05,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        base._gateway_url(),
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = json.load(response)
    if not isinstance(body, dict):
        raise RuntimeError("AI Gateway zwrócił niepoprawny format odpowiedzi Qwen.")
    return base._clean(base._extract_content(body))


def compile_prompt(
    original_prompt: str,
    *,
    duration_seconds: int = 2,
    has_input_image: bool = False,
    motion_level: str = DEFAULT_MOTION_LEVEL,
) -> tuple[str, bool, str | None, float]:
    """Return effective_prompt, qwen_used, failure_reason, elapsed_seconds.

    T2V intentionally delegates to the production Stage29 compiler unchanged.
    Stage30 modifies only I2V prompting.
    """
    if not has_input_image:
        return base.compile_prompt(
            original_prompt,
            duration_seconds=duration_seconds,
            has_input_image=False,
        )

    started = time.monotonic()
    timeout = base._timeout()
    try:
        level = normalize_motion_level(motion_level)
        compiled = _request_i2v(
            original_prompt,
            timeout,
            duration_seconds=duration_seconds,
            motion_level=level,
        )
        elapsed = time.monotonic() - started
        if not compiled:
            return original_prompt, False, "Qwen zwrócił pusty prompt.", elapsed
        if len(compiled) > 8000:
            return (
                original_prompt,
                False,
                "Qwen zwrócił nienaturalnie długi prompt.",
                elapsed,
            )
        return compiled, True, None, elapsed
    except TimeoutError:
        return (
            original_prompt,
            False,
            f"timeout Qwen po {timeout} s",
            time.monotonic() - started,
        )
    except urllib.error.HTTPError as exc:
        return (
            original_prompt,
            False,
            f"AI Gateway HTTP {exc.code}",
            time.monotonic() - started,
        )
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return (
            original_prompt,
            False,
            f"AI Gateway niedostępny: {reason}",
            time.monotonic() - started,
        )
    except Exception as exc:
        return (
            original_prompt,
            False,
            str(exc).strip() or exc.__class__.__name__,
            time.monotonic() - started,
        )


def fallback_notice(reason: str | None) -> str:
    return base.fallback_notice(reason)
