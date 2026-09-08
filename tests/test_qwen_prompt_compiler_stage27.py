from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "local_video" / "qwen_prompt_compiler.py"


def _load():
    spec = importlib.util.spec_from_file_location("qwen_prompt_compiler_stage27_test", MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


qwen = _load()


class FakeResponse:
    def __init__(self, body: dict):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, *args, **kwargs):
        return json.dumps(self.body).encode("utf-8")


def test_success_returns_clean_english_prompt(monkeypatch):
    body = {
        "choices": [
            {"message": {"content": "Prompt: A small red robot waves its right hand at the camera."}}
        ]
    }
    monkeypatch.setattr(qwen.urllib.request, "urlopen", lambda request, timeout: FakeResponse(body))
    effective, used, reason, elapsed = qwen.compile_prompt("Mały czerwony robot macha do kamery")
    assert used is True
    assert reason is None
    assert effective == "A small red robot waves its right hand at the camera."
    assert elapsed >= 0


def test_empty_response_falls_back_to_original(monkeypatch):
    body = {"choices": [{"message": {"content": ""}}]}
    monkeypatch.setattr(qwen.urllib.request, "urlopen", lambda request, timeout: FakeResponse(body))
    original = "robot macha"
    effective, used, reason, _elapsed = qwen.compile_prompt(original)
    assert used is False
    assert effective == original
    assert "pusty" in reason


def test_timeout_falls_back_and_reports_reason(monkeypatch):
    def timeout(*args, **kwargs):
        raise TimeoutError("slow")

    monkeypatch.setattr(qwen.urllib.request, "urlopen", timeout)
    monkeypatch.setenv("HERMES_VIDEO_QWEN_TIMEOUT", "7")
    effective, used, reason, _elapsed = qwen.compile_prompt("robot")
    assert used is False
    assert effective == "robot"
    assert reason == "timeout Qwen po 7 s"


def test_remote_gateway_is_refused(monkeypatch):
    monkeypatch.setenv("HERMES_VIDEO_QWEN_URL", "https://example.com/v1/chat/completions")
    effective, used, reason, _elapsed = qwen.compile_prompt("robot")
    assert used is False
    assert effective == "robot"
    assert "wyłącznie lokalnego AI Gateway" in reason


def test_fallback_notice_is_explicit():
    text = qwen.fallback_notice("timeout Qwen po 90 s")
    assert "Qwen został pominięty" in text
    assert "oryginalnego opisu" in text
    assert "timeout Qwen po 90 s" in text
