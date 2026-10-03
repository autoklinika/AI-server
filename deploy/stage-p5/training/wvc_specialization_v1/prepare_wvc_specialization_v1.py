#!/usr/bin/env python3
"""Deterministic WVC authoring plus train-only replay from accepted P5 curricula."""
from __future__ import annotations
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from curriculum import new_records
from smoke_cases import smoke_records

HERE=Path(__file__).resolve().parent
PARENT="/srv/ai-data/training/p5/adapters/automotive-specialization-v1/current"
QUALITY="PENDING_WVC_BASELINE_REVIEW"
PROTECTED_EVAL=Path("/srv/ai-data/evaluation/wvc-baseline/ollama-0.32.14-p511-vs-p512-20261003/corpus.json")
SOURCES={
    "automotive": ("automotive_v1/automotive_specialization_v1_train.jsonl",32),
    "electronics_v1": ("electronics/electronics_foundation_train_v1.jsonl",10),
    "electronics_v2": ("electronics_v2/electronics_foundation_v2_train.jsonl",11),
    "electronics_v3": ("electronics_v3/electronics_foundation_v3_train.jsonl",11),
}
FILES=("wvc_specialization_v1_train.jsonl","wvc_specialization_v1_replay_train.jsonl","wvc_specialization_v1_smoke.jsonl")

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]

def content(row):
    return "\n".join(row[k] for k in ("user","assistant") if k in row)

def select_replay():
    replay=[]; provenance=[]; seen=set(); ids=set()
    for origin,(rel,count) in SOURCES.items():
        path=HERE.parent/rel
        groups=defaultdict(list)
        for row in read(path):
            if row["metadata"].get("split")!="train" or not row["metadata"].get("training_eligible",True):
                raise ValueError("non-training replay source")
            groups[row["metadata"].get("category","unknown")].append(row)
        for group in groups.values():
            group.sort(key=lambda r:hashlib.sha256(content(r).encode()).hexdigest())
        chosen=[]
        while len(chosen)<count:
            progress=False
            for category in sorted(groups):
                while groups[category]:
                    row=groups[category].pop(0)
                    fp=content(row)
                    if fp in seen or row["record_id"] in ids:
                        continue
                    seen.add(fp); ids.add(row["record_id"]); chosen.append(row); progress=True; break
                if len(chosen)==count: break
            if not progress:
                raise ValueError("insufficient diverse replay")
        for row in chosen:
            copy=json.loads(json.dumps(row))
            copy["metadata"]["p513_origin"]=origin
            copy["metadata"]["p513_replay"]=True
            replay.append(copy)
        provenance.append({
            "origin":origin,"path":rel,"sha256":sha(path),"count":count,
            "record_ids":[r["record_id"] for r in chosen],
            "categories":sorted({r["metadata"].get("category","unknown") for r in chosen}),
        })
    return replay,provenance

def protected_eval_identity():
    if not PROTECTED_EVAL.is_file():
        return {"path":str(PROTECTED_EVAL),"available":False}
    x=json.loads(PROTECTED_EVAL.read_text(encoding="utf-8"))
    question_hashes=[
        hashlib.sha256(" ".join(c["question"].casefold().split()).encode()).hexdigest()
        for c in x["cases"]
    ]
    return {
        "path":str(PROTECTED_EVAL),
        "available":True,
        "sha256":sha(PROTECTED_EVAL),
        "case_count":len(x["cases"]),
        "normalized_question_sha256":question_hashes,
    }

def build():
    new=new_records()
    replay,provenance=select_replay()
    smoke=smoke_records()
    combined=new+replay
    combined.sort(key=lambda r:hashlib.sha256(("P513:"+r["record_id"]).encode()).hexdigest())
    return new,combined,smoke,provenance

def prepare():
    from validate_wvc_specialization_v1 import validate_rows
    new,combined,smoke,provenance=build()
    report=validate_rows(new,combined,smoke)
    for name,rows in zip(FILES,(new,combined,smoke)):
        (HERE/name).write_text("".join(
            json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n" for r in rows
        ),encoding="utf-8")
    manifest={
        "schema_version":1,
        "stage":"P5.13",
        "adapter_id":"wvc-specialization-v1",
        "base_model":"Qwen/Qwen3.8-27B",
        "parent_stage":"P5.11",
        "parent_adapter":PARENT,
        "adapter_kind":"standalone_lora_not_merged",
        "quality_acceptance":QUALITY,
        "protected_eval_material_used":False,
        "protected_eval":protected_eval_identity(),
        "counts":{"new":96,"replay":64,"combined":160,"smoke":12},
        "replay_fraction":0.4,
        "training":{"microsteps":160,"optimizer_steps":40,"group_size":4,"lr":1e-5,
                    "max_length":768,"lora_r":8,"optimizer":"fresh AdamW",
                    "base_dtype":"bfloat16","enable_thinking":False},
        "files":{name:sha(HERE/name) for name in FILES},
        "sources":provenance,
        "validation":report,
        "authoring_sha256":{name:sha(HERE/name) for name in ("curriculum.py","smoke_cases.py")},
    }
    (HERE/"wvc_specialization_v1.manifest.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"
    )
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    print("P5_13_WVC_DATASET_GATE=PASS")

if __name__=="__main__":
    prepare()
