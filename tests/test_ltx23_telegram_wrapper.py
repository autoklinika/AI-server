from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools" / "local_video" / "generate-video-telegram"


def _fake_ltx(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "args.log"
    fake = tmp_path / "fake-ltx"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$@\" > \"${HERMES_LTX_TEST_ARGS:?}\"\n"
        "if [[ \" ${*} \" == *\" --upscale-2x \"* ]]; then\n"
        "  printf '%s\\n' '/srv/ai-data/hermes-media/video/test-hq.mp4'\n"
        "else\n"
        "  printf '%s\\n' '/srv/ai-data/hermes-media/video/test-standard.mp4'\n"
        "fi\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake, log


def _run(tmp_path: Path, *args: str) -> tuple[str, list[str]]:
    fake, log = _fake_ltx(tmp_path)
    env = os.environ.copy()
    env["HERMES_LTX_VIDEO_BIN"] = str(fake)
    env["HERMES_LTX_TEST_ARGS"] = str(log)
    proc = subprocess.run(
        ["bash", str(WRAPPER), *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip(), log.read_text(encoding="utf-8").splitlines()


def test_standard_routes_to_ltx_without_upscale(tmp_path: Path):
    stdout, args = _run(tmp_path, "--", "red robot waves")
    assert stdout == "/srv/ai-data/hermes-media/video/test-standard.mp4"
    assert "--upscale-2x" not in args
    assert args == ["--prompt", "red robot waves"]


def test_hq_flag_routes_to_ltx_with_upscale(tmp_path: Path):
    stdout, args = _run(tmp_path, "--hq", "--", "red robot waves")
    assert stdout == "/srv/ai-data/hermes-media/video/test-hq.mp4"
    assert args == ["--upscale-2x", "--prompt", "red robot waves"]


def test_hq_first_token_is_mode_switch(tmp_path: Path):
    stdout, args = _run(tmp_path, "hq", "red", "robot", "waves")
    assert stdout == "/srv/ai-data/hermes-media/video/test-hq.mp4"
    assert args == ["--upscale-2x", "--prompt", "red robot waves"]


def test_hq_first_token_is_case_insensitive(tmp_path: Path):
    stdout, args = _run(tmp_path, "Hq", "red", "robot", "waves")
    assert stdout == "/srv/ai-data/hermes-media/video/test-hq.mp4"
    assert args == ["--upscale-2x", "--prompt", "red robot waves"]


def test_hq_inside_prompt_is_not_mode_switch(tmp_path: Path):
    stdout, args = _run(tmp_path, "render", "hq", "logo")
    assert stdout == "/srv/ai-data/hermes-media/video/test-standard.mp4"
    assert args == ["--prompt", "render hq logo"]


def test_success_stdout_is_only_bare_absolute_mp4_path(tmp_path: Path):
    stdout, _ = _run(tmp_path, "--", "scene")
    assert stdout.startswith("/srv/ai-data/hermes-media/video/")
    assert stdout.endswith(".mp4")
    assert "\n" not in stdout
