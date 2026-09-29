import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "deploy/stage-p5/training/electronics"
GEN = DIR / "prepare_electronics_foundation_v1.py"
VALID = DIR / "validate_electronics_foundation_v1.py"
TRAIN = DIR / "electronics_foundation_train_v1.jsonl"
HOLD = DIR / "electronics_foundation_holdout_v1.jsonl"
MAN = DIR / "electronics_foundation_v1.manifest.json"


def test_dataset_is_reproducible_and_separated():
    before = json.loads(MAN.read_text())
    r = subprocess.run([sys.executable, str(GEN)], cwd=ROOT, text=True, capture_output=True)
    assert r.returncode == 0, r.stdout + r.stderr
    after = json.loads(MAN.read_text())
    assert before["train_sha256"] == after["train_sha256"]
    assert before["holdout_sha256"] == after["holdout_sha256"]
    train = [json.loads(x) for x in TRAIN.read_text().splitlines() if x.strip()]
    hold = [json.loads(x) for x in HOLD.read_text().splitlines() if x.strip()]
    assert len(train) == 189
    assert len(hold) == 24
    assert all(r["metadata"]["training_eligible"] for r in train)
    assert not any(r["metadata"]["training_eligible"] for r in hold)


def test_no_oem_or_automotive_golden_material():
    manifest = json.loads(MAN.read_text())
    assert manifest["external_text_copied"] is False
    assert manifest["oem_material_used"] is False
    assert manifest["automotive_golden_used"] is False
    text = TRAIN.read_text() + HOLD.read_text()
    assert "ERS-GOLD-" not in text
    assert "CASE-0001" not in text
    assert "CASE-0002" not in text


def test_readiness_gate_passes():
    r = subprocess.run([sys.executable, str(VALID)], cwd=ROOT, text=True, capture_output=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "P5_2_ELECTRONICS_READINESS=PASS" in r.stdout


def test_reasoning_contract_present():
    required = ["DANE:", "MODEL/PRAWO:", "WNIOSKOWANIE:", "POMIAR/KONTROLA:", "ODPOWIEDŹ:", "PEWNOŚĆ:"]
    for path in (TRAIN, HOLD):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            assert all(x in row["assistant"] for x in required)
