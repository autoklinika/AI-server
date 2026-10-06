import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTO = ROOT / "deploy/stage-p5/training/automotive_v1"

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module

def read_jsonl(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def test_dataset_contract_and_validation():
    validator = load_module("p511_validator", AUTO / "validate_automotive_specialization_v1.py")
    out = validator.validate()
    assert out["status"] == "PASS"
    assert out["new_records"] == 183
    assert out["replay_records"] == 61
    assert out["combined_records"] == 244
    assert out["replay_fraction"] == 0.25
    assert out["diagnostic_knowledge_records"] == 28

def test_knowledge_examples_are_one_per_curated_record():
    knowledge = load_module("p511_knowledge", AUTO / "knowledge_examples.py")
    assert len(knowledge.EXAMPLES) == 28
    assert all(len(item) == 4 and all(isinstance(x, str) and x.strip() for x in item) for item in knowledge.EXAMPLES)

def test_replay_uses_only_train_sources():
    rows = read_jsonl(AUTO / "automotive_specialization_v1_replay_train.jsonl")
    replay = [r for r in rows if r["metadata"].get("p511_replay")]
    assert len(replay) == 61
    origins = {r["metadata"]["p511_origin"] for r in replay}
    assert origins == {
        "electronics_foundation_train_v1.jsonl",
        "electronics_foundation_v2_train.jsonl",
        "electronics_foundation_v3_train.jsonl",
    }
    assert all(r["metadata"]["split"] == "train" for r in replay)

def test_training_schedule_and_no_truncation_contract():
    text = (AUTO / "train_automotive_specialization_v1.py").read_text()
    assert "EXPECTED_RECORDS = 244" in text
    assert "EXPECTED_OPTIMIZER_STEPS = 64" in text
    assert "(loss / group_size).backward()" in text
    assert "refusing assistant-target truncation" in text
    assert "TRAINING_INTEGRITY_PASS_QUALITY_PENDING" in text
    assert "PENDING_FUTURE_INDEPENDENT_EVALUATION" in text

def test_runner_has_fail_closed_gpu_watchdog_and_no_service_mutation():
    text = (AUTO / "run_automotive_specialization_v1.sh").read_text()
    for required in (
        "HSA_USE_SVM=0", "WAIT_REG_MEM", "MES ring buffer is full", "GPU reset",
        "GPUVM", "unexpected_kfd_owner", "P5_11_ADAPTER_VALIDATION=PASS",
        "resource_release_timeout", 'mv -Tf "$TMP_LINK" "$ADAPTER_ROOT/current"',
    ):
        assert required in text
    assert "systemctl stop" not in text
    assert "systemctl start" not in text
    assert "systemctl restart" not in text

def test_manifests_keep_quality_boundary_open():
    a = json.loads((AUTO / "automotive_specialization_v1.manifest.json").read_text())
    r = json.loads((AUTO / "automotive_specialization_v1_replay.manifest.json").read_text())
    assert a["protected_eval_material_used"] is False
    assert r["protected_eval_material_used"] is False
    assert a["quality_acceptance"] == "PENDING_FUTURE_INDEPENDENT_EVALUATION"
    assert r["quality_acceptance"] == "PENDING_FUTURE_INDEPENDENT_EVALUATION"
    assert r["parent_adapter"].endswith("/electronics-foundation-v3/current")


def test_quiesced_comfyui_is_resumed_on_training_exit():
    text = (AUTO / "run_automotive_specialization_v1.sh").read_text()
    assert 'QUIESCED_COMFYUI_PIDS=""' in text
    assert 'resume_quiesced_comfyui()' in text
    assert 'kill -CONT "$pid"' in text
    assert "trap resume_quiesced_comfyui EXIT" in text
