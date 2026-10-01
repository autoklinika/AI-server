#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/p59"
P58_FINAL=ROOT/"deploy/stage-p5/training/p58/p58_final_v1.jsonl"

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def rows(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]

def main():
    m=json.loads((DIR/"p59_manifest.json").read_text())
    files={
      "train":DIR/"p59_thermal_train.jsonl",
      "dev":DIR/"p59_thermal_dev_v1.jsonl",
      "mini":DIR/"p59_thermal_mini_dev_v1.jsonl"
    }
    train,dev,mini=(rows(files[k]) for k in ("train","dev","mini"))
    ttext={r["user"] for r in train}
    dtext={r["prompt"] for r in dev}
    ftext={r["prompt"] for r in rows(P58_FINAL)}
    dev_ids={r["case_id"] for r in dev}
    thermal_train=[r for r in train if r.get("metadata",{}).get("category")=="thermal_intermittent"]
    abstain_train=[r for r in train if json.loads(r["assistant"]).get("abstain") is True]
    target_predictions=[json.loads(r["assistant"])["predicted_result"] for r in thermal_train]
    blocks={}
    for r in thermal_train:
        mo=re.match(r"P59-TRAIN-THM-(\d+)-(\d+)$",r["record_id"])
        if not mo:
            continue
        blocks.setdefault(int(mo.group(1)),set()).add(int(mo.group(2)))

    checks={
      "train_count":len(train)==m["train_records"],
      "dev_count":len(dev)==m["dev_records"],
      "mini_count":len(mini)==m["mini_dev_records"],
      "train_sha":sha(files["train"])==m["train_sha256"],
      "dev_sha":sha(files["dev"])==m["dev_sha256"],
      "mini_sha":sha(files["mini"])==m["mini_dev_sha256"],
      "p58_final_sha":sha(P58_FINAL)==m["p58_final_sha256"],
      "train_dev_disjoint":not bool(ttext & dtext),
      "train_final_disjoint":not bool(ttext & ftext),
      "dev_final_disjoint":not bool(dtext & ftext),
      "mini_subset":all(r["case_id"] in dev_ids for r in mini),
      "dev_training_exclusion":all(r.get("training_exclusion") is True for r in dev),
      "thermal_train_count":len(thermal_train)==m["thermal_train_records"]==48,
      "abstain_replay_count":len(abstain_train)==8,
      "eight_blocks":len(blocks)==8 and all(blocks.get(i)==set(range(6)) for i in range(8)),
      "conditional_predictions":all("jeśli" in p.lower() for p in target_predictions),
      "sealed_final_policy":"sealed final" in m["p58_final_role"].lower()
    }
    status="PASS" if all(checks.values()) else "FAIL"
    out={"status":status,"checks":checks}
    print(json.dumps(out,sort_keys=True,ensure_ascii=False))
    print("P59_READINESS="+status)
    if status!="PASS":
        raise SystemExit(1)

if __name__=="__main__":
    main()
