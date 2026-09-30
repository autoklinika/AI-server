#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,random
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics_v4"
TARGET=DIR/"discriminating_measurement_v4_train.jsonl"
V3=ROOT/"deploy/stage-p5/training/electronics_v3/electronics_foundation_v3_replay_train.jsonl"
def load(p): return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    target=load(TARGET); prior=load(V3)
    groups={}
    for r in prior: groups.setdefault(r.get("metadata",{}).get("replay_source","v3_new"),[]).append(r)
    rng=random.Random(20260930)
    wanted={"v3_new":8,"v2_replay":4,"v1_replay":3}
    replay=[]
    for src,n in wanted.items():
        for r in rng.sample(groups[src],n):
            x=json.loads(json.dumps(r)); x["metadata"]["p56_replay_source"]=src; replay.append(x)
    rows=target+replay
    seed=20261037
    probe=list(rows); random.Random(seed).shuffle(probe)
    first10=sum(r["record_id"].startswith("ELEC4-") for r in probe[:10])
    if first10 < 6: raise SystemExit("P5_6_REPLAY=FAIL weak_initial_target_mix")
    out=DIR/"discriminating_measurement_v4_replay_train.jsonl"
    out.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows))
    m={"schema_version":1,"dataset_id":"discriminating-measurement-v4-replay","records":len(rows),
       "target_records":len(target),"target_microcases":300,"replay_records":len(replay),
       "replay_mix":wanted,"trainer_shuffle_seed":seed,"steps_for_full_pass":len(rows),
       "dataset_sha256":sha(out),"parent_adapter":"electronics-foundation-v3/current"}
    (DIR/"discriminating_measurement_v4_replay.manifest.json").write_text(json.dumps(m,indent=2,sort_keys=True)+"\n")
    print("P5_6_REPLAY_DATASET=PASS"); print(json.dumps(m,sort_keys=True))
if __name__=="__main__": main()
