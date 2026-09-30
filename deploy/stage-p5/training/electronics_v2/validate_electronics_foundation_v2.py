#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics_v2"
TRAIN=DIR/"electronics_foundation_v2_train.jsonl"
HOLD=DIR/"electronics_foundation_v2_holdout.jsonl"
MAN=DIR/"electronics_foundation_v2.manifest.json"
V1=ROOT/"deploy/stage-p5/training/electronics"
HEADINGS=["DANE:","MODEL/PRAWO:","WNIOSKOWANIE:","POMIAR/KONTROLA:","ODPOWIEDŹ:","PEWNOŚĆ:"]

def rows(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def norm(s):
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9ąćęłńóśźż]+"," ",s.lower())).strip()

def sha(path):
    h=hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()

def main():
    train=rows(TRAIN); hold=rows(HOLD); man=json.loads(MAN.read_text())
    failures=[]
    if len(train)!=155: failures.append(f"train_records:{len(train)}")
    if len(hold)!=24: failures.append(f"holdout_records:{len(hold)}")
    if len({r["metadata"]["category"] for r in train})!=31: failures.append("train_categories")
    if len({r["metadata"]["category"] for r in hold})!=8: failures.append("holdout_categories")
    if man["train_sha256"]!=sha(TRAIN): failures.append("train_sha")
    if man["holdout_sha256"]!=sha(HOLD): failures.append("holdout_sha")
    if man.get("external_text_copied") is not False or man.get("oem_material_used") is not False:
        failures.append("source_policy")
    for split,items in (("train",train),("holdout",hold)):
        ids=[r["record_id"] for r in items]
        if len(ids)!=len(set(ids)): failures.append(f"{split}_duplicate_id")
        texts=[norm(r["user"]+" "+r["assistant"]) for r in items]
        if len(texts)!=len(set(texts)): failures.append(f"{split}_duplicate_text")
        for r in items:
            if any(h not in r["assistant"] for h in HEADINGS):
                failures.append(f"{split}_structure:{r['record_id']}")
    old=rows(V1/"electronics_foundation_train_v1.jsonl")+rows(V1/"electronics_foundation_holdout_v1.jsonl")
    old_text={norm(r["user"]+" "+r["assistant"]) for r in old}
    if any(norm(r["user"]+" "+r["assistant"]) in old_text for r in train+hold):
        failures.append("v1_exact_overlap")
    print(json.dumps({"failures":failures,"train_records":len(train),"holdout_records":len(hold)},sort_keys=True))
    if failures: raise SystemExit("P5_3_ELECTRONICS_V2_READINESS=FAIL")
    print("P5_3_ELECTRONICS_V2_READINESS=PASS")

if __name__=="__main__":
    main()
