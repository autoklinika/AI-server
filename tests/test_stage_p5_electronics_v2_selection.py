import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEL = ROOT / "deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_selection.json"


def test_replay_run_is_selected():
    doc = json.loads(SEL.read_text())
    assert doc["status"] == "selected_for_next_stage_not_deployed"
    assert doc["dual_holdout_gate"] == "PASS"
    assert doc["selected_run"] == "electronics-foundation-v2-replay-r1-20260930"
    assert doc["selected_adapter_sha256"] == "96c6565a6b1f29c1c86716e90c966aef09915009bd1041639bdd545e1383c84c"


def test_selection_improves_new_without_forgetting_old():
    doc = json.loads(SEL.read_text())
    assert doc["v2_relative_improvement"] >= 0.05
    assert doc["v1_relative_regression"] <= 0.03
    assert doc["v2_selected_loss"] < doc["v2_baseline_loss"]
    assert doc["v1_selected_loss"] <= doc["v1_reference_loss"] * 1.03


def test_new_only_run_remains_rejected():
    doc = json.loads(SEL.read_text())
    assert doc["rejected_run"] == "electronics-foundation-v2-r1-20260930"
    assert "8.0732%" in doc["rejected_reason"]
