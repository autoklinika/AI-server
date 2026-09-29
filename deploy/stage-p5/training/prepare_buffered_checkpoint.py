#!/usr/bin/env python3
from __future__ import annotations
import argparse
import gc
import json
import shutil
from pathlib import Path

import torch
from safetensors.torch import load, save_file

SMALL_FILES = [
    "config.json",
    "generation_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
    "merges.txt",
    "vocab.json",
    "preprocessor_config.json",
    "video_preprocessor_config.json",
    "LICENSE",
    "README.md",
    "crc32.txt",
]

def tensor_nbytes(t: torch.Tensor) -> int:
    return t.numel() * t.element_size()

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--target-mib", type=int, default=512)
    args = ap.parse_args()

    src = Path(args.source)
    dst = Path(args.dest)
    dst.mkdir(parents=True, exist_ok=True)
    index = json.loads((src / "model.safetensors.index.json").read_text())
    original_shards = sorted(set(index["weight_map"].values()))
    target = args.target_mib * 1024 * 1024

    for name in SMALL_FILES:
        s = src / name
        if s.exists():
            shutil.copy2(s, dst / name)

    new_map: dict[str, str] = {}
    output_num = 0
    total_size = 0

    for shard_idx, shard_name in enumerate(original_shards, 1):
        shard_path = src / shard_name
        print(f"P5_RESHARD=READ {shard_idx}/{len(original_shards)} {shard_name}", flush=True)
        with shard_path.open("rb") as fh:
            raw = fh.read()
        state = load(raw)

        bucket: dict[str, torch.Tensor] = {}
        bucket_bytes = 0

        def flush() -> None:
            nonlocal bucket, bucket_bytes, output_num, total_size
            if not bucket:
                return
            output_num += 1
            out_name = f"model-{output_num:05d}.safetensors"
            out_path = dst / out_name
            save_file(bucket, out_path, metadata={"format": "pt"})
            size = out_path.stat().st_size
            total_size += size
            for key in bucket:
                new_map[key] = out_name
            print(
                f"P5_RESHARD=WRITE {out_name} tensors={len(bucket)} "
                f"payload_bytes={bucket_bytes} file_bytes={size}",
                flush=True,
            )
            bucket = {}
            bucket_bytes = 0

        for key in sorted(state):
            t = state[key]
            n = tensor_nbytes(t)
            if bucket and bucket_bytes + n > target:
                flush()
            bucket[key] = t
            bucket_bytes += n
            if n >= target:
                flush()
        flush()

        del state
        del raw
        gc.collect()

    new_index = {
        "metadata": {
            **index.get("metadata", {}),
            "total_size": total_size,
            "p5_reshard_target_mib": args.target_mib,
            "p5_source_checkpoint": str(src),
        },
        "weight_map": new_map,
    }
    (dst / "model.safetensors.index.json").write_text(
        json.dumps(new_index, indent=2, sort_keys=True) + "\n"
    )

    if set(new_map) != set(index["weight_map"]):
        missing = set(index["weight_map"]) - set(new_map)
        extra = set(new_map) - set(index["weight_map"])
        raise RuntimeError(f"weight-map mismatch missing={len(missing)} extra={len(extra)}")

    print(
        f"P5_RESHARD=PASS input_shards={len(original_shards)} "
        f"output_shards={output_num} tensors={len(new_map)} total_size={total_size}",
        flush=True,
    )

if __name__ == "__main__":
    main()
