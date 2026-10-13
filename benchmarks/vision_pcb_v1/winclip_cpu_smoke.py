#!/usr/bin/env python3
"""CPU-only WinCLIP smoke test (NOT a benchmark quality result).

Uses official VisA images. Saves raw uncalibrated prediction scores and
metadata, not automatically comparable to seven-candidate leaderboard.
"""
import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from importlib.metadata import version
from PIL import Image
import torch
from torchvision.transforms.functional import pil_to_tensor
from anomalib.models.image.winclip.torch_model import WinClipModel, BACKBONE, PRETRAINED

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ground-truth", type=Path, required=True)
    ap.add_argument("--image-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--samples", type=int, default=2)
    args = ap.parse_args()
    if args.out.exists():
        raise RuntimeError("refuse to overwrite smoke report")
    torch.set_num_threads(2)
    rows = [json.loads(x) for x in args.ground_truth.read_text().splitlines()]
    candidates = [r for r in rows if r["split"] == "challenge"]
    chosen = []
    for label in ("normal", "anomaly"):
        chosen.extend([r for r in candidates if r["label"] == label][:args.samples])
    if len(chosen) < 2:
        raise ValueError("need both normal and anomalous real images")
    print("LOADING_CHECKPOINT", BACKBONE, PRETRAINED, flush=True)
    start = time.monotonic()
    model = WinClipModel(class_name="printed circuit board", apply_transform=True).eval()
    print("CHECKPOINT_LOADED elapsed_s", round(time.monotonic()-start,2), flush=True)
    records = []
    for r in chosen:
        image_path = (args.image_root / r["image_path"]).resolve(strict=True)
        if not image_path.is_relative_to(args.image_root.resolve()):
            raise ValueError("image escaped root")
        with Image.open(image_path) as img:
            t = pil_to_tensor(img.convert("RGB")).float() / 255
        ts = time.monotonic()
        with torch.inference_mode():
            prediction = model(t.unsqueeze(0))
        score = float(prediction.pred_score.squeeze().cpu().item())
        amap = prediction.anomaly_map
        records.append({"sample_id": r["sample_id"], "label_for_smoke_only": r["label"],
                        "score": score, "map_shape": list(amap.shape),
                        "wall_seconds": time.monotonic()-ts})
        print("SAMPLE",records[-1], flush=True)
    out = {"status":"SMOKE_ONLY_NOT_BENCHMARK", "model_id":"winclip",
           "checkpoint_backbone":BACKBONE,"checkpoint_pretrained":PRETRAINED,
           "class_prompt":"printed circuit board","k_shot":0,
           "torch":torch.__version__,"anomalib":version("anomalib"),
           "open_clip":version("open-clip-torch"),"python":sys.version.split()[0],
           "platform":platform.platform(),"device":"cpu", "cpu_threads":2,
           "notes":"No threshold calibration. No quality estimate. Raw image-level scores only; 240x240 CLIP processing loses microdetail.",
           "records":records}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print("WINCLIP_CPU_SMOKE=PASS", flush=True)

if __name__ == "__main__":
    main()
