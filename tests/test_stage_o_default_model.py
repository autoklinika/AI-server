from pathlib import Path

from ai_bridge.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
MODEL = "qwen3.8:27b-p4-64k-gpu"


def test_qwen38_is_platform_default_model() -> None:
    assert Settings(_env_file=None).ollama_model == MODEL


def test_release_manifest_uses_qwen38_default() -> None:
    text = (ROOT / "deploy/runtime/build_release.sh").read_text(encoding="utf-8")
    assert f"  llm_model: {MODEL}" in text


def test_stage_o_preload_is_candidate_and_rollback_aware() -> None:
    text = (ROOT / "deploy/stage-o/autopilot/gate.py").read_text(encoding="utf-8")
    assert 'DEFAULT_LLM_MODEL = "qwen3.8:27b-p4-64k-gpu"' in text
    assert "configure_preload_model(model)" in text
    assert "restore_preload_baseline(baseline)" in text
    assert '"preload_unit": OLLAMA_PRELOAD_UNIT.read_text' in text
