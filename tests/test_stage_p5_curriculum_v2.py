import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"deploy/stage-p5/training/prepare_curriculum_v2.py"
DATA=ROOT/"deploy/stage-p5/training/fixtures/automotive_curriculum_v2.jsonl"
MAN=ROOT/"deploy/stage-p5/training/fixtures/automotive_curriculum_v2.manifest.json"

def _regen():
    result=subprocess.run([sys.executable,str(SCRIPT)],cwd=ROOT,text=True,capture_output=True)
    assert result.returncode==0, result.stdout+result.stderr
    assert "P5_1_V2_DATASET_GATE=PASS" in result.stdout

def test_v2_counts_and_structure():
    _regen()
    rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
    manifest=json.loads(MAN.read_text())
    assert len(rows)==155
    assert manifest["records"]==155
    assert manifest["unique_categories"]==47
    assert manifest["incomplete_evidence_records"]==30
    assert len({r["record_id"] for r in rows})==155
    assert all(r["metadata"]["training_eligible"] is True for r in rows)
    assert all(r["metadata"]["case_ids"]==[] for r in rows)

def test_v2_has_no_reserved_or_retrieval_only_source_leakage():
    text=DATA.read_text()
    for forbidden in (
        "ERS-GOLD-",
        "CASE-0001",
        "CASE-0002",
        "retrieval_reference_only_pending_license_review",
    ):
        assert forbidden not in text

def test_v2_is_deterministic():
    _regen()
    first=json.loads(MAN.read_text())["dataset_sha256"]
    _regen()
    second=json.loads(MAN.read_text())["dataset_sha256"]
    assert first==second=="b9f3b85afd10d0bcbc286b95c1f2f8b4135f095ca8911b2f8780235c8e6190cc"
