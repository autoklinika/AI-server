import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / "deploy/stage-p5/training/electronics/electronics_foundation_selection_v1.json"


def test_r1_is_selected_by_frozen_holdout():
    doc = json.loads(SELECTION.read_text())
    assert doc["status"] == "selected_for_next_stage_not_deployed"
    assert doc["selected_run"] == "electronics-foundation-v1-r1-20260929"
    assert doc["r1_holdout_loss"] < doc["r2_holdout_loss"]
    assert doc["r1_holdout_loss"] < doc["base_holdout_loss"]
    assert doc["r2_holdout_loss"] < doc["base_holdout_loss"]


def test_selected_adapter_identity_is_frozen():
    doc = json.loads(SELECTION.read_text())
    assert doc["selected_adapter_sha256"] == "9b52b30908baf29f21856ec2f0777dfd6b7d2e4a7f3b83b521127917c3034935"
    assert doc["selection_metric"] == "frozen_holdout_token_weighted_loss"
    assert doc["r2_relative_change_vs_r1"] < 0
