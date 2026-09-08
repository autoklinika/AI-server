from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_VIDEO = ROOT / "tools" / "local_video"
sys.path.insert(0, str(LOCAL_VIDEO))
MODULE_PATH = LOCAL_VIDEO / "hermes_video_dispatch_stage29.py"
spec = importlib.util.spec_from_file_location("hermes_video_dispatch_stage29_test", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_parser_keeps_backward_compatible_two_second_default():
    out = mod.parse_request_args(["robot macha do kamery"])
    assert out == {"hq": False, "duration_seconds": 2, "prompt": "robot macha do kamery"}


def test_parser_accepts_hq_and_duration_in_both_prefix_orders():
    a = mod.parse_request_args(["hq 4s robot macha"])
    b = mod.parse_request_args(["4s hq robot macha"])
    assert a == b == {"hq": True, "duration_seconds": 4, "prompt": "robot macha"}


def test_parser_accepts_polish_seconds_and_rejects_too_long():
    assert mod.parse_request_args(["6sek robot"])["duration_seconds"] == 6
    try:
        mod.parse_request_args(["7s robot"])
    except mod.base.DispatchError as exc:
        assert "1–6" in str(exc)
    else:
        raise AssertionError("7-second render must be rejected")


def test_input_image_requires_absolute_existing_image(tmp_path):
    image = tmp_path / "first.png"
    image.write_bytes(b"png")
    assert mod._input_image({"HERMES_VIDEO_INPUT_IMAGE": str(image)}) == image.resolve()


def _write_request(tmp_path: Path, *, input_image: str | None = None, duration: int = 4) -> Path:
    job = tmp_path / "job"
    job.mkdir()
    request = {
        "schema": 2,
        "job_id": "test",
        "target": "telegram:123",
        "hq": True,
        "duration_seconds": duration,
        "frames": duration * 24 + 1,
        "fps": 24,
        "prompt": "robot macha",
        "input_image": input_image,
        "mode": "i2v" if input_image else "t2v",
        "render_strategy": "single_tiled_vae",
    }
    path = job / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


def test_worker_passes_full_duration_hq_and_input_image_to_single_ltx_render(monkeypatch, tmp_path):
    input_image = tmp_path / "input.png"
    input_image.write_bytes(b"png")
    request_path = _write_request(tmp_path, input_image=str(input_image), duration=4)
    output = tmp_path / "out.mp4"
    output.write_bytes(b"mp4")
    fake_ltx = tmp_path / "generate-video-ltx23"
    fake_ltx.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_ltx.chmod(0o755)
    monkeypatch.setenv("HERMES_LTX_VIDEO_BIN", str(fake_ltx))

    monkeypatch.setattr(
        mod.qwen,
        "compile_prompt",
        lambda original, **kwargs: ("A red robot waves from the supplied first frame.", True, None, 0.2),
    )

    seen = {}

    class Render:
        returncode = 0
        stdout = str(output) + "\n"

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return Render()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.base, "_extract_mp4", lambda stdout: output)
    sent = []
    monkeypatch.setattr(mod.base, "_send", lambda target, msg: sent.append((target, msg)))

    assert mod.run_worker(request_path) == 0
    cmd = seen["cmd"]
    assert cmd[:3] == [str(fake_ltx), "--duration-seconds", "4"]
    assert "--upscale-2x" in cmd
    assert cmd[cmd.index("--input-image") + 1] == str(input_image)
    assert cmd[cmd.index("--prompt") + 1].startswith("A red robot")
    assert sent[-1] == ("telegram:123", f"MEDIA:{output}")

    result = json.loads((request_path.parent / "result.json").read_text(encoding="utf-8"))
    assert result["mode"] == "i2v"
    assert result["duration_seconds"] == 4
    assert result["frames"] == 97
    assert result["render_strategy"] == "single_tiled_vae"


def test_qwen_warning_delivery_failure_stops_before_ltx(monkeypatch, tmp_path):
    request_path = _write_request(tmp_path)
    monkeypatch.setattr(
        mod.qwen,
        "compile_prompt",
        lambda original, **kwargs: (original, False, "timeout", 90.0),
    )
    monkeypatch.setattr(mod.base, "_send", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    def must_not_render(*args, **kwargs):
        raise AssertionError("LTX must not start when fallback warning cannot be delivered")

    monkeypatch.setattr(mod.subprocess, "run", must_not_render)
    assert mod.run_worker(request_path) == 1
    result = json.loads((request_path.parent / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert "Nie wysłano ostrzeżenia" in result["error"]
