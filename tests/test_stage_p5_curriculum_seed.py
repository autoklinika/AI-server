import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"deploy/stage-p5/training/fixtures/automotive_curriculum_seed_v1.jsonl"
MAN=ROOT/"deploy/stage-p5/training/fixtures/automotive_curriculum_seed_v1.manifest.json"

def test_curriculum_seed_gate_reproducible():
    subprocess.run(
        [sys.executable,str(ROOT/"deploy/stage-p5/training/prepare_curriculum_seed_v1.py")],
        cwd=ROOT,check=True,
    )
    rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
    manifest=json.loads(MAN.read_text())
    assert len(rows)==20
    assert manifest["records"]==20
    assert all(r["metadata"]["training_eligible"] for r in rows)
    assert all(r["metadata"]["case_ids"]==[] for r in rows)
    assert all(r["metadata"]["source_kind"]=="project_owned_synthetic" for r in rows)
    assert set(manifest["reserved_benchmark_case_families"]) >= {"CASE-0001","CASE-0002"}

def test_no_benchmark_or_oem_training_sources():
    text=DATA.read_text()
    assert "ERS-GOLD-" not in text
    assert "CASE-0001" not in text
    assert "CASE-0002" not in text
    assert "retrieval_reference_only_pending_license_review" not in text
