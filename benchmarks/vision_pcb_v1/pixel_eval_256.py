#!/usr/bin/env python3
"""Optional pixel-level WinCLIP anomaly metrics from frozen per-image maps.

Approximate AU-PRO is measured at 256x256, against original binary masks
resized by nearest-neighbor. Never misrepresent this as full-resolution AUPRO.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage
from sklearn.metrics import average_precision_score,roc_auc_score

from b1_journal import sha256_file,immutable,encode

SIZE=256

def map_file(sample_id:str,run_dir:Path)->Path:
    return run_dir/"maps"/(hashlib.sha256(sample_id.encode()).hexdigest()+".npz")

def pixel_metrics(scores:list[np.ndarray],masks:list[np.ndarray],max_fpr:float=.3,grid:int=101)->dict:
    if len(scores)!=len(masks) or not scores:
        raise ValueError("missing or mismatched pixel maps/masks")
    normal=[]
    positives=[]
    all_scores=[]
    all_masks=[]
    for score,mask in zip(scores,masks):
        if score.shape!=(SIZE,SIZE) or mask.shape!=(SIZE,SIZE):
            raise ValueError("wrong normalized map resolution")
        if not np.isfinite(score).all():
            raise ValueError("nonfinite map values")
        mask=mask.astype(bool)
        all_scores.append(score.flatten())
        all_masks.append(mask.flatten())
        normal.append(score[~mask])
        labels,count=ndimage.label(mask,structure=ndimage.generate_binary_structure(2,1))
        for i in range(1,count+1):
            positives.append(score[labels==i])
    s=np.concatenate(all_scores).astype(np.float32)
    y=np.concatenate(all_masks).astype(np.uint8)
    if y.sum()==0 or y.sum()==len(y):
        raise ValueError("pixel metrics require both classes")
    normals=np.concatenate(normal).astype(np.float32)
    if not positives:
        raise ValueError("no connected anomaly region")
    ordered=np.sort(normals)
    n=len(ordered)
    fs=np.linspace(0,max_fpr,grid,dtype=np.float64)
    # select quantile thresholds with strict > comparison and explicit 0-FPR endpoint
    thresholds=np.array([
        float(ordered[min(n-1,max(0,int(np.ceil((1-f)*n)-1)))])
        for f in fs],dtype=np.float64)
    fpr=np.array([(n-np.searchsorted(ordered,t,side="right"))/n for t in thresholds])
    pro=np.array([np.mean([np.mean(region>t) for region in positives]) for t in thresholds])
    points={}
    for f,p in zip(fpr,pro):
        points[float(f)]=max(points.get(float(f),0),float(p))
    x=np.array(sorted(points))
    v=np.array([points[float(t)] for t in x])
    # limit integration to measured support; no optimistic extrapolation.
    if x[0]>0:x=np.insert(x,0,0.);v=np.insert(v,0,0.)
    end=min(max_fpr,float(x[-1]))
    if end<=0 or end < max_fpr-0.001:
        # Do not extrapolate past the measured FPR support when the normal
        # score distribution has ties (e.g. every normal pixel identical).
        aupro=None
    else:
        indices=x<=end
        xx=x[indices]
        vv=v[indices]
        if xx[-1]<end:
            xx=np.append(xx,end);vv=np.append(vv,float(np.interp(end,x,v)))
        aupro=float(np.trapezoid(vv,xx)/end)
    return {"pixel_auroc":float(roc_auc_score(y,s)),
            "pixel_average_precision":float(average_precision_score(y,s)),
            "aupro_approx_256":aupro,
            "aupro_fpr_cap":max_fpr,
            "aupro_status":"estimated" if aupro is not None else "fpr_coverage_insufficient",
            "observed_max_fpr":end,
            "connected_regions":len(positives),
            "pixel_positive_count":int(y.sum()),
            "pixel_negative_count":int(len(y)-y.sum()),
            "maps":len(scores),
            "method":"AU-PRO approx on resized 256x256 maps, strict >, quantile grid, four-connected GT",
            "threshold_grid":grid}

def run(args):
    full_gt=[json.loads(x) for x in args.gt.read_text().splitlines() if x.strip()]
    target=sorted((x for x in full_gt if x["split"]==args.split),key=lambda x:x["sample_id"])
    pred_file=args.run_dir/"predictions.jsonl"
    if not pred_file.is_file():raise FileNotFoundError("full split not yet completed; no pixel quality report")
    preds=[json.loads(x) for x in pred_file.read_text().splitlines()]
    if {x["sample_id"] for x in preds}!={x["sample_id"] for x in target} or len(preds)!=len(target):
        raise ValueError("predictions do not exactly cover split")
    cache=json.loads((args.run_dir/"config.json").read_text())
    if cache.get("ground_truth_sha256")!=sha256_file(args.gt) or cache.get("split")!=args.split or cache.get("anomaly_map_resolution")!=SIZE:
        raise ValueError("run configuration mismatch")
    annotations={x["sample_id"]:x for x in (json.loads(line) for line in args.annotation_evidence.read_text().splitlines())}
    scores=[];masks=[]
    root=args.image_root.resolve(strict=True)
    for i,r in enumerate(target):
        sid=r["sample_id"]
        rec=json.loads((args.run_dir/"records"/(hashlib.sha256(sid.encode()).hexdigest()+".json")).read_text())
        mp=map_file(sid,args.run_dir)
        if sha256_file(mp)!=rec.get("map_sha256"):
            raise ValueError("anomaly map changed for "+sid)
        with np.load(mp,allow_pickle=False) as z:
            score=z["map"].copy()
        if score.shape!=(SIZE,SIZE):raise ValueError("anomaly map shape mismatch")
        evidence=annotations.get(sid)
        if not evidence:raise ValueError("missing mask provenance")
        mask_path=evidence["mask_path"]
        if r["label"]=="normal":
            if mask_path:raise ValueError("normal image with defect mask")
            mask=np.zeros((SIZE,SIZE),dtype=bool)
        else:
            if not mask_path:raise ValueError("anomaly without pixel mask")
            mask_file=(root/mask_path).resolve(strict=True)
            if not mask_file.is_relative_to(root) or sha256_file(mask_file)!=evidence["mask_sha256"]:
                raise ValueError("source mask provenance mismatch")
            with Image.open(mask_file) as m:
                mask=np.asarray(m.convert("L").resize((SIZE,SIZE),Image.Resampling.NEAREST))>0
            if not mask.any():raise ValueError("downsampling erased defect mask")
        scores.append(score)
        masks.append(mask)
        if (i+1)%100==0:print(f"MAPS_READ={i+1}/{len(target)}",flush=True)
    result={"schema_version":1,"dataset_sha256":sha256_file(args.gt),
            "prediction_sha256":sha256_file(pred_file),"split":args.split,
            "map_resolution":[SIZE,SIZE],"metrics":pixel_metrics(scores,masks,args.max_fpr)}
    immutable(args.out,encode(result))
    print("PIXEL_METRICS=PASS split="+args.split+" auPRO256="+str(result["metrics"]["aupro_approx_256"]),flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--gt",type=Path,required=True)
    p.add_argument("--annotation-evidence",type=Path,required=True)
    p.add_argument("--image-root",type=Path,required=True)
    p.add_argument("--run-dir",type=Path,required=True)
    p.add_argument("--split",choices=["holdout","challenge"],required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--max-fpr",type=float,default=.3)
    args=p.parse_args()
    if not 0<args.max_fpr<=.5:p.error("max-fpr must be (0,0.5]")
    run(args)

if __name__=="__main__":main()
