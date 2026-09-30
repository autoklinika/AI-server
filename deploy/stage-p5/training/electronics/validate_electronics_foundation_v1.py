#!/usr/bin/env python3
from __future__ import annotations
import json, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics"
TRAIN=DIR/"electronics_foundation_train_v1.jsonl"
HOLD=DIR/"electronics_foundation_holdout_v1.jsonl"
MAN=DIR/"electronics_foundation_v1.manifest.json"
HEADINGS=["DANE:","MODEL/PRAWO:","WNIOSKOWANIE:","POMIAR/KONTROLA:","ODPOWIEDŹ:","PEWNOŚĆ:"]

def norm(s):
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9ąćęłńóśźż]+"," ",s.lower())).strip()

def rows(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def main():
    train=rows(TRAIN); hold=rows(HOLD); man=json.loads(MAN.read_text())
    failures=[]
    if len(train)<150: failures.append(f"train_records:{len(train)}<150")
    if len(hold)<20: failures.append(f"holdout_records:{len(hold)}<20")
    cats={r["metadata"]["category"] for r in train}
    if len(cats)<30: failures.append(f"categories:{len(cats)}<30")
    if man.get("external_text_copied") is not False: failures.append("external_text_policy")
    if man.get("oem_material_used") is not False: failures.append("oem_policy")
    if man.get("automotive_golden_used") is not False: failures.append("golden_policy")
    for split,records in (("train",train),("holdout",hold)):
        ids=[r["record_id"] for r in records]
        if len(ids)!=len(set(ids)): failures.append(f"{split}_duplicate_ids")
        texts=[norm(r["user"]+" "+r["assistant"]) for r in records]
        if len(texts)!=len(set(texts)): failures.append(f"{split}_duplicate_text")
        for r in records:
            if any(h not in r["assistant"] for h in HEADINGS):
                failures.append(f"{split}_structure:{r['record_id']}")
            expected=(split=="train")
            if r["metadata"]["training_eligible"] is not expected:
                failures.append(f"{split}_eligibility:{r['record_id']}")
    t={norm(r["user"]+" "+r["assistant"]) for r in train}
    h={norm(r["user"]+" "+r["assistant"]) for r in hold}
    if t & h: failures.append("train_holdout_overlap")
    report={
      "train_records":len(train),"holdout_records":len(hold),
      "train_categories":len(cats),"failures":failures,
      "train_sha256":man["train_sha256"],"holdout_sha256":man["holdout_sha256"],
    }
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    if failures:
        raise SystemExit("P5_2_ELECTRONICS_READINESS=FAIL "+ ";".join(failures))
    print("P5_2_ELECTRONICS_READINESS=PASS")

if __name__=="__main__":
    main()
