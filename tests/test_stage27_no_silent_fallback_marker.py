from pathlib import Path


def test_stage27_source_contains_mandatory_visible_fallback_contract():
    root = Path(__file__).resolve().parents[1]
    dispatcher = (root / "tools/local_video/hermes_video_dispatch_stage27.py").read_text(encoding="utf-8")
    compiler = (root / "tools/local_video/qwen_prompt_compiler.py").read_text(encoding="utf-8")
    assert "Silent fallback is forbidden" in dispatcher
    assert "Qwen został pominięty" in compiler
