import importlib.util
from pathlib import Path
import subprocess, sys

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"deploy/stage-p5/training/validate_curriculum_readiness_v1.py"

def test_seed_readiness_passes():
    r=subprocess.run([sys.executable,str(SCRIPT),"--level","seed"],cwd=ROOT,text=True,capture_output=True)
    assert r.returncode==0, r.stdout+r.stderr
    assert "P5_1_READINESS=PASS level=seed" in r.stdout

def test_serious_calibration_is_blocked_until_corpus_expands():
    r=subprocess.run([sys.executable,str(SCRIPT),"--level","serious"],cwd=ROOT,text=True,capture_output=True)
    assert r.returncode!=0
    text=r.stdout+r.stderr
    assert "P5_1_READINESS=NOT_READY" in text
    assert "records:20<100" in text
    assert "project_owned_confirmed_case_unbenchmarked" in text
