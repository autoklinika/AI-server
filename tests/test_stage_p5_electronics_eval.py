import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy/stage-p5/training/electronics/compare_electronics_eval_v1.py"
spec = importlib.util.spec_from_file_location("electronics_compare", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_holdout_improvement_gate_passes_at_five_percent():
    base = {"status": "PASS", "records": 24, "token_weighted_loss": 1.5}
    tuned = {"status": "PASS", "records": 24, "token_weighted_loss": 1.35}
    result = mod.compare(base, tuned, 0.05)
    assert result["gate_pass"] is True
    assert result["relative_improvement"] > 0.09


def test_holdout_gate_rejects_regression():
    base = {"status": "PASS", "records": 24, "token_weighted_loss": 1.5}
    tuned = {"status": "PASS", "records": 24, "token_weighted_loss": 1.55}
    assert mod.compare(base, tuned, 0.05)["gate_pass"] is False
