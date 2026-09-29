#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

CONFIRMED = {"workshop_confirmed", "vehicle_confirmed", "application_confirmed"}

def load_jsonl(path: Path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--ers-repo", default="/home/harrypotter/EcuRepairService")
    ap.add_argument("--golden", default="benchmarks/automotive_v1/datasets/golden.v1.jsonl")
    ap.add_argument("--allowlist", default="deploy/stage-p5/training/real_case_training_allowlist_v1.json")
    args=ap.parse_args()

    golden=load_jsonl(Path(args.golden))
    benchmarked={c for row in golden for c in row.get("provenance",{}).get("case_ids",[])}
    allow_doc=json.loads(Path(args.allowlist).read_text())
    approved=set(allow_doc.get("approved_case_ids",[]))
    if len(approved) != len(allow_doc.get("approved_case_ids",[])):
        raise SystemExit("P5_1_REAL_CASE_GATE=FAIL duplicate_allowlist")

    root=Path(args.ers_repo)/"cases"
    results=[]
    selected=[]
    if root.is_dir():
        for seed in sorted(root.glob("*/case.seed.json")):
            doc=json.loads(seed.read_text())
            case_id=doc.get("legacy_case_code") or seed.parent.name
            confirmations={
                r.get("confirmation_status")
                for r in doc.get("results",[])
                if r.get("confirmation_status")
            }
            final_status=doc.get("final_status")
            reasons=[]
            if case_id in benchmarked: reasons.append("reserved_by_benchmark")
            if final_status != "closed": reasons.append("case_not_closed")
            if not confirmations.intersection(CONFIRMED): reasons.append("no_confirmed_final_result")
            if case_id not in approved: reasons.append("not_allowlisted")
            eligible=not reasons
            item={
                "case_id":case_id,
                "seed":str(seed),
                "final_status":final_status,
                "confirmation_statuses":sorted(confirmations),
                "benchmarked":case_id in benchmarked,
                "allowlisted":case_id in approved,
                "eligible":eligible,
                "reasons":reasons,
            }
            results.append(item)
            if eligible: selected.append(item)

    unknown=sorted(approved-{x["case_id"] for x in results})
    if unknown:
        raise SystemExit("P5_1_REAL_CASE_GATE=FAIL allowlisted_case_missing:"+",".join(unknown))

    print(json.dumps({
        "cases_seen":len(results),
        "benchmarked_case_ids":sorted(benchmarked),
        "approved_case_ids":sorted(approved),
        "eligible_case_ids":[x["case_id"] for x in selected],
        "cases":results,
    },ensure_ascii=False,sort_keys=True))
    print(f"P5_1_REAL_CASE_GATE=PASS eligible={len(selected)}")

if __name__=="__main__":
    main()
