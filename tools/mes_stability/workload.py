#!/usr/bin/env python3
"""Synthetic ROCm diagnostics. No corpus, adapter loading or checkpoint writes."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import time
import torch


def emit(**data):
    print(json.dumps(data, sort_keys=True), flush=True)


def memory():
    return dict(allocated=torch.cuda.memory_allocated(), reserved=torch.cuda.memory_reserved(),
                peak_allocated=torch.cuda.max_memory_allocated(), peak_reserved=torch.cuda.max_memory_reserved())


def run_synthetic(args):
    # Gradually allocate/touch physical pages rather than reserve unused virtual memory.
    resident = []
    remaining = int(args.resident_gib * 1024**3)
    while remaining:
        size = min(remaining, 256 * 1024**2)
        resident.append(torch.zeros(size, dtype=torch.uint8, device='cuda'))
        remaining -= size
        torch.cuda.synchronize()
        emit(phase='allocation', **memory())
    a = torch.randn((2048, 2048), device='cuda', dtype=torch.bfloat16, requires_grad=True)
    b = torch.randn_like(a, requires_grad=True)
    cpu = torch.arange(4*1024**2, dtype=torch.float32).pin_memory()
    copy = torch.empty_like(cpu, device='cuda')
    start = time.monotonic()
    step = 0
    while time.monotonic() - start < args.seconds:
        a.grad = None; b.grad = None
        loss = (a @ b).float().square().mean()
        loss.backward()
        copy.copy_(cpu, non_blocking=True)
        back = copy.to('cpu', non_blocking=False)
        # Exercise allocation churn and queue/barrier traffic without cache flushing.
        churn = torch.empty((32 + step % 5 * 16) * 1024**2, dtype=torch.uint8, device='cuda')
        churn.fill_(step % 251)
        if resident:
            resident[step % len(resident)].add_(1)
        torch.cuda.synchronize()
        if not torch.isfinite(loss).item() or not torch.equal(back, cpu):
            raise RuntimeError('numerical or copy verification failed')
        del churn, back
        step += 1
        if step % 10 == 0:
            emit(phase='stress', step=step, elapsed_s=time.monotonic()-start, **memory())
    emit(phase='completed', profile='synthetic', steps=step, measured_s=time.monotonic()-start, **memory())


def run_qwen(args):
    import sys
    sys.path.insert(0, '/workspace/deploy/stage-p5/training')
    from streaming_bf16_loader import load_qwen_bf16
    from peft import LoraConfig, get_peft_model
    model, metrics = load_qwen_bf16('/model')
    emit(phase='model_loaded', loader=metrics, **memory())
    for cfg in (model.config, getattr(model.config, 'text_config', None)):
        if cfg is not None:
            cfg.use_cache = False
    targets = [name for name, module in model.named_modules()
               if isinstance(module, torch.nn.Linear) and '.layers.' in name
               and not any(s in name.lower() for s in ('visual', 'vision', 'image'))]
    if not targets:
        raise RuntimeError('no language linear targets')
    model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0,
                                           target_modules=targets, bias='none', task_type='CAUSAL_LM'))
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model.train()
    params = [p for p in model.parameters() if p.requires_grad]
    # lr=0 retains compute/Adam state without learning. Fresh LoRA, never v3/v4.
    optimizer = torch.optim.AdamW(params, lr=0)
    cfg = getattr(model.config, 'text_config', model.config)
    vocab = cfg.vocab_size
    start = time.monotonic(); step = 0
    while time.monotonic() - start < args.seconds:
        length = (396, 900, 960, 887, 399)[step % 5]
        ids = torch.randint(100, min(vocab, 10000), (1, length), device='cuda')
        labels = ids.clone(); labels[:, :length//2] = -100
        optimizer.zero_grad(set_to_none=True)
        loss = model(input_ids=ids, attention_mask=torch.ones_like(ids), labels=labels).loss
        if not torch.isfinite(loss).item():
            raise RuntimeError('nonfinite synthetic loss')
        loss.backward()
        grad = torch.nn.utils.clip_grad_norm_(params, 1.0)
        if not torch.isfinite(grad).item():
            raise RuntimeError('nonfinite synthetic gradient')
        optimizer.step(); torch.cuda.synchronize(); step += 1
        emit(phase='stress', profile='qwen', step=step, tokens=length, loss=float(loss),
             elapsed_s=time.monotonic()-start, **memory())
    emit(phase='completed', profile='qwen', steps=step, measured_s=time.monotonic()-start, **memory())


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--seconds', type=int, required=True)
    p.add_argument('--resident-gib', type=float, required=True)
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--profile', choices=['synthetic', 'qwen'], default='synthetic')
    args = p.parse_args()
    if not torch.version.hip or not torch.cuda.is_available():
        raise RuntimeError('ROCm device unavailable')
    torch.manual_seed(args.seed)
    props = torch.cuda.get_device_properties(0)
    cg = {}
    for n in ('memory.max', 'memory.swap.max', 'memory.current', 'memory.events', 'pids.max'):
        f = Path('/sys/fs/cgroup') / n
        cg[n] = f.read_text() if f.exists() else 'unavailable'
    emit(phase='environment', torch=torch.__version__, hip=torch.version.hip,
         gfx=props.gcnArchName, gpu=str(props), allocator=torch.cuda.memory.get_allocator_backend(),
         packages={n: importlib.metadata.version(n) for n in ('transformers', 'peft', 'accelerate')},
         environment={k:v for k,v in os.environ.items() if k.startswith(('HSA_', 'HIP_', 'ROCM_', 'PYTORCH_', 'AMD_', 'TORCH_'))},
         cgroup=cg, seed=args.seed, profile=args.profile)
    (run_qwen if args.profile == 'qwen' else run_synthetic)(args)


if __name__ == '__main__':
    main()
