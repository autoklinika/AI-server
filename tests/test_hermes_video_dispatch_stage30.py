from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "local_video" / "hermes_video_dispatch_stage30.py"
spec = importlib.util.spec_from_file_location("hermes_video_dispatch_stage30_test", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_stage30_parser_preserves_stage29_defaults():
    parsed = mod.parse_request_args(["robot", "macha"])
    assert parsed == {
        "hq": False,
        "duration_seconds": 2,
        "motion_level": "normal",
        "prompt": "robot macha",
    }


def test_stage30_parser_accepts_explicit_motion_profile():
    parsed = mod.parse_request_args(
        ["hq", "4s", "motion=subtle", "robot", "robi", "krok"]
    )
    assert parsed["hq"] is True
    assert parsed["duration_seconds"] == 4
    assert parsed["motion_level"] == "subtle"
    assert parsed["prompt"] == "robot robi krok"

    parsed = mod.parse_request_args(
        ["6s", "ruch=mocny", "robot", "biegnie"]
    )
    assert parsed["motion_level"] == "strong"


def test_normal_words_inside_prompt_are_not_eaten_as_control_tokens():
    parsed = mod.parse_request_args(
        ["4s", "strong", "red", "robot", "stands", "still"]
    )
    assert parsed["motion_level"] == "normal"
    assert parsed["prompt"].startswith("strong red robot")
