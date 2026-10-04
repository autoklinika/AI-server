#!/usr/bin/env python3
# Derived from the audited P5.11 runner: bounded loader, accumulation, finite
# loss/gradient checks and manifests retained; no parent adapter is accepted.
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import psutil
import torch
from peft import LoraConfig, get_peft_model
from safetensors import safe_open
from transformers import AutoTokenizer
import accelerate
import datasets
import peft
import transformers
import trl

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from streaming_bf16_loader import load_qwen_bf16

EXPECTED_RECORDS = 160
EXPECTED_OPTIMIZER_STEPS = 40
GROUP_SIZES = [4] * EXPECTED_OPTIMIZER_STEPS

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def load_rows(path: Path) -> list[dict]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(rows) != EXPECTED_RECORDS:
        raise RuntimeError(f"expected {EXPECTED_RECORDS} training rows, got {len(rows)}")
    return rows


def assert_finite_gradients(model, where: str) -> None:
    for name, param in model.named_parameters():
        if param.requires_grad and param.grad is not None and not bool(torch.isfinite(param.grad).all().item()):
            raise RuntimeError(f"non-finite gradient after {where}: {name}")


def assert_finite_optimizer_state(model, optimizer, where: str) -> None:
    for name, param in model.named_parameters():
        if param.requires_grad and not bool(torch.isfinite(param).all().item()):
            raise RuntimeError(f"non-finite trainable parameter after {where}: {name}")
    for state in optimizer.state.values():
        for key, value in state.items():
            if torch.is_tensor(value) and not bool(torch.isfinite(value).all().item()):
                raise RuntimeError(f"non-finite optimizer state after {where}: {key}")


