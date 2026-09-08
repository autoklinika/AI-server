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


def test_long_durations_are_split_into_two_second_safe_segments():
    assert mod.segment_plan(1) == [1]
    assert mod.segment_plan(2) == [2]
    assert mod.segment_plan(3) == [2, 1]
    assert mod.segment_plan(4) == [2, 2]
    assert mod.segment_plan(5) == [2, 2, 1]
    assert mod.segment_plan(6) == [2, 2, 2]


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
    }
    path = job / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    return path


def test_worker_chains_four_seconds_as_two_i2v_safe_segments(monkeypatch, tmp_path):
    input_image = tmp_path / "input.png"
    input_image.write_bytes(b"png")
    request_path = _write_request(tmp_path, input_image=str(input_image), duration=4)
    fake_ltx = tmp_path / "generate-video-ltx23"
    fake_ltx.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_ltx.chmod(0o755)
    monkeypatch.setenv("HERMES_LTX_VIDEO_BIN", str(fake_ltx))

    monkeypatch.setattr(
        mod.qwen,
        "compile_prompt",
        lambda original, **kwargs: ("A red robot waves from the supplied first frame.", True, None, 0.2),
    )
    monkeypatch.setattr(mod, "_ffmpeg_bin", lambda: "/usr/bin/ffmpeg")

    calls = []
    seg1 = tmp_path / "seg1.mp4"
    seg2 = tmp_path / "seg2.mp4"
    seg1.write_bytes(b"mp4-1")
    seg2.write_bytes(b"mp4-2")

    def fake_segment(ltx, **kwargs):
        calls.append(kwargs.copy())
        return ([seg1, seg2][len(calls) - 1], 10.0)

    def fake_extract(mp4, dst):
        dst.write_bytes(b"frame")
        return dst

    final = tmp_path / "final.mp4"
    final.write_bytes(b"joined")
    monkeypatch.setattr(mod, "_run_ltx_segment", fake_segment)
    monkeypatch.setattr(mod, "_extract_last_frame", fake_extract)
    monkeypatch.setattr(mod, "_concat_segments", lambda segments, job_dir: final)
    sent = []
    monkeypatch.setattr(mod.base, "_send", lambda target, msg: sent.append((target, msg)))

    assert mod.run_worker(request_path) == 0
    assert [c["duration_seconds"] for c in calls] == [2, 2]
    assert calls[0]["input_image"] == str(input_image)
    assert calls[1]["input_image"].endswith("continuation-01.png")
    assert calls[0]["hq"] is True and calls[1]["hq"] is True
    assert "opening segment" in calls[0]["prompt"]
    assert "Continue naturally" in calls[1]["prompt"]
    assert sent[-1] == ("telegram:123", f"MEDIA:{final}")

    result = json.loads((request_path.parent / "result.json").read_text(encoding="utf-8"))
    assert result["mode"] == "i2v"
    assert result["duration_seconds"] == 4
    assert result["frames"] == 97
    assert result["segment_plan"] == [2, 2]
    assert result["segment_count"] == 2
    assert result["render_strategy"] == "chained_2s_i2v"


def test_two_seconds_stays_single_segment(monkeypatch, tmp_path):
    request_path = _write_request(tmp_path, duration=2)
    fake_ltx = tmp_path / "generate-video-ltx23"
    fake_ltx.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_ltx.chmod(0o755)
    monkeypatch.setenv("HERMES_LTX_VIDEO_BIN", str(fake_ltx))
    monkeypatch.setattr(mod.qwen, "compile_prompt", lambda original, **kwargs: ("robot waves", True, None, 0.1))
    output = tmp_path / "out.mp4"
    output.write_bytes(b"mp4")
    calls = []

    def fake_single(ltx, **kwargs):
        calls.append(kwargs.copy())
        return output, 5.0

    monkeypatch.setattr(mod, "_run_ltx_segment", fake_single)
    monkeypatch.setattr(mod.base, "_send", lambda *args, **kwargs: None)
    assert mod.run_worker(request_path) == 0
    assert len(calls) == 1
    assert calls[0]["duration_seconds"] == 2
    result = json.loads((request_path.parent / "result.json").read_text(encoding="utf-8"))
    assert result["render_strategy"] == "single"


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

    monkeypatch.setattr(mod, "_run_ltx_segment", must_not_render)
    assert mod.run_worker(request_path) == 1
    result = json.loads((request_path.parent / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert "Nie wysłano ostrzeżenia" in result["error"]
