#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from collections import Counter
from pathlib import Path

HEADINGS = [
    "FAKTY:", "WYKLUCZONE:", "HIPOTEZY:", "TEST ROZDZIELAJĄCY:",
    "OCZEKIWANE WYNIKI:", "INTERPRETACJA:", "NASTĘPNY KROK:", "PEWNOŚĆ:",
]
INCOMPLETE_CATEGORIES = {
    "insufficient_evidence", "partial_verification", "bench_wakeup_unknown",
    "replace_pressure", "clone_identity", "clone_readback",
}

def norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ąćęłńóśźż]+", " ", text.lower())).strip()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--dataset", default="deploy/stage-p5/training/fixtures/automotive_curriculum_v2.jsonl")
    ap.add_argument("--policy", default="deploy/stage-p5/training/curriculum_readiness_policy_v1.json")
    ap.add_argument("--level", choices=["seed","serious"], default="serious")
    args=ap.parse_args()

    rows=[json.loads(x) for x in Path(args.dataset).read_text().splitlines() if x.strip()]
    policy=json.loads(Path(args.policy).read_text())["serious_calibration"]
    failures=[]
    ids=[r.get("record_id") for r in rows]
    if len(ids) != len(set(ids)): failures.append("duplicate_record_id")
    for row in rows:
        if not row.get("metadata",{}).get("training_eligible"): failures.append(f"not_training_eligible:{row.get('record_id')}")
        if row.get("metadata",{}).get("case_ids"): failures.append(f"case_id_present:{row.get('record_id')}")
        if any(h not in row.get("assistant","") for h in HEADINGS): failures.append(f"structure:{row.get('record_id')}")
    normalized=[norm(r.get("user","")+" "+r.get("assistant","")) for r in rows]
    duplicate_fraction=1.0-(len(set(normalized))/max(1,len(normalized)))
    categories=Counter(r.get("metadata",{}).get("category") for r in rows)
    source_kinds=Counter(r.get("metadata",{}).get("source_kind") for r in rows)
    incomplete=sum(1 for r in rows if r.get("metadata",{}).get("incomplete_evidence") is True or r.get("metadata",{}).get("category") in INCOMPLETE_CATEGORIES)

    serious_failures=[]
    if len(rows) < policy["min_records"]: serious_failures.append(f"records:{len(rows)}<{policy['min_records']}")
    if len(categories) < policy["min_unique_categories"]: serious_failures.append(f"categories:{len(categories)}<{policy['min_unique_categories']}")
    if len(source_kinds) < policy["min_source_kinds"]: serious_failures.append(f"source_kinds:{len(source_kinds)}<{policy['min_source_kinds']}")
    missing_sources=[x for x in policy["required_source_kinds"] if x not in source_kinds]
    if missing_sources: serious_failures.append("missing_source_kinds:"+",".join(missing_sources))
    if incomplete < policy["min_incomplete_evidence_records"]: serious_failures.append(f"incomplete:{incomplete}<{policy['min_incomplete_evidence_records']}")
    if duplicate_fraction > policy["max_normalized_duplicate_fraction"]: serious_failures.append(f"duplicate_fraction:{duplicate_fraction:.6f}")

    report={
        "records":len(rows),
        "unique_categories":len(categories),
        "categories":dict(sorted(categories.items())),
        "source_kinds":dict(sorted(source_kinds.items())),
        "incomplete_evidence_records":incomplete,
        "normalized_duplicate_fraction":duplicate_fraction,
        "base_failures":failures,
        "serious_failures":serious_failures,
    }
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    if failures:
        raise SystemExit("P5_1_READINESS=FAIL base:"+";".join(failures))
    if args.level=="serious" and serious_failures:
        raise SystemExit("P5_1_READINESS=NOT_READY serious:"+";".join(serious_failures))
    print(f"P5_1_READINESS=PASS level={args.level}")

if __name__=="__main__":
    main()
