from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PATH = ROOT / "tools" / "local_video" / "hermes_video_dispatch.py"
PATCH_PATH = ROOT / "tools" / "patch_hermes_quick_command_args_stage26.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dispatch = _load("hermes_video_dispatch_stage26", DISPATCH_PATH)
patcher = _load("hermes_quick_args_patcher_stage26", PATCH_PATH)


def test_parse_standard_and_hq_from_single_forwarded_argv():
    assert dispatch.parse_request_args(["robot waves at camera"]) == (False, "robot waves at camera")
    assert dispatch.parse_request_args(["hq robot waves at camera"]) == (True, "robot waves at camera")
    assert dispatch.parse_request_args(["Hq robot waves at camera"]) == (True, "robot waves at camera")


def test_parse_manual_multi_argv_and_reject_empty():
    assert dispatch.parse_request_args(["hq", "red", "robot"]) == (True, "red robot")
    with pytest.raises(dispatch.DispatchError, match="Użycie"):
        dispatch.parse_request_args([])
    with pytest.raises(dispatch.DispatchError, match="Użycie"):
        dispatch.parse_request_args(["hq"])


def test_routing_target_is_exact_chat_and_optional_thread():
    env = {"HERMES_SESSION_PLATFORM": "telegram", "HERMES_SESSION_CHAT_ID": "12345"}
    assert dispatch.routing_target(env) == "telegram:12345"
    env["HERMES_SESSION_THREAD_ID"] = "777"
    assert dispatch.routing_target(env) == "telegram:12345:777"
    with pytest.raises(dispatch.DispatchError, match="Brak kontekstu"):
        dispatch.routing_target({"HERMES_SESSION_PLATFORM": "telegram"})


def test_queue_job_captures_route_prompt_and_returns_immediate_ack(tmp_path: Path, monkeypatch):
    class FakeProc:
        pid = 4242

    seen = {}

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setenv("HERMES_VIDEO_JOB_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "5844")
    monkeypatch.setenv("HERMES_SESSION_THREAD_ID", "")
    monkeypatch.setattr(dispatch.subprocess, "Popen", fake_popen)

    reply = dispatch.queue_job(["hq red robot waves"])
    assert "HQ 1280×768" in reply
    assert "odesłany do tego czatu" in reply

    requests = list((tmp_path / "jobs").glob("*/request.json"))
    assert len(requests) == 1
    doc = json.loads(requests[0].read_text(encoding="utf-8"))
    assert doc["target"] == "telegram:5844"
    assert doc["hq"] is True
    assert doc["prompt"] == "red robot waves"
    assert seen["kwargs"]["start_new_session"] is True


def _make_fake_backend(tmp_path: Path, *, hq: bool):
    mp4 = tmp_path / ("hq.mp4" if hq else "standard.mp4")
    mp4.write_bytes(b"fake mp4 payload")

    ltx_log = tmp_path / "ltx.args"
    ltx = tmp_path / "fake-ltx"
    ltx.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$@\" > \"${HERMES_TEST_LTX_LOG:?}\"\n"
        "printf '%s\\n' \"${HERMES_TEST_MP4:?}\"\n",
        encoding="utf-8",
    )
    ltx.chmod(0o755)

    send_log = tmp_path / "send.args"
    hermes = tmp_path / "fake-hermes"
    hermes.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$@\" > \"${HERMES_TEST_SEND_LOG:?}\"\n",
        encoding="utf-8",
    )
    hermes.chmod(0o755)
    return mp4, ltx, ltx_log, hermes, send_log


@pytest.mark.parametrize("hq", [False, True])
def test_worker_renders_expected_mode_and_sends_native_media_to_origin_chat(tmp_path: Path, monkeypatch, hq: bool):
    mp4, ltx, ltx_log, hermes, send_log = _make_fake_backend(tmp_path, hq=hq)
    monkeypatch.setenv("HERMES_LTX_VIDEO_BIN", str(ltx))
    monkeypatch.setenv("HERMES_CLI_BIN", str(hermes))
    monkeypatch.setenv("HERMES_TEST_LTX_LOG", str(ltx_log))
    monkeypatch.setenv("HERMES_TEST_SEND_LOG", str(send_log))
    monkeypatch.setenv("HERMES_TEST_MP4", str(mp4))

    job = tmp_path / "job"
    job.mkdir()
    req = job / "request.json"
    req.write_text(
        json.dumps(
            {
                "schema": 1,
                "target": "telegram:5844876074",
                "hq": hq,
                "prompt": "red robot waves at camera",
            }
        ),
        encoding="utf-8",
    )

    assert dispatch.run_worker(req) == 0

    ltx_args = ltx_log.read_text(encoding="utf-8").splitlines()
    if hq:
        assert ltx_args == ["--upscale-2x", "--prompt", "red robot waves at camera"]
    else:
        assert ltx_args == ["--prompt", "red robot waves at camera"]

    send_args = send_log.read_text(encoding="utf-8").splitlines()
    assert send_args == [
        "send",
        "--to",
        "telegram:5844876074",
        f"MEDIA:{mp4}",
    ]
    result = json.loads((job / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["path"] == str(mp4)
    assert result["target"] == "telegram:5844876074"


def test_patcher_inserts_shell_quoted_argument_forwarding_once():
    original = '''async def handle(event, qcmd):
    exec_cmd = qcmd.get("command", "")
    if exec_cmd:
        try:
            # Sanitize env
            pass
        except Exception:
            pass
'''
    assert patcher.check_text(original) == "patchable"
    patched = patcher.patch_text(original)
    assert patcher.MARKER in patched
    assert "event.get_command_args().strip()" in patched
    assert "_stage26_shlex.quote(_stage26_user_args)" in patched
    assert patcher.patch_text(patched) == patched
    assert patcher.check_text(patched) == "patched"


def test_patcher_refuses_ambiguous_source():
    with pytest.raises(patcher.PatchError):
        patcher.patch_text("no compatible Hermes quick-command block here")
