#!/usr/bin/env python3
"""Read-only FLUX2 Klein lower-bound memory analysis (metadata only).

Never loads tensors, PyTorch, ROCm, Ollama inference, or ComfyUI. No service
mutations; output is an admission warning, not an approval to run GPU tasks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import struct
import sys

MODEL_PATHS = {
    "flux2_klein": Path("/opt/comfyui/data/models/diffusion_models/flux-2-klein-4b-fp8.safetensors"),
    "flux2_text": Path("/opt/comfyui/data/models/text_encoders/qwen_3_4b.safetensors"),
    "flux2_vae": Path("/opt/comfyui/data/models/vae/flux2-vae.safetensors"),
}
DEV_UNIT = (Path(__file__).resolve().parents[2]
            / "deploy/comfy-ondemand-dev/ai-rm-comfy-ondemand-dev.service")
BYTES_PER_ELEMENT = {
    "BOOL": 1, "U8": 1, "I8": 1, "F8_E4M3": 1,
    "F8_E5M2": 1, "I16": 2, "F16": 2, "BF16": 2,
    "I32": 4, "F32": 4, "I64": 8, "F64": 8,
}
GIB = 1024**3
# Diagnostic reserve only. This is not a validated GPU runtime safety budget.
HOST_RESERVE_BYTES = 8*GIB
MAX_HEADER_BYTES = 32*1024*1024


class MemoryPreflightBlocked(ValueError):
    pass


def inspect_weights(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise MemoryPreflightBlocked("missing model file or symlink")
    file_size = path.stat().st_size
    with path.open("rb") as fp:
        raw = fp.read(8)
        if len(raw) != 8:
            raise MemoryPreflightBlocked("invalid safetensors header")
        (header_len,) = struct.unpack("<Q", raw)
        if not 2 <= header_len <= MAX_HEADER_BYTES or 8 + header_len > file_size:
            raise MemoryPreflightBlocked("invalid or excessive metadata length")
        try:
            header = json.loads(fp.read(header_len))
        except (ValueError, UnicodeDecodeError) as exc:
            raise MemoryPreflightBlocked("invalid safetensors metadata") from exc
    if not isinstance(header, dict):
        raise MemoryPreflightBlocked("invalid safetensors dictionary")

    data_bytes = file_size - 8 - header_len
    dtype_bytes: dict[str, int] = {}
    segments: list[tuple[int, int]] = []
    count = 0
    for name, spec in header.items():
        if name == "__metadata__":
            continue
        if not isinstance(name, str) or not isinstance(spec, dict):
            raise MemoryPreflightBlocked("invalid tensor record")
        dtype = spec.get("dtype")
        shape = spec.get("shape")
        offsets = spec.get("data_offsets")
        if (dtype not in BYTES_PER_ELEMENT or not isinstance(shape, list)
                or len(shape) > 10 or not isinstance(offsets, list)
                or len(offsets) != 2):
            raise MemoryPreflightBlocked("unknown or malformed tensor metadata")
        if any(type(d) is not int or d < 0 for d in shape):
            raise MemoryPreflightBlocked("invalid tensor shape")
        if any(type(n) is not int or n < 0 for n in offsets):
            raise MemoryPreflightBlocked("invalid tensor offsets")
        start, end = offsets
        if start > end or end > data_bytes:
            raise MemoryPreflightBlocked("tensor exceeds file payload")
        element_count = 1
        for dimension in shape:
            element_count *= dimension
        expected = element_count * BYTES_PER_ELEMENT[dtype]
        if end - start != expected:
            raise MemoryPreflightBlocked("tensor byte count does not match shape")
        segments.append((start, end))
        dtype_bytes[dtype] = dtype_bytes.get(dtype, 0) + expected
        count += 1
    if not count:
        raise MemoryPreflightBlocked("empty model tensor inventory")
    segments.sort()
    for (_, end), (next_start, _) in zip(segments, segments[1:]):
        if end > next_start:
            raise MemoryPreflightBlocked("overlapping model tensor segments")

    return {
        "file_bytes": file_size, "tensors": count,
        "weight_payload_bytes": sum(dtype_bytes.values()),
        "dtype_bytes": dtype_bytes,
    }


def parse_limit(raw: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)([KMGT])", raw.strip())
    if not match:
        raise MemoryPreflightBlocked("unsupported DEV memory limit")
    val = int(match.group(1)) * 1024 ** ("KMGT".index(match.group(2)) + 1)
    if val <= 0:
        raise MemoryPreflightBlocked("invalid DEV memory limit")
    return val


def unit_limit(text: str) -> int:
    matches = re.findall(r"(?m)^MemoryMax=([^\n]+)$", text)
    if len(matches) != 1:
        raise MemoryPreflightBlocked("missing/ambiguous DEV cgroup MemoryMax")
    return parse_limit(matches[0])


def host_memory(path: Path = Path("/proc/meminfo")) -> dict[str, int]:
    rows: dict[str, int] = {}
    for line in path.read_text().splitlines():
        field, sep, value = line.partition(":")
        if sep and field in {"MemTotal", "MemAvailable"}:
            parts = value.split()
            if len(parts) != 2 or parts[1] != "kB":
                raise MemoryPreflightBlocked("invalid physical RAM telemetry")
            rows[field] = int(parts[0]) * 1024
    if len(rows) != 2 or not (0 < rows["MemAvailable"] <= rows["MemTotal"]):
        raise MemoryPreflightBlocked("physical RAM telemetry unavailable")
    return rows


def analyze(*, data: dict[str, dict[str, object]], memory_max: int,
            mem_total: int, mem_available: int) -> dict[str, object]:
    if (not data or memory_max <= 0 or mem_available <= 0
            or mem_available > mem_total):
        raise MemoryPreflightBlocked("invalid memory inputs")
    weights = sum(int(entry["weight_payload_bytes"]) for entry in data.values())
    budget = max(0, mem_available - HOST_RESERVE_BYTES)
    # 2 GiB is a heuristic screening margin, NOT a measured activation peak.
    # Require explicit GPU sampling even if both screening margins pass.
    screening_margin = 2 * GIB
    enough_cgroup = memory_max >= weights + screening_margin
    enough_host = budget >= weights + screening_margin
    return {
        "schema_version": 1, "kind": "FLUX2_METADATA_READONLY",
        "files": data,
        "weights_lower_bound_bytes": weights,
        "memory_max_bytes": memory_max,
        "mem_total_bytes": mem_total,
        "mem_available_bytes": mem_available,
        "host_reserve_screen_bytes": HOST_RESERVE_BYTES,
        "estimated_activation_screen_bytes": screening_margin,
        "cgroup_screen": "PASS" if enough_cgroup else "INSUFFICIENT",
        "host_screen": "PASS" if enough_host else "INSUFFICIENT",
        "gpu_memory_peak": "NOT_MEASURED",
        "real_qwen_gpu_route": "NOT_VERIFIED",
        "gpu_reuse_safe": "NOT_VERIFIED",
        "fullchain_gpu_authorized": False,
        "production_modified": False,
    }


def main() -> int:
    if sys.argv[1:] != ["--check"]:
        print("Usage: fullchain_flux2_memory_preflight_dev.py --check", file=sys.stderr)
        return 2
    try:
        specs = {name: inspect_weights(path) for name, path in MODEL_PATHS.items()}
        ram = host_memory()
        result = analyze(data=specs, memory_max=unit_limit(DEV_UNIT.read_text()),
                         mem_total=ram["MemTotal"], mem_available=ram["MemAvailable"])
    except (OSError, KeyError, TypeError, OverflowError, MemoryPreflightBlocked) as exc:
        print(json.dumps({"gate": "BLOCKED", "error": type(exc).__name__,
                          "gpu_authorized": False}))
        return 3
    print(json.dumps(result, indent=2, sort_keys=True))
    # An insufficient cgroup budget must never be declared acceptable.
    return 0 if result["cgroup_screen"] == result["host_screen"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
