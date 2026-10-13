#!/usr/bin/env python3
"""The same WinCLIP checkpoint and image preprocessing on CPU or ROCm GPU.

No access to Ollama or ComfyUI; run GPU variant only inside an authorized
manual maintenance window. Does NOT provide full B1 accuracy statistics.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import torch
from PIL import Image
from torchvision.transforms.functional import pil_to_tensor
from anomalib.models.image.winclip.torch_model import WinClipModel, BACKBONE,PRETRAINED

WEIGHTS_SHA256="8fb26589b9a8bab2e7a683d280e48df89b8e742f3a82132707282620b36facba"

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(2**20),b""):h.update(b)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ground-truth",type=Path,required=True)
    p.add_argument("--image-root",type=Path,required=True)
    p.add_argument("--checkpoint",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--device",choices=["cpu","cuda"],required=True)
    p.add_argument("--limit",type=int,default=5)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError("no overwrite allowed")
    if not 1<=args.limit<=50:raise ValueError("limit must be 1..50")
    if sha(args.checkpoint)!=WEIGHTS_SHA256:raise ValueError("checkpoint SHA256 mismatch")
    if args.device=="cuda" and (not torch.cuda.is_available() or not torch.version.hip):
        raise RuntimeError("HIP device not ready")
    torch.set_num_threads(2)
    model=WinClipModel(class_name="printed circuit board",apply_transform=False).eval().to(args.device)
    base=args.image_root.resolve(strict=True)
    rows=[json.loads(line) for line in args.ground_truth.read_text().splitlines()]
    labels=[]
    # Choose exact, stable list across devices: same sample_id ordering and classes.
    for label in ("normal","anomaly"):
        labels.extend(sorted((r for r in rows if r["split"]=="holdout" and r["label"]==label),
                      key=lambda x:x["sample_id"])[:args.limit])
    records=[]
    started=time.perf_counter()
    for i,row in enumerate(labels,1):
        fp=(base/row["image_path"]).resolve(strict=True)
        if not fp.is_relative_to(base) or sha(fp)!=row["sha256"]:
            raise ValueError("image provenance mismatch")
        with Image.open(fp) as im:
            rgb=im.convert("RGB")
            full=pil_to_tensor(rgb).float()/255.0
        # Same OpenCLIP transform on CPU for both devices; only model tensors move.
        tensor=model.transform(full).unsqueeze(0).to(args.device)
        st=time.perf_counter()
        with torch.inference_mode():
            pred=model(tensor)
        if args.device=="cuda":torch.cuda.synchronize()
        seconds=time.perf_counter()-st
        score=float(pred.pred_score.squeeze().item())
        if not 0<=score<=1:raise RuntimeError("non-finite or nonprobabilistic anomaly score")
        records.append({"sample_id":row["sample_id"],"label_for_report_only":row["label"],
                        "score":score,"forward_seconds":round(seconds,6)})
        print(f"DEVICE={args.device} SAMPLE={i}/{len(labels)} score={score:.7f} time={seconds:.3f}s",flush=True)
    runtime={
        "status":"DEVICE_SMOKE_NOT_FULL_BENCHMARK",
        "device":args.device,"n_images":len(labels),"model":"winclip",
        "checkpoint_sha256":WEIGHTS_SHA256,"torch":torch.__version__,
        "torch_hip":torch.version.hip,"backbone":BACKBONE,"pretrained":PRETRAINED,
        "prompt":"printed circuit board",
        "preprocessing":"model.transform CPU, normalized 240x240",
        "wall_seconds":round(time.perf_counter()-started,4),
        "peak_gpu_allocated_bytes":int(torch.cuda.max_memory_allocated()) if args.device=="cuda" else None,
        "records":records
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x") as f:json.dump(runtime,f,indent=2);f.write("\n")
    print("WINCLIP_DEVICE_SMOKE=PASS",flush=True)

if __name__=="__main__": main()
