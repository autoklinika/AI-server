#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics_v3"
HEAD=["DANE:","MODEL/PRAWO:","WNIOSKOWANIE:","POMIAR/KONTROLA:","ODPOWIEDŹ:","PEWNOŚĆ:"]

def load(p): return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]

def main():
    train=load(DIR/"electronics_foundation_v3_train.jsonl")
    hold=load(DIR/"electronics_foundation_v3_holdout.jsonl")
    man=json.loads((DIR/"electronics_foundation_v3.manifest.json").read_text())
    fail=[]
    if len(train)!=150: fail.append(f"train:{len(train)}")
    if len(hold)!=24: fail.append(f"hold:{len(hold)}")
    if man.get("train_categories")!=30: fail.append("categories")
    if man.get("prior_records_checked")!=392: fail.append("prior_records")
    if any(r["metadata"].get("training_eligible") is not True for r in train): fail.append("train_eligibility")
    if any(r["metadata"].get("training_eligible") is not False for r in hold): fail.append("holdout_eligibility")
    if any(any(h not in r["assistant"] for h in HEAD) for r in train+hold): fail.append("structure")
    if man.get("external_text_copied") is not False or man.get("oem_material_used") is not False: fail.append("source_policy")
    print(json.dumps({"train":len(train),"holdout":len(hold),"categories":man.get("train_categories"),"failures":fail},sort_keys=True))
    if fail: raise SystemExit("P5_4_ELECTRONICS_V3_READINESS=FAIL "+";".join(fail))
    print("P5_4_ELECTRONICS_V3_READINESS=PASS")
if __name__=="__main__": main()
