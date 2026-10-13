#!/usr/bin/env python3
"""Read-only MiniCPM-V 4.7 1B CPU smoke on a real VisA PCB (NOT scored benchmark)."""
from __future__ import annotations
import argparse
import hashlib
import json
import time
from pathlib import Path
import torch
from PIL import Image
from transformers import AutoModelForImageTextToText,AutoProcessor

MODEL_SHA256="8c4921ac83182c85190ad10c3aeb118d51e385d2d98ec13b88b514bbf6cac002"
MODEL_REVISION="984a89aafcd5160164f4f0d04b4be0f4eec03cb8"
PROMPT=("Inspect the visible printed circuit board for physical surface defects. "
        "Answer briefly: is there visual evidence of damage, what specifically is visible, "
        "and what cannot be determined from the image? Do not guess electrical failure. "
        "If uncertain, explicitly say so.")

def sha256(path:Path):
    h=hashlib.sha256()
    with path.open('rb') as fp:
        for b in iter(lambda:fp.read(2**20),b''):h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--model-dir',type=Path,required=True)
    ap.add_argument('--image-root',type=Path,required=True)
    ap.add_argument('--ground-truth',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--max-new-tokens',type=int,default=80)
    args=ap.parse_args()
    if args.out.exists():raise FileExistsError("no overwrite")
    if not (1<=args.max_new_tokens<=128):raise ValueError("token budget 1..128")
    torch.set_num_threads(2)
    weight_file=args.model_dir/'model.safetensors'
    actual=sha256(weight_file)
    if actual!=MODEL_SHA256:raise ValueError("model SHA256 mismatch")
    start=time.monotonic()
    processor=AutoProcessor.from_pretrained(str(args.model_dir),local_files_only=True)
    model=AutoModelForImageTextToText.from_pretrained(
        str(args.model_dir),torch_dtype=torch.float32,device_map="cpu",
        low_cpu_mem_usage=True,local_files_only=True,
    ).eval()
    startup_seconds=time.monotonic()-start
    print("MINICPM_MODEL_LOADED",round(startup_seconds,2),flush=True)
    rows=[json.loads(x) for x in args.ground_truth.read_text().splitlines()]
    images=[]
    for label in ("normal","anomaly"):
        image_row=next(r for r in rows if r["split"]=="challenge" and r["label"]==label)
        image_path=(args.image_root/image_row['image_path']).resolve(strict=True)
        if not image_path.is_relative_to(args.image_root.resolve()):
            raise ValueError("image path traversal")
        with Image.open(image_path) as im:
            image=im.convert("RGB")
            # Fidelity as measured by the image processor, not manual 224 px reduction.
            msg=[{"role":"user","content":[{"type":"image","image":image},
                  {"type":"text","text":PROMPT}]}]
            t0=time.monotonic()
            inputs=processor.apply_chat_template(msg,tokenize=True,
                add_generation_prompt=True,return_dict=True,return_tensors='pt',
                downsample_mode="16x",max_slice_nums=4,enable_thinking=False)
            with torch.inference_mode():
                generated=model.generate(**inputs,max_new_tokens=args.max_new_tokens,
                        do_sample=False,downsample_mode="16x")
            new_ids=generated[:,inputs.input_ids.shape[-1]:]
            answer=processor.batch_decode(new_ids,skip_special_tokens=True,
                        clean_up_tokenization_spaces=False)[0]
            seconds=time.monotonic()-t0
        entry={"sample_id":image_row["sample_id"],"ground_truth_label_for_audit_only":label,
               "input_size":list(image.size),"response":answer,"seconds":round(seconds,2)}
        images.append(entry)
        print("IMAGE_RESPONSE",json.dumps(entry,ensure_ascii=False),flush=True)
    report={"status":"MINICPM_4_7_1B_CPU_SMOKE_NOT_BENCHMARK","model_revision":MODEL_REVISION,
        "checkpoint_sha256":MODEL_SHA256,"runtime":"torch-cpu-float32",
        "model_startup_seconds":round(startup_seconds,2),"prompt":PROMPT,
        "image_processor":"downsample_mode=16x,max_slice_nums=4",
        "images":images,
        "limitations":"Not scored or calibrated; 2 samples cannot establish recall/FPR. Responses are qualitative and require expert review."}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("MINICPM47_1B_CPU_SMOKE=PASS",flush=True)

if __name__=="__main__":
    main()
