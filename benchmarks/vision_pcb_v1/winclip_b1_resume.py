#!/usr/bin/env python3
"""Incremental WinCLIP B1 CPU runner: complete split, resumable and traceable.

Outputs are NOT benchmarks until full split predictions, normal calibration,
holdout/challenge scoring and expert error analysis all pass.
"""
from __future__ import annotations
import argparse
from itertools import zip_longest
import hashlib
import json
import os
from pathlib import Path
import time

from b1_journal import Journal,sha256_file,encode,immutable
from tile_policy import tile_rectangles,aggregate_max

MODEL_SHA="8fb26589b9a8bab2e7a683d280e48df89b8e742f3a82132707282620b36facba"
PROMPT="printed circuit board"

def run(args):
    os.environ["HF_HUB_OFFLINE"]="1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"]="1"
    os.environ["TOKENIZERS_PARALLELISM"]="false"
    import numpy as np
    import torch
    import torch.nn.functional as F
    from PIL import Image
    from torchvision.transforms.functional import pil_to_tensor
    from importlib.metadata import version
    from anomalib.models.image.winclip.torch_model import WinClipModel,BACKBONE,PRETRAINED
    if torch.cuda.is_available():
        print("CUDA available but explicitly disabled: CPU-only",flush=True)
    torch.set_num_threads(args.threads)
    if sha256_file(args.checkpoint)!=MODEL_SHA:
        raise RuntimeError("checkpoint checksum mismatch")
    source_hash=sha256_file(args.ground_truth)
    rows=[json.loads(x) for x in args.ground_truth.read_text().splitlines() if x.strip()]
    selected=sorted((x for x in rows if x["split"]==args.split),key=lambda r:r["sample_id"])
    expected={r["sample_id"] for r in selected}
    if len(expected)!=len(selected):raise ValueError("duplicate IDs in GT")
    config={"schema_version":1,"model_id":"winclip","checkpoint_sha256":MODEL_SHA,
            "checkpoint_backbone":BACKBONE,"checkpoint_pretrained":PRETRAINED,
            "ground_truth_sha256":source_hash,
            "split":args.split,"expected_count":len(selected),
            "sample_ids_sha256":hashlib.sha256(encode(sorted(expected))).hexdigest(),
            "device":args.device,"cpu_threads":args.threads,
            "preprocessing_mode":args.mode,
            "class_prompt":PROMPT,
            "tile_size":args.tile_size if args.mode=="tiled" else None,
            "tile_overlap":args.overlap if args.mode=="tiled" else None,
            "aggregation":"max_global_plus_tiles" if args.mode=="tiled" else "whole_image",
            "anomaly_map_resolution":256 if args.save_maps and args.mode=="global" else None,
            "torch":torch.__version__,"anomalib":version("anomalib"),"open_clip":version("open-clip-torch"),
            "note":"Original image resized internally to 240x240 for whole-image WinCLIP."}
    if args.mode=="tiled" and args.save_maps:
        raise ValueError("tiled anomaly-map stitching is not implemented")
    j=Journal(args.out,config,expected)
    started=time.monotonic()
    try:
        done,total=j.progress()
        print(f"B1_INITIAL={done}/{total} model=winclip split={args.split} mode={args.mode}",flush=True)
        if done==total:
            print("B1_ALREADY_COMPLETE="+str(j.finalize()),flush=True)
            return
        if args.device == "cuda":
            if not torch.version.hip or not torch.cuda.is_available():
                raise RuntimeError("ROCm GPU unavailable: fail closed")
        model=WinClipModel(class_name=PROMPT,apply_transform=(args.device=="cpu")).eval().to(args.device)
        new=0
        base=args.image_root.resolve(strict=True)
        # Interleave anomaly and normal samples to produce informative checkpoints.
        # Ordering has no influence on frozen scores and must not change the manifest.
        normals=[r for r in selected if r["label"]=="normal"]
        anomalies=[r for r in selected if r["label"]=="anomaly"]
        ordered=[r for pair in zip_longest(normals,anomalies) for r in pair if r is not None]
        for row in ordered:
            if j.read(row["sample_id"]) is not None:continue
            if args.max_new is not None and new>=args.max_new:break
            if args.time_budget is not None and new>0 and time.monotonic()-started>args.time_budget:break
            # Exit rather than make interactive AI service compete with sustained CPU demand.
            if os.getloadavg()[0]>args.max_load:
                print(f"RESOURCE_LOAD_HIGH={os.getloadavg()[0]:.2f}; stopping cleanly",flush=True)
                break
            image_file=(base/row["image_path"]).resolve(strict=True)
            if not image_file.is_relative_to(base):raise RuntimeError("image path escape")
            digest=sha256_file(image_file)
            if digest!=row["sha256"]:raise RuntimeError("source image SHA mismatch: "+row["sample_id"])
            tic=time.monotonic()
            with Image.open(image_file) as file:
                rgb=file.convert("RGB")
                images=[rgb]
                if args.mode=="tiled":
                    rects=tile_rectangles(*rgb.size,args.tile_size,args.overlap)
                    images.extend(rgb.crop(box) for box in rects)
                scores=[]
                full_map=None
                with torch.inference_mode():
                    for index, img in enumerate(images):
                        t=pil_to_tensor(img).float()/255
                        batch=(model.transform(t).unsqueeze(0).to("cuda") if args.device=="cuda"
                               else t.unsqueeze(0))
                        pred=model(batch)
                        if args.device=="cuda":torch.cuda.synchronize()
                        sc=float(pred.pred_score.squeeze().item())
                        if not 0<=sc<=1:raise ValueError("invalid model score")
                        scores.append(sc)
                        if index==0 and args.save_maps:
                            data=pred.anomaly_map.float().cpu()
                            if data.ndim==3:data=data.unsqueeze(1)
                            full_map=F.interpolate(data,size=(256,256),mode="bilinear",align_corners=False)[0,0].cpu().numpy().astype("float32")
            score=aggregate_max(scores[0],scores[1:]) if args.mode=="tiled" else scores[0]
            output={"sample_id":row["sample_id"],"model_id":"winclip",
                    "localization_mode":"none","regions":[],"image_score":score,
                    "image_sha256":digest,"preprocessing_mode":args.mode,
                    "runtime_seconds":round(time.monotonic()-tic,4)}
            if args.save_maps:
                name=hashlib.sha256(row["sample_id"].encode()).hexdigest()+".npz"
                mapfile=args.out/"maps"/name
                mapfile.parent.mkdir(parents=True,exist_ok=True)
                if mapfile.exists():
                    # No committed journal record exists, so this is an orphan
                    # from a crash between map write and record commit.
                    mapfile.unlink()
                tmp=mapfile.with_suffix(".pending")
                tmp.unlink(missing_ok=True)
                with tmp.open("xb") as stream:
                    np.savez_compressed(stream,map=full_map)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp,mapfile)
                output["map_sha256"]=sha256_file(mapfile)
            j.write(output)
            new+=1
            if new==1 or new%8==0:
                curr,_=j.progress()
                print(f"B1_PROGRESS={curr}/{total} NEW={new} AVG_WALL={round((time.monotonic()-started)/new,2)}s",flush=True)
        complete=j.finalize()
        now,total=j.progress()
        print(f"B1_EXIT completed={complete} done={now}/{total} new={new} elapsed={round(time.monotonic()-started,1)}s",flush=True)
    finally:
        j.close()
        if args.device=="cuda":
            torch.cuda.empty_cache()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ground-truth",type=Path,required=True)
    p.add_argument("--image-root",type=Path,required=True)
    p.add_argument("--checkpoint",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--split",choices=["calibration","holdout","challenge"],required=True)
    p.add_argument("--mode",choices=["global","tiled"],default="global")
    p.add_argument("--device",choices=["cpu","cuda"],default="cpu")
    p.add_argument("--save-maps",action="store_true")
    p.add_argument("--tile-size",type=int,default=640)
    p.add_argument("--overlap",type=float,default=.25)
    p.add_argument("--threads",type=int,default=2)
    p.add_argument("--max-new",type=int)
    p.add_argument("--time-budget",type=int,default=180)
    p.add_argument("--max-load",type=float,default=12.0)
    args=p.parse_args()
    if args.threads not in range(1,5) or args.max_new is not None and args.max_new<1:
        p.error("threads 1..4, max-new >=1")
    if args.time_budget is not None and args.time_budget<15:p.error("time-budget>=15")
    if args.max_load<1:p.error("max-load>=1")
    run(args)

if __name__=="__main__":main()
