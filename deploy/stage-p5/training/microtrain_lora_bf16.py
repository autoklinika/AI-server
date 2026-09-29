#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, random, time
from pathlib import Path

import numpy as np
import psutil
import torch
from peft import LoraConfig, PeftConfig, get_peft_model
from safetensors import safe_open
from transformers import AutoModelForMultimodalLM, AutoTokenizer
import transformers, peft, trl, accelerate, datasets

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def load_rows(path: Path):
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not rows:
        raise RuntimeError("empty microtrain dataset")
    return rows

def build_example(tok, row, max_length):
    prompt = [{"role":"system","content":row["system"]},{"role":"user","content":row["user"]}]
    full = prompt + [{"role":"assistant","content":row["assistant"]}]
    prompt_text = tok.apply_chat_template(prompt, tokenize=False, add_generation_prompt=True)
    full_text = tok.apply_chat_template(full, tokenize=False, add_generation_prompt=False)
    prompt_ids = tok(prompt_text, add_special_tokens=False)["input_ids"]
    enc = tok(full_text, add_special_tokens=False, truncation=True, max_length=max_length)
    ids = enc["input_ids"]
    labels = list(ids)
    masked = min(len(prompt_ids), len(labels))
    labels[:masked] = [-100] * masked
    if all(x == -100 for x in labels):
        raise RuntimeError("assistant target truncated completely")
    return {
        "input_ids": torch.tensor([ids], dtype=torch.long, device="cuda"),
        "attention_mask": torch.ones((1, len(ids)), dtype=torch.long, device="cuda"),
        "labels": torch.tensor([labels], dtype=torch.long, device="cuda"),
        "tokens": len(ids),
        "target_tokens": sum(x != -100 for x in labels),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--max-length", type=int, default=256)
    ap.add_argument("--seed", type=int, default=20260929)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lora-r", type=int, default=4)
    args = ap.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)

    dataset_path = Path(args.dataset)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows = load_rows(dataset_path)

    tok = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    host_ram_before = psutil.virtual_memory().used
    load_t0 = time.perf_counter()
    model = AutoModelForMultimodalLM.from_pretrained(
        args.model_dir,
        local_files_only=True,
        dtype=torch.bfloat16,
        device_map={"": 0},
        low_cpu_mem_usage=True,
    )
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_t0

    if hasattr(model.config, "use_cache"):
        model.config.use_cache = False
    if hasattr(model.config, "text_config") and hasattr(model.config.text_config, "use_cache"):
        model.config.text_config.use_cache = False

    linear = []
    for name, module in model.named_modules():
        if isinstance(module, torch.nn.Linear):
            low = name.lower()
            if ".layers." in name and not any(x in low for x in ("visual", "vision", "image")):
                linear.append(name)
    if not linear:
        raise RuntimeError("no language-layer Linear modules discovered")

    lcfg = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_r * 2,
        lora_dropout=0.0,
        bias="none",
        target_modules=linear,
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lcfg)
    for name, p in model.named_parameters():
        if p.requires_grad and any(x in name.lower() for x in ("visual", "vision", "image")):
            p.requires_grad = False

    model.gradient_checkpointing_enable()
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    if trainable <= 0:
        raise RuntimeError("no trainable LoRA parameters")

    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=args.lr)
    examples = [build_example(tok, r, args.max_length) for r in rows]

    model.train()
    torch.cuda.synchronize()
    train_t0 = time.perf_counter()
    step_metrics = []
    total_tokens = 0
    total_target_tokens = 0

    for step in range(args.steps):
        ex = examples[step % len(examples)]
        optimizer.zero_grad(set_to_none=True)
        t0 = time.perf_counter()
        out = model(
            input_ids=ex["input_ids"],
            attention_mask=ex["attention_mask"],
            labels=ex["labels"],
        )
        loss = out.loss
        if not torch.isfinite(loss):
            raise RuntimeError(f"non-finite loss at step {step}: {loss.item()}")
        loss.backward()
        grad_norm = float(torch.nn.utils.clip_grad_norm_(
            [p for p in model.parameters() if p.requires_grad], 1.0
        ))
        optimizer.step()
        torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        total_tokens += ex["tokens"]
        total_target_tokens += ex["target_tokens"]
        metric = {
            "step": step + 1,
            "loss": float(loss.detach().cpu()),
            "seconds": dt,
            "tokens": ex["tokens"],
            "target_tokens": ex["target_tokens"],
            "tokens_per_second": ex["tokens"] / dt,
            "grad_norm": grad_norm,
            "vram_allocated": torch.cuda.memory_allocated(),
            "vram_reserved": torch.cuda.memory_reserved(),
        }
        step_metrics.append(metric)
        print(json.dumps(metric, sort_keys=True), flush=True)

    train_seconds = time.perf_counter() - train_t0
    model.save_pretrained(output, safe_serialization=True)
    tok.save_pretrained(output)

    adapter_path = output / "adapter_model.safetensors"
    pcfg = PeftConfig.from_pretrained(output)
    with safe_open(adapter_path, framework="pt", device="cpu") as f:
        adapter_tensor_count = len(list(f.keys()))

    manifest = {
        "status": "PASS",
        "purpose": "P5.0 feasibility only; synthetic dataset is not P5.1 training data",
        "base_model": "Qwen/Qwen3.8-27B",
        "base_revision": "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
        "git_sha": os.environ.get("P5_GIT_SHA", "unknown"),
        "dataset_path": str(dataset_path),
        "dataset_sha256": sha256_file(dataset_path),
        "seed": args.seed,
        "method": "BF16 LoRA",
        "config": {
            "steps": args.steps,
            "max_length": args.max_length,
            "batch_size": 1,
            "gradient_accumulation_steps": 1,
            "lr": args.lr,
            "lora_r": args.lora_r,
            "lora_alpha": args.lora_r * 2,
            "lora_dropout": 0.0,
            "base_dtype": "bfloat16",
            "gradient_checkpointing": True,
        },
        "environment": {
            "torch": torch.__version__,
            "hip": torch.version.hip,
            "transformers": transformers.__version__,
            "peft": peft.__version__,
            "trl": trl.__version__,
            "accelerate": accelerate.__version__,
            "datasets": datasets.__version__,
            "device": torch.cuda.get_device_name(0),
            "device_total_memory": torch.cuda.get_device_properties(0).total_memory,
        },
        "model_load_seconds": load_seconds,
        "train_seconds": train_seconds,
        "mean_step_seconds": sum(x["seconds"] for x in step_metrics) / len(step_metrics),
        "tokens_per_second": total_tokens / train_seconds,
        "target_tokens_per_second": total_target_tokens / train_seconds,
        "peak_vram_allocated": torch.cuda.max_memory_allocated(),
        "peak_vram_reserved": torch.cuda.max_memory_reserved(),
        "host_ram_used_before": host_ram_before,
        "host_ram_used_after": psutil.virtual_memory().used,
        "trainable_params": trainable,
        "total_params_reported": total,
        "target_module_count": len(linear),
        "target_module_examples": linear[:30],
        "adapter_tensor_count": adapter_tensor_count,
        "adapter_sha256": sha256_file(adapter_path),
        "peft_base_model_name_or_path": pcfg.base_model_name_or_path,
        "steps": step_metrics,
    }
    (output / "p5_feasibility_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("P5_FEASIBILITY=PASS")
    print(json.dumps({
        k: manifest[k] for k in (
            "dataset_sha256", "model_load_seconds", "train_seconds",
            "mean_step_seconds", "tokens_per_second", "peak_vram_allocated",
            "peak_vram_reserved", "trainable_params", "target_module_count",
            "adapter_sha256"
        )
    }, indent=2))

if __name__ == "__main__":
    main()
