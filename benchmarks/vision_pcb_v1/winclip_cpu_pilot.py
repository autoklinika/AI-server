#!/usr/bin/env python3
"""Reproducible WinCLIP CPU B1 pilot on a deliberately tiny, stratified subset.

Not a production-grade benchmark; only a contract/inference integration trial.
"""
import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path
from importlib.metadata import version
from PIL import Image
import torch
from torchvision.transforms.functional import pil_to_tensor
from anomalib.models.image.winclip.torch_model import WinClipModel, BACKBONE, PRETRAINED

def immutable(path, text):
    if path.exists():
        if path.read_text() != text:
            raise FileExistsError(f"refuse to overwrite existing artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ground-truth",type=Path,required=True)
    p.add_argument("--image-root",type=Path,required=True)
    p.add_argument("--out-dir",type=Path,required=True)
    p.add_argument("--per-label",type=int,default=8)
    args=p.parse_args()
    if not 1 <= args.per_label <= 20:
        p.error("per-label must be 1..20")
    torch.set_num_threads(2)
    seed=20261013
    rng=random.Random(seed)
    all_rows=[json.loads(x) for x in args.ground_truth.read_text().splitlines()]
    # Group by split and label; fixed RNG seed, stable sort
    subset=[]
    for split in ("train","calibration","holdout","challenge"):
        labels=("normal",) if split=="train" else ("normal","anomaly")
        for label in labels:
            group=sorted((r for r in all_rows if r["split"]==split and r["label"]==label), key=lambda x:x["sample_id"])
            subset.extend(rng.sample(group,args.per_label))
    subset.sort(key=lambda r:r["sample_id"])
    gt_text="".join(json.dumps(r,sort_keys=True,ensure_ascii=False)+"\n" for r in subset)
    immutable(args.out_dir/"pilot_ground_truth.jsonl",gt_text)
    print("PILOT_SAMPLES",len(subset),"SPLIT_COUNTS",[(sp,len([r for r in subset if r['split']==sp])) for sp in ("train","calibration","holdout","challenge")],flush=True)
    model=WinClipModel(class_name="printed circuit board",apply_transform=True).eval()
    metadata={"status":"B1_PILOT_SMALL_SAMPLE","model":"winclip","checkpoint":PRETRAINED,
              "backbone":BACKBONE,"class_prompt":"printed circuit board",
              "split_source_sha256":hashlib.sha256(args.ground_truth.read_bytes()).hexdigest(),
              "subset_ground_truth_sha256":hashlib.sha256(gt_text.encode()).hexdigest(),
              "selection_seed":seed,"per_label":args.per_label,
              "device":"cpu","threads":2,"no_training":True,
              "torch":torch.__version__,"anomalib":version("anomalib"),
              "open_clip":version("open-clip-torch"),"python":sys.version.split()[0],
              "disclaimer":"Exploratory only, tiny sample, threshold unstable, no pixel/box metrics; NOT production result"}
    for split in ("calibration","holdout","challenge"):
        selected=[r for r in subset if r["split"]==split]
        predictions=[]
        start=time.monotonic()
        for idx,r in enumerate(selected,1):
            fp=(args.image_root/r["image_path"]).resolve(strict=True)
            if not fp.is_relative_to(args.image_root.resolve()):
                raise ValueError("path escape")
            with Image.open(fp) as img:
                image=pil_to_tensor(img.convert("RGB")).float()/255
            with torch.inference_mode():
                prediction=model(image.unsqueeze(0))
            score=float(prediction.pred_score.squeeze().item())
            if not 0<=score<=1:
                raise RuntimeError("WinClip image score outside [0,1]")
            predictions.append({"sample_id":r["sample_id"],"model_id":"winclip",
                                "image_score":score,"localization_mode":"none","regions":[]})
            if idx%4==0:
                print(f"{split.upper()}_PROGRESS={idx}/{len(selected)}",flush=True)
        pred_text="".join(json.dumps(p,sort_keys=True)+"\n" for p in predictions)
        immutable(args.out_dir/f"winclip_{split}.jsonl",pred_text)
        metadata[split]={"images":len(selected),"elapsed_seconds":round(time.monotonic()-start,2),
                         "predictions_sha256":hashlib.sha256(pred_text.encode()).hexdigest()}
    immutable(args.out_dir/"pilot_metadata.json",json.dumps(metadata,ensure_ascii=False,indent=2)+"\n")
    print("WINCLIP_PILOT_INFERENCE=PASS",flush=True)

if __name__=="__main__":
    main()
