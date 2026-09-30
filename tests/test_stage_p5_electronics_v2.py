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
