from pathlib import Path

from ai_bridge.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
MODEL = "qwen3.8:27b-p4-64k-gpu-p511"


def test_qwen38_is_platform_default_model() -> None:
    assert Settings(_env_file=None).ollama_model == MODEL


def test_release_manifest_uses_qwen38_default() -> None:
    text = (ROOT / "deploy/runtime/build_release.sh").read_text(encoding="utf-8")
    assert f"  llm_model: {MODEL}" in text
    assert "provider_model_config_version: qwen38-p511-automotive-gpu-20261002-v1" in text
    assert "llm_adapter: automotive-specialization-v1" in text
    assert "46f38a1d4a4c26ce7800a4e05be8cbcb23da8b8f460e6f7faa8a73d577defdcb" in text
    assert "bb4966fa3d8a5a71a7e21b159235cc5e00f0282ff6c50ce6c1c41eca2dbba8a7" in text


def test_stage_o_preload_is_candidate_and_rollback_aware() -> None:
    text = (ROOT / "deploy/stage-o/autopilot/gate.py").read_text(encoding="utf-8")
    assert 'DEFAULT_LLM_MODEL = "qwen3.8:27b-p4-64k-gpu-p511"' in text
    assert "configure_preload_model(model)" in text
    assert "verify_default_ollama_adapter(DEFAULT_LLM_MODEL)" in text
    assert "DEFAULT_LLM_ADAPTER_RUNTIME_SHA256" in text
    assert "restore_preload_baseline(baseline)" in text
    assert '"preload_unit": OLLAMA_PRELOAD_UNIT.read_text' in text
