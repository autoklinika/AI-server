import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/"deploy/stage-p5/training/electronics_v3"
GEN=DIR/"prepare_electronics_foundation_v3.py"
REPLAY=DIR/"prepare_electronics_v3_replay.py"
VALID=DIR/"validate_electronics_foundation_v3.py"
GATE=DIR/"triple_holdout_gate_v3.py"

def test_v3_dataset_and_replay_ready():
    for script,mark in [
        (GEN,"P5_4_ELECTRONICS_V3_DATASET_GATE=PASS"),
        (REPLAY,"P5_4_REPLAY_DATASET_GATE=PASS"),
        (VALID,"P5_4_ELECTRONICS_V3_READINESS=PASS"),
    ]:
        r=subprocess.run([sys.executable,str(script)],cwd=ROOT,text=True,capture_output=True)
        assert r.returncode==0, r.stdout+r.stderr
        assert mark in r.stdout
    m=json.loads((DIR/"electronics_foundation_v3.manifest.json").read_text())
    rm=json.loads((DIR/"electronics_foundation_v3_replay.manifest.json").read_text())
    assert m["train_records"]==150 and m["holdout_records"]==24
    assert m["train_categories"]==30 and m["prior_records_checked"]==392
    assert rm["records"]==200
    assert rm["first40_after_trainer_shuffle"]=={"v1_replay":5,"v2_replay":5,"v3_new":30}
    assert rm["holdout_leakage"] is False

def _ev(p,loss):
    Path(p).write_text(json.dumps({"status":"PASS","records":24,"token_weighted_loss":loss}))

def test_triple_gate_accepts_new_gain_and_preserved_old_skills():
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)
        for n,l in [("v3b",1.0),("v3t",0.8),("v2r",0.7),("v2t",0.71),("v1r",1.1),("v1t",1.11)]:
            _ev(p/f"{n}.json",l)
        r=subprocess.run([sys.executable,str(GATE),
          "--v3-base",str(p/"v3b.json"),"--v3-tuned",str(p/"v3t.json"),
          "--v2-reference",str(p/"v2r.json"),"--v2-tuned",str(p/"v2t.json"),
          "--v1-reference",str(p/"v1r.json"),"--v1-tuned",str(p/"v1t.json"),
          "--output",str(p/"out.json")],cwd=ROOT,text=True,capture_output=True)
        assert r.returncode==0, r.stdout+r.stderr
        assert json.loads((p/"out.json").read_text())["gate_pass"] is True

def test_triple_gate_rejects_v2_forgetting():
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)
        for n,l in [("v3b",1.0),("v3t",0.8),("v2r",0.7),("v2t",0.75),("v1r",1.1),("v1t",1.10)]:
            _ev(p/f"{n}.json",l)
        r=subprocess.run([sys.executable,str(GATE),
          "--v3-base",str(p/"v3b.json"),"--v3-tuned",str(p/"v3t.json"),
          "--v2-reference",str(p/"v2r.json"),"--v2-tuned",str(p/"v2t.json"),
          "--v1-reference",str(p/"v1r.json"),"--v1-tuned",str(p/"v1t.json"),
          "--output",str(p/"out.json")],cwd=ROOT,text=True,capture_output=True)
        assert r.returncode!=0
        assert json.loads((p/"out.json").read_text())["v2_regression_gate_pass"] is False

def test_runner_uses_selected_v2_and_safe_limits():
    text=(DIR/"run_electronics_foundation_v3.sh").read_text()
    assert "electronics-foundation-v2/current" in text
    assert "P5_ELECTRONICS_V3_MAX_LENGTH:-480" in text
    assert "P5_ELECTRONICS_V3_LR:-0.00002" in text
    assert "electronics_foundation_v3_replay_train.jsonl" in text
