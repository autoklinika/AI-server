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

SYSTEM_PROMPT = """You compile user requests for a local FLUX.2 Klein image generator/editor.
Return ONLY one JSON object with exactly two string fields: intent and prompt.
intent must be either generate or edit.

Rules:
- The user may write in Polish or another language. The prompt field must be concise natural English.
- Preserve all concrete requested details; do not add unrelated objects, text, logos, people, or scene changes.
- For generate intent, produce a standalone visual description suitable for text-to-image: subject, appearance, scene, composition, lighting/style, and important constraints.
- For edit intent with an attached image, produce a precise image-edit instruction: state exactly what changes and explicitly preserve everything else that the user asked to keep unchanged.
- If there is NO attached image and the request depends on modifying an existing image/object (for example: change its color, remove something, keep the rest unchanged, make this object different), set intent to edit. Do NOT invent the missing source image or subject.
- If there IS an attached image, intent must be edit.
- Do not output markdown, commentary, reasoning, or code fences.
"""


def _gateway_url() -> str:
    url = os.environ.get("HERMES_FOTO_QWEN_URL", QWEN_GATEWAY_URL_DEFAULT).strip()
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Foto prompt-compiler może używać wyłącznie lokalnego AI Gateway (loopback).")
    return url


def _timeout() -> int:
    try:
        value = int(os.environ.get("HERMES_FOTO_QWEN_TIMEOUT", QWEN_TIMEOUT_DEFAULT))
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


def _clean_json_text(text: str) -> str:
    text = re.sub(r"(?is)<think>.*?</think>", "", text or "").strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return match.group(0).strip() if match else text


def _request(original_prompt: str, has_input_image: bool, timeout: int) -> tuple[str, str]:
    model = os.environ.get("HERMES_FOTO_QWEN_MODEL", QWEN_MODEL_DEFAULT).strip() or QWEN_MODEL_DEFAULT
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"ATTACHED_IMAGE: {'yes' if has_input_image else 'no'}\n"
                        "USER REQUEST:\n<<<\n" + original_prompt + "\n>>>"
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
    content = _clean_json_text(_extract_content(body))
    if not content:
        raise RuntimeError("Qwen zwrócił pustą odpowiedź.")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Qwen nie zwrócił poprawnego JSON dla /foto.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Qwen zwrócił niepoprawny format promptu /foto.")
    intent = str(parsed.get("intent") or "").strip().casefold()
    prompt = str(parsed.get("prompt") or "").strip()
    if intent not in {"generate", "edit"}:
        raise RuntimeError(f"Qwen zwrócił niepoprawny intent: {intent or '<pusty>'}")
    if has_input_image:
        intent = "edit"
    if not prompt:
        raise RuntimeError("Qwen zwrócił pusty prompt obrazu.")
    if len(prompt) > 6000:
        raise RuntimeError("Qwen zwrócił nienaturalnie długi prompt obrazu.")
    return intent, prompt


def compile_prompt(original_prompt: str, has_input_image: bool) -> dict:
    started = time.monotonic()
    timeout = _timeout()
    try:
        intent, prompt = _request(original_prompt, has_input_image, timeout)
        return {
            "qwen_used": True,
            "intent": intent,
            "prompt": prompt,
            "failure_reason": None,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    except TimeoutError:
        reason = f"timeout Qwen po {timeout} s"
    except urllib.error.HTTPError as exc:
        reason = f"AI Gateway HTTP {exc.code}"
    except urllib.error.URLError as exc:
        reason = f"AI Gateway niedostępny: {getattr(exc, 'reason', exc)}"
    except Exception as exc:
        reason = str(exc).strip() or exc.__class__.__name__
    return {
        "qwen_used": False,
        "intent": "edit" if has_input_image else "unknown",
        "prompt": original_prompt,
        "failure_reason": reason,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
