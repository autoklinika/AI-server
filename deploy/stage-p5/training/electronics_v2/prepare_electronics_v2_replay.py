#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, random
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
V2=ROOT/"deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_train.jsonl"
V1=ROOT/"deploy/stage-p5/training/electronics/electronics_foundation_train_v1.jsonl"
V1H=ROOT/"deploy/stage-p5/training/electronics/electronics_foundation_holdout_v1.jsonl"
V2H=ROOT/"deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_holdout.jsonl"
OUT=ROOT/"deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_replay_train.jsonl"
MAN=ROOT/"deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_replay.manifest.json"
SEED=20260930

def load(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    v2=load(V2); v1=load(V1)
    rng=random.Random(SEED)
    replay=rng.sample(v1,52)
    rows=[]
    for row in v2:
        x=json.loads(json.dumps(row))
        x["metadata"]["replay_source"]="v2_new"
        rows.append(x)
    for row in replay:
        x=json.loads(json.dumps(row))
        x["record_id"]="REPLAY-"+x["record_id"]
        x["metadata"]["replay_source"]="v1_replay"
        x["metadata"]["curriculum"]="electronics-foundation-v2-replay"
        rows.append(x)

    holdout_ids={r["record_id"] for r in load(V1H)+load(V2H)}
    if any(r["record_id"].replace("REPLAY-","") in holdout_ids for r in rows):
        raise SystemExit("P5_3_REPLAY=FAIL holdout_leakage")
    ids=[r["record_id"] for r in rows]
    if len(ids)!=len(set(ids)):
        raise SystemExit("P5_3_REPLAY=FAIL duplicate_ids")

    OUT.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows))
    probe=list(rows)
    random.Random(SEED).shuffle(probe)
    first40=probe[:40]
    c={"v2_new":0,"v1_replay":0}
    for r in first40:
        c[r["metadata"]["replay_source"]]+=1
    if c["v1_replay"]<7 or c["v1_replay"]>13:
        raise SystemExit(f"P5_3_REPLAY=FAIL first40_ratio:{c}")
    manifest={
        "schema_version":1,
        "dataset_id":"electronics-foundation-v2-replay",
        "records":len(rows),
        "v2_new_records":len(v2),
        "v1_replay_records":len(replay),
        "configured_ratio":"155:52 (~3:1)",
        "first40_after_trainer_shuffle":c,
        "seed":SEED,
        "dataset_sha256":sha(OUT),
        "v2_source_sha256":sha(V2),
        "v1_source_sha256":sha(V1),
        "holdout_leakage":False,
    }
    MAN.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print("P5_3_REPLAY_DATASET_GATE=PASS")
    print(json.dumps(manifest,sort_keys=True))

if __name__=="__main__":
    main()
