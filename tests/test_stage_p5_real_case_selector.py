import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"deploy/stage-p5/training/select_real_training_cases_v1.py"

def write_case(root, case_id, *, closed=True, confirmation="workshop_confirmed"):
    d=root/"cases"/case_id
    d.mkdir(parents=True)
    (d/"case.seed.json").write_text(json.dumps({
        "legacy_case_code":case_id,
        "final_status":"closed" if closed else "open",
        "results":[{"confirmation_status":confirmation}],
    }))

def run(root, golden_rows, approved):
    golden=Path(root)/"golden.jsonl"
    golden.write_text("".join(json.dumps(x)+"\n" for x in golden_rows))
    allow=Path(root)/"allow.json"
    allow.write_text(json.dumps({"schema_version":1,"approved_case_ids":approved}))
    return subprocess.run(
        [sys.executable,str(SCRIPT),"--ers-repo",str(root),"--golden",str(golden),"--allowlist",str(allow)],
        cwd=ROOT,text=True,capture_output=True,
    )

def test_confirmed_unbenchmarked_allowlisted_case_is_selected():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); write_case(root,"CASE-0099")
        r=run(root,[],["CASE-0099"])
        assert r.returncode==0, r.stdout+r.stderr
        assert '"eligible_case_ids": ["CASE-0099"]' in r.stdout

def test_benchmarked_or_unconfirmed_case_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        write_case(root,"CASE-0001-LONG-NAME")
        write_case(root,"CASE-0098",closed=False,confirmation="bench_confirmed_vehicle_pending")
        golden=[{"provenance":{"case_ids":["CASE-0001"]}}]
        r=run(root,golden,["CASE-0001-LONG-NAME","CASE-0098"])
        assert r.returncode==0, r.stdout+r.stderr
        assert '"eligible_case_ids": []' in r.stdout
        assert "reserved_by_benchmark" in r.stdout
        assert "case_not_closed" in r.stdout
