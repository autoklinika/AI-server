#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics_v4"
P55=ROOT/"benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"
EXPECTED="8ba6b0a767c4649949a399e38e276287cc3058d89e89fca86d44b3ddb1858fa5"
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p): return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def main():
    train=load(DIR/"discriminating_measurement_v4_train.jsonl")
    hold=load(DIR/"discriminating_measurement_v4_holdout.jsonl")
    replay=load(DIR/"discriminating_measurement_v4_replay_train.jsonl")
    manifest=json.loads((DIR/"discriminating_measurement_v4.manifest.json").read_text())
    rm=json.loads((DIR/"discriminating_measurement_v4_replay.manifest.json").read_text())
    checks={
      "p55_frozen":sha(P55)==EXPECTED,
      "target_records":len(train)==50,
      "target_microcases":sum(r["metadata"].get("microcases",0) for r in train)==300,
      "holdout_records":len(hold)==36,
      "replay_records":len(replay)==65,
      "replay_target_records":sum(r["record_id"].startswith("ELEC4-") for r in replay)==50,
      "manifest_target_sha":manifest["train_sha256"]==sha(DIR/"discriminating_measurement_v4_train.jsonl"),
      "manifest_holdout_sha":manifest["holdout_sha256"]==sha(DIR/"discriminating_measurement_v4_holdout.jsonl"),
      "manifest_replay_sha":rm["dataset_sha256"]==sha(DIR/"discriminating_measurement_v4_replay_train.jsonl"),
      "p55_excluded":manifest.get("p55_training_exclusion") is True,
    }
    status="PASS" if all(checks.values()) else "FAIL"
    print(json.dumps({"status":status,"checks":checks},sort_keys=True))
    print("P5_6_READINESS="+status)
    if status!="PASS": raise SystemExit(1)
if __name__=="__main__": main()
