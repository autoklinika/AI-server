import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEL = ROOT / "deploy/stage-p5/training/electronics_v3/electronics_foundation_v3_selection.json"


def test_v3_retry_is_selected():
    doc = json.loads(SEL.read_text())
    assert doc["status"] == "selected_for_next_stage_not_deployed"
    assert doc["triple_holdout_gate"] == "PASS"
    assert doc["selected_run"] == "electronics-foundation-v3-replay-r2-20260930"
    assert doc["selected_adapter_sha256"] == "2fbcbd394318576d2a50924ad2e3f7b452306566243ede24dd524c6d1b549183"


def test_v3_selection_passes_all_three_metrics():
    doc = json.loads(SEL.read_text())
    assert doc["v3_relative_improvement"] >= 0.05
    assert doc["v2_relative_regression"] <= 0.03
    assert doc["v1_relative_regression"] <= 0.03
    assert doc["v3_selected_loss"] < doc["v3_baseline_loss"]


def test_aborted_mes_run_is_not_selected():
    doc = json.loads(SEL.read_text())
    assert doc["aborted_run"] == "electronics-foundation-v3-replay-r1-20260930"
    assert "MES" in doc["aborted_reason"]
