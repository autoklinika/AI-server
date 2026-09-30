import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/"deploy/stage-p5/training/electronics_v2"
GEN=DIR/"prepare_electronics_foundation_v2.py"
VALID=DIR/"validate_electronics_foundation_v2.py"
GATE=DIR/"dual_holdout_gate_v2.py"
MAN=DIR/"electronics_foundation_v2.manifest.json"

def test_v2_dataset_reproducible_and_ready():
    before=json.loads(MAN.read_text())
    r=subprocess.run([sys.executable,str(GEN)],cwd=ROOT,text=True,capture_output=True)
    assert r.returncode==0, r.stdout+r.stderr
    after=json.loads(MAN.read_text())
    assert before["train_sha256"]==after["train_sha256"]
    assert before["holdout_sha256"]==after["holdout_sha256"]
    r=subprocess.run([sys.executable,str(VALID)],cwd=ROOT,text=True,capture_output=True)
    assert r.returncode==0, r.stdout+r.stderr
    assert "P5_3_ELECTRONICS_V2_READINESS=PASS" in r.stdout

def _eval(path,loss):
    Path(path).write_text(json.dumps({"status":"PASS","records":24,"token_weighted_loss":loss}))

def test_dual_holdout_gate_accepts_new_gain_without_old_regression():
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)
        _eval(p/"vb.json",1.50); _eval(p/"vt.json",1.30)
        _eval(p/"v1r.json",1.10); _eval(p/"v1t.json",1.12)
        r=subprocess.run([sys.executable,str(GATE),"--v2-base",str(p/"vb.json"),"--v2-tuned",str(p/"vt.json"),
            "--v1-reference",str(p/"v1r.json"),"--v1-tuned",str(p/"v1t.json"),"--output",str(p/"out.json")],
            cwd=ROOT,text=True,capture_output=True)
        assert r.returncode==0, r.stdout+r.stderr
        assert json.loads((p/"out.json").read_text())["gate_pass"] is True

def test_dual_holdout_gate_rejects_old_skill_regression():
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)
        _eval(p/"vb.json",1.50); _eval(p/"vt.json",1.30)
        _eval(p/"v1r.json",1.10); _eval(p/"v1t.json",1.20)
        r=subprocess.run([sys.executable,str(GATE),"--v2-base",str(p/"vb.json"),"--v2-tuned",str(p/"vt.json"),
            "--v1-reference",str(p/"v1r.json"),"--v1-tuned",str(p/"v1t.json"),"--output",str(p/"out.json")],
            cwd=ROOT,text=True,capture_output=True)
        assert r.returncode!=0
        assert json.loads((p/"out.json").read_text())["v1_regression_gate_pass"] is False


def test_replay_dataset_preserves_expected_first40_mix():
    script = DIR / "prepare_electronics_v2_replay.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((DIR / "electronics_foundation_v2_replay.manifest.json").read_text())
    assert manifest["records"] == 207
    assert manifest["v2_new_records"] == 155
    assert manifest["v1_replay_records"] == 52
    assert manifest["holdout_leakage"] is False
    assert manifest["first40_after_trainer_shuffle"] == {"v1_replay": 10, "v2_new": 30}


def test_replay_runner_starts_from_selected_v1_adapter():
    text = (DIR / "run_electronics_foundation_v2_replay.sh").read_text()
    assert "electronics_foundation_v2_replay_train.jsonl" in text
    assert "P5_ELECTRONICS_V2_REPLAY_LR:-0.00003" in text
    assert "electronics-foundation-v1/current" in text
    assert "prepare_electronics_v2_replay.py" in text
