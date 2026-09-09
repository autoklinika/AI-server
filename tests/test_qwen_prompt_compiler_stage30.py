from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "local_video" / "qwen_prompt_compiler_stage30.py"
spec = importlib.util.spec_from_file_location("qwen_prompt_compiler_stage30_test", MODULE_PATH)
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


def test_i2v_prompt_is_fidelity_first_and_does_not_invent_camera(monkeypatch):
    captured = {}
    body = {
        "choices": [
            {
                "message": {
                    "content": (
                        "The robot takes one natural step forward. "
                        "Camera remains locked."
                    )
                }
            }
        ]
    }

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(body)

    monkeypatch.setattr(qwen.urllib.request, "urlopen", fake_urlopen)
    effective, used, reason, _elapsed = qwen.compile_prompt(
        "Robot robi jeden krok do przodu",
        duration_seconds=4,
        has_input_image=True,
        motion_level="normal",
    )
    assert used is True
    assert reason is None
    assert effective.startswith("The robot takes one natural step")
    messages = captured["payload"]["messages"]
    system = messages[0]["content"]
    user = messages[1]["content"]
    assert "starting image is authoritative" in system
    assert "Never invent orbit" in system
    assert "Default to a locked/static camera" in system
    assert "do not simultaneously demand that the background remain pixel-identical" in system
    assert "MOTION_LEVEL: normal" in user
    assert captured["payload"]["temperature"] == 0.05


def test_motion_levels_have_distinct_policies():
    subtle = qwen._i2v_system_prompt(4, "subtle")
    normal = qwen._i2v_system_prompt(4, "normal")
    strong = qwen._i2v_system_prompt(4, "strong")
    assert "SUBTLE" in subtle
    assert "NORMAL" in normal
    assert "STRONG" in strong
    assert qwen.normalize_motion_level("SUBTLE") == "subtle"


def test_t2v_delegates_to_stage29_unchanged(monkeypatch):
    expected = ("same prompt", True, None, 0.1)
    captured = {}

    def fake_compile(original_prompt, *, duration_seconds, has_input_image):
        captured.update(
            {
                "original_prompt": original_prompt,
                "duration_seconds": duration_seconds,
                "has_input_image": has_input_image,
            }
        )
        return expected

    monkeypatch.setattr(qwen.base, "compile_prompt", fake_compile)
    out = qwen.compile_prompt(
        "same prompt",
        duration_seconds=6,
        has_input_image=False,
        motion_level="strong",
    )
    assert out == expected
    assert captured == {
        "original_prompt": "same prompt",
        "duration_seconds": 6,
        "has_input_image": False,
    }
