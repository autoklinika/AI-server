from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_VIDEO = ROOT / "tools" / "local_video"
if str(LOCAL_VIDEO) not in sys.path:
    sys.path.insert(0, str(LOCAL_VIDEO))

import hermes_video_dispatch_stage27 as stage27  # noqa: E402


def _make_request(tmp_path: Path, prompt: str = "robot macha") -> Path:
    job = tmp_path / "job"
    job.mkdir()
    request = job / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema": 1,
                "target": "telegram:5844876074",
                "hq": False,
                "prompt": prompt,
            }
        ),
        encoding="utf-8",
    )
    return request


def _make_fake_ltx(tmp_path: Path, mp4: Path) -> tuple[Path, Path]:
    args_log = tmp_path / "ltx.args"
    script = tmp_path / "fake-ltx"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$@\" > \"${STAGE27_LTX_ARGS:?}\"\n"
        "printf '%s\\n' \"${STAGE27_MP4:?}\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, args_log


def test_qwen_success_uses_compiled_prompt_without_warning(tmp_path: Path, monkeypatch):
    request = _make_request(tmp_path, "robot macha")
    mp4 = tmp_path / "video.mp4"
    mp4.write_bytes(b"fake video")
    ltx, args_log = _make_fake_ltx(tmp_path, mp4)

    monkeypatch.setenv("HERMES_LTX_VIDEO_BIN", str(ltx))
    monkeypatch.setenv("STAGE27_LTX_ARGS", str(args_log))
    monkeypatch.setenv("STAGE27_MP4", str(mp4))
    monkeypatch.setattr(
        stage27.qwen,
        "compile_prompt",
        lambda original: ("A red robot waves at the camera.", True, None, 1.25),
    )
    sent = []
    monkeypatch.setattr(stage27.base, "_send", lambda target, message: sent.append((target, message)))

    assert stage27.run_worker(request) == 0
    assert sent == [("telegram:5844876074", f"MEDIA:{mp4}")]
    assert args_log.read_text(encoding="utf-8").splitlines() == [
        "--prompt",
        "A red robot waves at the camera.",
    ]
    result = json.loads((request.parent / "result.json").read_text(encoding="utf-8"))
    assert result["qwen_used"] is True
    assert result["original_prompt"] == "robot macha"
    assert result["effective_prompt"] == "A red robot waves at the camera."
    assert result["qwen_failure_reason"] is None


def test_qwen_fallback_warns_before_render_and_uses_original(tmp_path: Path, monkeypatch):
    request = _make_request(tmp_path, "robot macha")
    mp4 = tmp_path / "video.mp4"
    mp4.write_bytes(b"fake video")
    ltx, args_log = _make_fake_ltx(tmp_path, mp4)

    monkeypatch.setenv("HERMES_LTX_VIDEO_BIN", str(ltx))
    monkeypatch.setenv("STAGE27_LTX_ARGS", str(args_log))
    monkeypatch.setenv("STAGE27_MP4", str(mp4))
    monkeypatch.setattr(
        stage27.qwen,
        "compile_prompt",
        lambda original: (original, False, "timeout Qwen po 90 s", 90.0),
    )
    sent = []
    monkeypatch.setattr(stage27.base, "_send", lambda target, message: sent.append((target, message)))

    assert stage27.run_worker(request) == 0
    assert len(sent) == 2
    assert "Qwen został pominięty" in sent[0][1]
    assert sent[1] == ("telegram:5844876074", f"MEDIA:{mp4}")
    assert args_log.read_text(encoding="utf-8").splitlines() == ["--prompt", "robot macha"]
    result = json.loads((request.parent / "result.json").read_text(encoding="utf-8"))
    assert result["qwen_used"] is False
    assert result["qwen_failure_reason"] == "timeout Qwen po 90 s"


def test_failed_fallback_warning_aborts_before_ltx(tmp_path: Path, monkeypatch):
    request = _make_request(tmp_path, "robot macha")
    marker = tmp_path / "ltx-ran"
    script = tmp_path / "fake-ltx"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"touch {marker}\n"
        "exit 99\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("HERMES_LTX_VIDEO_BIN", str(script))
    monkeypatch.setattr(
        stage27.qwen,
        "compile_prompt",
        lambda original: (original, False, "AI Gateway niedostępny", 0.1),
    )

    def fail_send(target, message):
        raise RuntimeError("telegram send failed")

    monkeypatch.setattr(stage27.base, "_send", fail_send)
    assert stage27.run_worker(request) == 1
    assert not marker.exists()
    result = json.loads((request.parent / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["qwen_used"] is False
    assert "Nie wysłano ostrzeżenia" in result["error"]
