from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "deploy/stage-p5/runtime"
BUILDER = RUNTIME / "build_qwen38_p511_runtime.sh"
PATCHER = RUNTIME / "patch_qwen35_lora_outproj.py"

SOURCE_SHA = "46f38a1d4a4c26ce7800a4e05be8cbcb23da8b8f460e6f7faa8a73d577defdcb"
RUNTIME_SHA = "bb4966fa3d8a5a71a7e21b159235cc5e00f0282ff6c50ce6c1c41eca2dbba8a7"
LLAMA_SHA = "34af94cd9ab277632e27caeec2d41de2fd091b31"
MODEL = "qwen3.8:27b-p4-64k-gpu-p511"


def test_runtime_builder_is_pinned_and_fail_closed() -> None:
    text = BUILDER.read_text(encoding="utf-8")
    for required in (
        SOURCE_SHA,
        RUNTIME_SHA,
        LLAMA_SHA,
        MODEL,
        "TRAINING_INTEGRITY_PASS_QUALITY_PENDING",
        "PENDING_FUTURE_INDEPENDENT_EVALUATION",
        "P511_LORA_PERMUTATION_EQUIVALENCE=PASS",
        "ollama show --modelfile",
        "P511_RUNTIME=PASS",
    ):
        assert required in text


def test_runtime_builder_does_not_merge_lora_into_base() -> None:
    text = BUILDER.read_text(encoding="utf-8")
    assert "convert_lora_to_gguf.py" in text
    assert "ADAPTER $IMMUTABLE_GGUF" in text
    assert "merge_and_unload" not in text
    assert "merge_adapter" not in text


def test_qwen35_lora_patch_preserves_low_rank_factorization() -> None:
    text = PATCHER.read_text(encoding="utf-8")
    assert 'if hasattr(data_torch, "get_lora_A_B"):' in text
    assert "data_torch = data_torch[:, col_perm]" in text
    assert "A LoRA weight W = B @ A" in text
    assert "unexpected Qwen3.5 out_proj source block count" in text


def test_runtime_artifact_is_not_committed() -> None:
    tracked = {
        path.as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() == ".gguf"
    }
    assert tracked == set()
