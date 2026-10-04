from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "deploy/stage-p5/training/wvc_v1"
DATA = HERE / "data"

spec = importlib.util.spec_from_file_location("wvc_dataset", HERE / "dataset.py")
assert spec and spec.loader
wvc_dataset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wvc_dataset)

ALLOWED_CHANNELS = {
    "pm1_0_ug_m3", "pm2_5_ug_m3", "pm4_0_ug_m3", "pm10_0_ug_m3",
    "voc_index", "nox_index", "temperature_celsius", "humidity_percent",
}


def rows(split: str) -> list[dict]:
    return [json.loads(line) for line in (DATA / f"{split}.jsonl").read_text().splitlines()]


def test_wvc_dataset_gates_and_identity() -> None:
    result = wvc_dataset.validate(DATA)
    assert result["contamination"] == "PASS"
    assert result["non_wvc_elements"] == 0
    assert result["schema_current"] == "PASS"
    assert result["leakage"] == "PASS"
    manifest = json.loads((DATA / "manifest.json").read_text())
    assert manifest["adapter"] == "wvc-advisory-v1"
    assert manifest["base_model"] == "Qwen/Qwen3.8-27B"
    assert manifest["parent_adapter"] is None
    assert manifest["files"]["train"]["tasks"] == {"CURRENT": 104, "FUTURE": 56}


def test_current_contract_is_v122_only() -> None:
    for split in ("train", "holdout", "challenge"):
        for row in rows(split):
            assert row["domain"] == "WVC"
            if row["task"] != "CURRENT":
                continue
            target = json.loads(row["assistant"])
            assert set(target) == {"schema_version", "environmental_attention", "selected_fact_ids"}
            assert target["schema_version"] == 1
            assert isinstance(target["environmental_attention"], bool)
            assert len(target["selected_fact_ids"]) <= 6
            payload = json.loads(row["user"].split("\n\n", 1)[1])
            for fact in payload["facts"]:
                assert fact["kind"] in {"reading", "setpoint", "controller_mode"}
                if fact["kind"] == "reading":
                    assert fact["channel"] in ALLOWED_CHANNELS
                    assert "missing" not in fact
                    assert "count" not in fact
            text = row["user"].lower()
            assert "active_alarm_codes" not in text
            assert "active_alarm_sample_count" not in text
            assert "sensor_node_unavailable" not in text


def test_split_families_do_not_overlap() -> None:
    families = {}
    for split in ("train", "holdout", "challenge"):
        families[split] = {row["family"] for row in rows(split)}
    assert families["train"].isdisjoint(families["holdout"])
    assert families["train"].isdisjoint(families["challenge"])
    assert families["holdout"].isdisjoint(families["challenge"])


def test_training_has_rocm_numerical_stability_guards() -> None:
    source = (HERE / "train.py").read_text()
    assert "foreach=False" in source
    assert "fused=False" in source
    assert "assert_finite_gradients(" in source
    assert "assert_finite_optimizer_state(model, optimizer" in source
    assert "optimizer.zero_grad(set_to_none=True)" in source
    assert "torch.cuda.empty_cache()" in source
    assert "vram_reserved_before_cleanup" in source
    assert "vram_reserved_after_cleanup" in source
