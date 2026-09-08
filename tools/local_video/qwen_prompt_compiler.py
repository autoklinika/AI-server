#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

QWEN_GATEWAY_URL_DEFAULT = "http://127.0.0.1:11435/clients/hermes/v1/chat/completions"
QWEN_MODEL_DEFAULT = "qwen3.6:35b-hermes64k"
QWEN_TIMEOUT_DEFAULT = 90


def _system_prompt(duration_seconds: int, has_input_image: bool) -> str:
    mode = (
        "The user supplied a starting image. Treat that image as the exact first frame: preserve its subject identity, geometry, colors, composition and background unless the user explicitly requests a change. Describe the motion that should develop from that frame; do not invent a conflicting appearance."
        if has_input_image
        else
        "No starting image is supplied. Produce a complete standalone visual description for text-to-video."
    )
    return f"""You compile prompts for local LTX-2.3 video generation.
Return only the final English production prompt. No markdown, JSON, labels, commentary, or analysis.
Preserve every concrete instruction from the user's description and translate it to natural English when needed.
The requested clip duration is about {duration_seconds} seconds. Fit the action sequence naturally inside that duration; do not claim a different duration.
{mode}
Describe compactly: subject/scene when needed, exact temporal action sequence, camera framing or movement, lighting/style, and stability/continuity constraints.
Do not invent dialogue, text, logos, extra characters, or contradictory actions unless requested.
Avoid excessive adjectives and competing camera moves. Favor clear physical motion and stable identity/geometry.
If sound is requested or clearly implied, append a concise [SOUNDS]: section. Otherwise do not invent sound.
"""


def _gateway_url() -> str:
    url = os.environ.get("HERMES_VIDEO_QWEN_URL", QWEN_GATEWAY_URL_DEFAULT).strip()
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Qwen prompt-compiler może używać wyłącznie lokalnego AI Gateway (loopback).")
    return url


def _timeout() -> int:
    try:
        value = int(os.environ.get("HERMES_VIDEO_QWEN_TIMEOUT", QWEN_TIMEOUT_DEFAULT))
    except (TypeError, ValueError):
        value = QWEN_TIMEOUT_DEFAULT
    return max(5, min(value, 300))


def _extract_content(body: dict) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def _clean(text: str) -> str:
    text = re.sub(r"(?is)<think>.*?</think>", "", text or "").strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip() if len(lines) >= 2 else ""
    text = re.sub(r"^(?:prompt|final prompt)\s*:\s*", "", text, flags=re.IGNORECASE).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'\"', "'"}:
        text = text[1:-1].strip()
    return text


def _request(
    original_prompt: str,
    timeout: int,
    *,
    duration_seconds: int = 2,
    has_input_image: bool = False,
) -> str:
    model = os.environ.get("HERMES_VIDEO_QWEN_MODEL", QWEN_MODEL_DEFAULT).strip() or QWEN_MODEL_DEFAULT
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": _system_prompt(duration_seconds, has_input_image)},
                {
                    "role": "user",
                    "content": (
                        f"DURATION_SECONDS: {duration_seconds}\n"
                        f"STARTING_IMAGE: {'yes' if has_input_image else 'no'}\n"
                        "USER VIDEO DESCRIPTION:\n<<<\n" + original_prompt + "\n>>>"
                    ),
                },
            ],
            "stream": False,
            "temperature": 0.1,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        _gateway_url(),
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = json.load(response)
    if not isinstance(body, dict):
        raise RuntimeError("AI Gateway zwrócił niepoprawny format odpowiedzi Qwen.")
    return _clean(_extract_content(body))


def compile_prompt(
    original_prompt: str,
    *,
    duration_seconds: int = 2,
    has_input_image: bool = False,
) -> tuple[str, bool, str | None, float]:
    """Return effective_prompt, qwen_used, failure_reason, elapsed_seconds.

    Failure is intentionally non-fatal. The caller must visibly notify the originating
    chat before using the returned original prompt; silent fallback is forbidden.
    """
    started = time.monotonic()
    timeout = _timeout()
    try:
        compiled = _request(
            original_prompt,
            timeout,
            duration_seconds=duration_seconds,
            has_input_image=has_input_image,
        )
        elapsed = time.monotonic() - started
        if not compiled:
            return original_prompt, False, "Qwen zwrócił pusty prompt.", elapsed
        if len(compiled) > 8000:
            return original_prompt, False, "Qwen zwrócił nienaturalnie długi prompt.", elapsed
        return compiled, True, None, elapsed
    except TimeoutError:
        return original_prompt, False, f"timeout Qwen po {timeout} s", time.monotonic() - started
    except urllib.error.HTTPError as exc:
        return original_prompt, False, f"AI Gateway HTTP {exc.code}", time.monotonic() - started
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return original_prompt, False, f"AI Gateway niedostępny: {reason}", time.monotonic() - started
    except Exception as exc:
        return original_prompt, False, str(exc).strip() or exc.__class__.__name__, time.monotonic() - started


def fallback_notice(reason: str | None) -> str:
    clean = " ".join((reason or "nieznany błąd Qwen").split())[:300]
    return (
        "⚠️ Qwen został pominięty — używam oryginalnego opisu do LTX.\n"
        f"Powód: {clean}"
    )
