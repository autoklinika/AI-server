from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "local_video" / "qwen_prompt_compiler.py"
spec = importlib.util.spec_from_file_location("qwen_prompt_compiler_stage29_test", MODULE_PATH)
assert spec and spec.loader
qwen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qwen)


class FakeResponse:
    def __init__(self, body: dict):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, *args, **kwargs):
        return json.dumps(self.body).encode("utf-8")


def test_request_tells_qwen_requested_duration_and_start_image(monkeypatch):
    captured = {}
    body = {"choices": [{"message": {"content": "The red robot waves while preserving the supplied first frame."}}]}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(body)

    monkeypatch.setattr(qwen.urllib.request, "urlopen", fake_urlopen)
    effective, used, reason, _elapsed = qwen.compile_prompt(
        "Robot macha do kamery",
        duration_seconds=6,
        has_input_image=True,
    )
    assert used is True
    assert reason is None
    assert effective.startswith("The red robot")
    messages = captured["payload"]["messages"]
    assert "about 6 seconds" in messages[0]["content"]
    assert "exact first frame" in messages[0]["content"]
    assert "DURATION_SECONDS: 6" in messages[1]["content"]
    assert "STARTING_IMAGE: yes" in messages[1]["content"]


def test_default_stage27_compatibility_remains_two_seconds(monkeypatch):
    captured = {}
    body = {"choices": [{"message": {"content": "A robot waves."}}]}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(body)

    monkeypatch.setattr(qwen.urllib.request, "urlopen", fake_urlopen)
    _effective, used, reason, _elapsed = qwen.compile_prompt("robot macha")
    assert used is True and reason is None
    system = captured["payload"]["messages"][0]["content"]
    assert "about 2 seconds" in system
