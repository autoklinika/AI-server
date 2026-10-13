#!/usr/bin/env python3
"""Snapshot a balanced B1 checkpoint from already completed, hash-verified records.

The selection is made without consulting model scores; it is NOT a final test.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from b1_journal import Journal,encode,immutable,sha256_file

def build(gt:Path,run_root:Path,out:Path,per_label:int)->dict:
    if per_label<5:raise ValueError("per-label must be >=5")
    samples=[json.loads(x) for x in gt.read_text().splitlines() if x.strip()]
    selection=[]
    predictions={}
    supports={}
    for split in ("calibration","holdout","challenge"):
        subset=sorted((x for x in samples if x["split"]==split),key=lambda x:x["sample_id"])
        config=json.loads((run_root/split/"config.json").read_text())
        expected=set(x["sample_id"] for x in subset)
        if config.get("ground_truth_sha256")!=sha256_file(gt):
            raise ValueError("journal source ground truth has changed")
        journal=Journal(run_root/split,config,expected)
        try:
            candidates=[]
            for row in subset:
                cached=journal.read(row["sample_id"])
                if cached:
                    if cached["image_sha256"]!=row["sha256"]:raise ValueError("image hash changed")
                    candidates.append((row,cached))
            by_label={label:sorted((c for c in candidates if c[0]["label"]==label),key=lambda c:c[0]["sample_id"])[:per_label]
                      for label in ("normal","anomaly")}
            if any(len(v)!=per_label for v in by_label.values()):
                raise ValueError(f"insufficient real evidence in {split}: "+str({k:len(v) for k,v in by_label.items()}))
            picked=sorted([*by_label["normal"],*by_label["anomaly"]],key=lambda t:t[0]["sample_id"])
            selection.extend(r for r,_ in picked)
            predictions[split]=[
                {k:record[k] for k in ("sample_id","model_id","image_score","localization_mode","regions")}
                for _,record in picked]
            supports[split]={"all_completed":len(candidates),"picked":len(picked),
                             "normal":per_label,"anomaly":per_label}
        finally:
            journal.close()
    raw_gt=b"".join(encode(row) for row in sorted(selection,key=lambda x:x["sample_id"]))
    immutable(out/"ground_truth.jsonl",raw_gt)
    for split,preds in predictions.items():
        immutable(out/f"winclip_{split}.jsonl",b"".join(encode(p) for p in preds))
    report={"status":"NONFINAL_CHECKPOINT_NOT_PRODUCTION_B1",
            "per_split_label":per_label,
            "selection":"first sample_id sorted per label from completed subset; no score-based cherry picking; nonrandom sampling",
            "source_ground_truth_sha256":sha256_file(gt),
            "checkpoint_gt_sha256":hashlib.sha256(raw_gt).hexdigest(),
            "split_status":supports,
            "limitations":"Only a limited, non-random checkpoint. Split source and model outputs are not the complete VisA folds.",
            "model":"winclip"}
    immutable(out/"snapshot.json",encode(report))
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ground-truth",type=Path,required=True)
    p.add_argument("--run-root",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--per-label",type=int,default=40)
    a=p.parse_args()
    report=build(a.ground_truth,a.run_root,a.out,a.per_label)
    print("B1_SNAPSHOT=PASS "+json.dumps(report["split_status"]),flush=True)

if __name__=="__main__":main()
