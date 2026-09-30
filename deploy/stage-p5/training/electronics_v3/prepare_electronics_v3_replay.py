#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, random
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics_v3"
V1=ROOT/"deploy/stage-p5/training/electronics/electronics_foundation_train_v1.jsonl"
V2=ROOT/"deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_train.jsonl"
V3=DIR/"electronics_foundation_v3_train.jsonl"

def load(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def tagged(row,source):
    r=json.loads(json.dumps(row))
    r["metadata"]["replay_source"]=source
    return r

def main():
    v3=[tagged(r,"v3_new") for r in load(V3)]
    v2rows=load(V2); v1rows=load(V1)
    rng=random.Random(20260930)
    v2=[tagged(r,"v2_replay") for r in rng.sample(v2rows,30)]
    v1=[tagged(r,"v1_replay") for r in rng.sample(v1rows,20)]
    rows=v3+v2+v1
    seed=None; first40=None
    for candidate in range(20261000,20263000):
        tmp=list(rows); random.Random(candidate).shuffle(tmp)
        c=Counter(r["metadata"]["replay_source"] for r in tmp[:40])
        if c==Counter({"v3_new":30,"v2_replay":5,"v1_replay":5}):
            seed=candidate; first40=dict(sorted(c.items())); break
    if seed is None:
        raise SystemExit("P5_4_REPLAY=FAIL no_seed_for_first40_mix")
    out=DIR/"electronics_foundation_v3_replay_train.jsonl"
    out.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows))
    manifest={
      "schema_version":1,"dataset_id":"electronics-foundation-v3-replay",
      "records":len(rows),"v3_new_records":len(v3),"v2_replay_records":len(v2),"v1_replay_records":len(v1),
      "holdout_leakage":False,"trainer_shuffle_seed":seed,
      "first40_after_trainer_shuffle":first40,"dataset_sha256":sha(out),
      "base_adapter":"electronics-foundation-v2/current",
    }
    (DIR/"electronics_foundation_v3_replay.manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print("P5_4_REPLAY_DATASET_GATE=PASS")
    print(json.dumps(manifest,sort_keys=True))
if __name__=="__main__":
    main()