def tokenize_example(tok, row: dict, max_length: int):
    prompt = [{"role": "system", "content": row["system"]}, {"role": "user", "content": row["user"]}]
    full = prompt + [{"role": "assistant", "content": row["assistant"]}]
    prompt_text = tok.apply_chat_template(prompt, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    full_text = tok.apply_chat_template(full, tokenize=False, add_generation_prompt=False, enable_thinking=False)
    prompt_ids = tok(prompt_text, add_special_tokens=False)["input_ids"]
    full_ids = tok(full_text, add_special_tokens=False)["input_ids"]
    if len(full_ids) > max_length:
        raise RuntimeError(
            f"record {row.get('record_id')} token length {len(full_ids)} exceeds max_length={max_length}; "
            "refusing assistant-target truncation"
        )
    if len(prompt_ids) >= len(full_ids):
        raise RuntimeError(f"record {row.get('record_id')} has no assistant target")
    if full_ids[:len(prompt_ids)] != prompt_ids:
        raise RuntimeError("chat template prompt/target prefix mismatch")
    labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids):]
    return {
        "input_ids": torch.tensor([full_ids], dtype=torch.long, device="cuda"),
        "attention_mask": torch.ones((1, len(full_ids)), dtype=torch.long, device="cuda"),
        "labels": torch.tensor([labels], dtype=torch.long, device="cuda"),
        "tokens": len(full_ids),
        "target_tokens": len(full_ids) - len(prompt_ids),
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--optimizer-steps", type=int, default=EXPECTED_OPTIMIZER_STEPS)
    ap.add_argument("--max-length", type=int, default=8192)
    ap.add_argument("--seed", type=int, default=20261003)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--lora-r", type=int, default=8)
    args = ap.parse_args()

    if args.optimizer_steps != EXPECTED_OPTIMIZER_STEPS:
        raise RuntimeError("WVC requires exactly 40 optimizer steps")
    if args.lora_r != 8:
        raise RuntimeError("WVC fresh adapter contract requires LoRA rank 8")
    if os.environ.get("HSA_USE_SVM") != "0":
        raise RuntimeError("WVC stability profile requires HSA_USE_SVM=0")

    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    dataset_root = Path(args.dataset).resolve().parent
    if Path(args.dataset).resolve() != dataset_root / "train.jsonl":
        raise RuntimeError("only train.jsonl may be trained")

    manifest_path = dataset_root / "manifest.json"
    gates_path = dataset_root / "gates.json"
    manifest = json.loads(manifest_path.read_text())
    gates = json.loads(gates_path.read_text())
    if (
        gates.get("contamination") != "PASS"
        or gates.get("non_wvc_elements") != 0
        or gates.get("schema_current") != "PASS"
        or gates.get("leakage") != "PASS"
    ):
        raise RuntimeError("WVC dataset gates are not PASS")
    if (
        manifest.get("adapter") != "wvc-advisory-v1"
        or manifest.get("base_model") != "Qwen/Qwen3.8-27B"
        or manifest.get("parent_adapter") is not None
    ):
        raise RuntimeError("WVC dataset manifest identity mismatch")
    train_meta = manifest.get("files", {}).get("train", {})
    if train_meta.get("sha256") != sha256_file(Path(args.dataset)):
        raise RuntimeError("WVC training dataset hash mismatch")

    manifest_sha = sha256_file(manifest_path)
    baseline = json.loads((Path(args.output_dir) / "baseline.json").read_text())
    if (
        baseline.get("status") != "COMPLETE"
        or baseline.get("adapter") is not None
        or baseline.get("base_model") != "Qwen/Qwen3.8-27B"
        or baseline.get("manifest_sha256") != manifest_sha
    ):
        raise RuntimeError("missing/stale/wrong-model baseline")
    rows = load_rows(Path(args.dataset))
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    print("WVC_MARK=TOKENIZER_LOAD_START", flush=True)
    if Path(args.model_dir).name != "Qwen3.8-27B-buffered-512m":
        raise RuntimeError("WVC requires the audited Qwen3.8-27B buffered base")
    tok = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    token_lengths = []
    target_lengths = []
    for row in rows:
        prompt = [{"role": "system", "content": row["system"]}, {"role": "user", "content": row["user"]}]
        full = prompt + [{"role": "assistant", "content": row["assistant"]}]
        pids = tok(tok.apply_chat_template(prompt, tokenize=False, add_generation_prompt=True, enable_thinking=False),
                   add_special_tokens=False)["input_ids"]
        fids = tok(tok.apply_chat_template(full, tokenize=False, add_generation_prompt=False, enable_thinking=False),
                   add_special_tokens=False)["input_ids"]
        if len(fids) > args.max_length or len(pids) >= len(fids):
            raise RuntimeError(
                f"dataset token contract failed record={row.get('record_id')} full={len(fids)} "
                f"prompt={len(pids)} max={args.max_length}"
            )
        token_lengths.append(len(fids))
        target_lengths.append(len(fids) - len(pids))
    print(
        f"WVC_MARK=TOKEN_CONTRACT_PASS records={len(rows)} max_tokens={max(token_lengths)} "
        f"max_target_tokens={max(target_lengths)}", flush=True
    )

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    host_ram_before = psutil.virtual_memory().used
    load_t0 = time.perf_counter()
    model, loader_metrics = load_qwen_bf16(args.model_dir)
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_t0
    print(f"WVC_MARK=MODEL_LOAD_DONE seconds={load_seconds:.3f}", flush=True)

    if hasattr(model.config, "use_cache"):
        model.config.use_cache = False
    if hasattr(model.config, "text_config") and hasattr(model.config.text_config, "use_cache"):
        model.config.text_config.use_cache = False

    linear = [name for name, module in model.named_modules()
              if isinstance(module, torch.nn.Linear) and ".layers." in name
              and not any(x in name.lower() for x in ("visual", "vision", "image"))]
    if not linear:
        raise RuntimeError("no language-layer Linear modules discovered")
    model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.0,
             bias="none", target_modules=linear, task_type="CAUSAL_LM"))
    for name, param in model.named_parameters():
        if param.requires_grad and any(x in name.lower() for x in ("visual", "vision", "image")):
            param.requires_grad = False
    model.gradient_checkpointing_enable()
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    if trainable <= 0:
        raise RuntimeError("no trainable LoRA parameters")
    optimizer = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad),
        lr=args.lr,
        foreach=False,
        fused=False,
    )

    model.train()
    torch.cuda.synchronize()
    train_t0 = time.perf_counter()
    cursor = 0
    optimizer_metrics = []
    microstep_metrics = []
    total_tokens = 0
    total_target_tokens = 0

    for opt_index, group_size in enumerate(GROUP_SIZES, 1):
        optimizer.zero_grad(set_to_none=True)
        group_t0 = time.perf_counter()
        group_losses = []
        group_tokens = 0
        group_targets = 0
        for local_micro in range(group_size):
            row = rows[cursor]
            ex = tokenize_example(tok, row, args.max_length)
            micro_t0 = time.perf_counter()
            out = model(
                input_ids=ex["input_ids"],
                attention_mask=ex["attention_mask"],
                labels=ex["labels"],
            )
            loss = out.loss
            if not torch.isfinite(loss):
                raise RuntimeError(f"non-finite loss at microstep {cursor + 1}: {loss.item()}")
            raw_loss = float(loss.detach().cpu())
            (loss / group_size).backward()
            torch.cuda.synchronize()
            assert_finite_gradients(
                model,
                f"microstep {cursor + 1} record={row.get('record_id')}",
            )
            micro_dt = time.perf_counter() - micro_t0
            group_losses.append(raw_loss)
            group_tokens += ex["tokens"]
            group_targets += ex["target_tokens"]
            total_tokens += ex["tokens"]
            total_target_tokens += ex["target_tokens"]
            micro = {
                "microstep": cursor + 1,
                "optimizer_step": opt_index,
                "group_size": group_size,
                "record_id": row.get("record_id"),
                "loss": raw_loss,
                "tokens": ex["tokens"],
                "target_tokens": ex["target_tokens"],
                "seconds": micro_dt,
            }
            microstep_metrics.append(micro)
            print("WVC_MICROSTEP=" + json.dumps(micro, sort_keys=True), flush=True)
            cursor += 1
            del out, loss, ex

        grad_norm_tensor = torch.nn.utils.clip_grad_norm_(
            [p for p in model.parameters() if p.requires_grad], 1.0
        )
        grad_norm = float(grad_norm_tensor.detach().cpu() if torch.is_tensor(grad_norm_tensor) else grad_norm_tensor)
        if not math.isfinite(grad_norm):
            raise RuntimeError(f"non-finite grad norm at optimizer step {opt_index}: {grad_norm}")
        optimizer.step()
        torch.cuda.synchronize()
        assert_finite_optimizer_state(model, optimizer, f"optimizer step {opt_index}")
        optimizer.zero_grad(set_to_none=True)
        reserved_before_cleanup = torch.cuda.memory_reserved()
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        reserved_after_cleanup = torch.cuda.memory_reserved()
        group_dt = time.perf_counter() - group_t0
        metric = {
            "optimizer_step": opt_index,
            "microsteps_consumed": cursor,
            "group_size": group_size,
            "mean_loss": sum(group_losses) / len(group_losses),
            "min_loss": min(group_losses),
            "max_loss": max(group_losses),
            "grad_norm": grad_norm,
            "tokens": group_tokens,
            "target_tokens": group_targets,
            "seconds": group_dt,
            "vram_allocated": torch.cuda.memory_allocated(),
            "vram_reserved": reserved_after_cleanup,
            "vram_reserved_before_cleanup": reserved_before_cleanup,
            "vram_reserved_after_cleanup": reserved_after_cleanup,
        }
        optimizer_metrics.append(metric)
        print("WVC_OPTIMIZER_STEP=" + json.dumps(metric, sort_keys=True), flush=True)
        if opt_index % 10 == 0:
            model.save_pretrained(output / f"checkpoint-{opt_index}", safe_serialization=True)

    if cursor != EXPECTED_RECORDS:
        raise RuntimeError(f"training schedule consumed {cursor} rows, expected {EXPECTED_RECORDS}")

    train_seconds = time.perf_counter() - train_t0
    model.save_pretrained(output, safe_serialization=True)
    tok.save_pretrained(output)
    adapter_path = output / "adapter_model.safetensors"
    if not adapter_path.is_file():
        raise RuntimeError("adapter_model.safetensors missing after save")
    with safe_open(adapter_path, framework="pt", device="cpu") as f:
        adapter_tensor_count = len(list(f.keys()))
        if adapter_tensor_count <= 0:
            raise RuntimeError("saved adapter contains no tensors")

    manifest = {
        "schema_version": 1,
        "status": "TRAINING_INTEGRITY_PASS_QUALITY_PENDING",
        "stage": "WVC",
        "adapter_kind": "standalone_lora_not_merged",
        "base_model": "Qwen/Qwen3.8-27B",
        "base_revision": "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
        "git_sha": os.environ.get("P5_GIT_SHA", "unknown"),
        "dataset_path": str(Path(args.dataset)),
        "dataset_sha256": sha256_file(Path(args.dataset)),
        "parent_adapter": None,
        "seed": args.seed,
        "method": "BF16 fresh WVC LoRA with once-through gradient accumulation",
        "config": {
            "optimizer_steps": EXPECTED_OPTIMIZER_STEPS,
            "microsteps": EXPECTED_RECORDS,
            "group_sizes": GROUP_SIZES,
            "max_length": args.max_length,
            "lr": args.lr,
            "lora_r": args.lora_r,
            "fresh_optimizer": True,
            "adamw_foreach": False,
            "adamw_fused": False,
            "microstep_gradient_finite_check": True,
            "optimizer_state_finite_check": True,
            "optimizer_boundary_cache_cleanup": True,
            "gradient_checkpointing": True,
            "base_dtype": "bfloat16",
            "HSA_USE_SVM": os.environ.get("HSA_USE_SVM"),
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
        "token_contract": {
            "records": len(rows),
            "max_tokens": max(token_lengths),
            "max_target_tokens": max(target_lengths),
            "truncated_records": 0,
        },
        "model_load_seconds": load_seconds,
        "streaming_loader": loader_metrics,
        "train_seconds": train_seconds,
        "tokens_per_second": total_tokens / train_seconds,
        "target_tokens_per_second": total_target_tokens / train_seconds,
        "peak_vram_allocated": torch.cuda.max_memory_allocated(),
        "peak_vram_reserved": torch.cuda.max_memory_reserved(),
        "host_ram_used_before": host_ram_before,
        "host_ram_used_after": psutil.virtual_memory().used,
        "trainable_params": trainable,
        "adapter_tensor_count": adapter_tensor_count,
        "adapter_sha256": sha256_file(adapter_path),
        "optimizer_steps": optimizer_metrics,
        "microsteps": microstep_metrics,
        "quality_acceptance": "PENDING_FUTURE_INDEPENDENT_EVALUATION",
    }
    (output / "wvc_training_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("WVC_TRAINING_INTEGRITY=PASS", flush=True)
    print(json.dumps({
        "optimizer_steps": len(optimizer_metrics),
        "microsteps": len(microstep_metrics),
        "adapter_sha256": manifest["adapter_sha256"],
        "train_seconds": train_seconds,
        "peak_vram_allocated": manifest["peak_vram_allocated"],
    }, sort_keys=True), flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
