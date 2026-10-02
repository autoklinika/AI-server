"""P5-only bounded BF16 loader for Qwen3.8 on ROCm UMA.

Weights are copied from safetensors payloads to their final CUDA allocations in
fixed-size chunks. No full CPU tensor/state_dict, mmap weight mapping, prefetch,
or Transformers weight loader is used.
"""
from __future__ import annotations

import json
import math
import os
import re
import resource
import struct
import sys
import time
from pathlib import Path

CHUNK_BYTES = 64 * 1024 * 1024
HEADER_LIMIT = 8 * 1024 * 1024
MIN_HOST_AVAILABLE = 8 * 1024**3
MIN_CGROUP_HEADROOM = 512 * 1024**2
_VERSION_OVERRIDE = "P5_ALLOW_UNTESTED_LOADER_VERSIONS"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def check_versions(transformers_version: str, accelerate_version: str):
    def minor(version):
        match = re.match(r"^(\d+\.\d+)\.", version)
        return match.group(1) if match else None
    incompatible = minor(transformers_version) != "5.17" or minor(accelerate_version) != "1.15"
    overridden = os.environ.get(_VERSION_OVERRIDE) == "1"
    if incompatible and not overridden:
        raise RuntimeError(
            f"P5 streaming loader requires Transformers 5.17.0-compatible (5.17.x) / Accelerate 1.15.x; "
            f"got {transformers_version} / {accelerate_version}; override only after review with {_VERSION_OVERRIDE}=1"
        )
    return {
        "transformers": transformers_version,
        "accelerate": accelerate_version,
        "version_override": bool(incompatible and overridden),
    }


def _cgroup_headroom_bytes():
    current = Path("/sys/fs/cgroup/memory.current")
    maximum = Path("/sys/fs/cgroup/memory.max")
    if not current.is_file() or not maximum.is_file():
        return None
    raw_max = maximum.read_text().strip()
    if raw_max == "max":
        return None
    return int(raw_max) - int(current.read_text().strip())


def checkpoint_metadata(directory):
    """Validate shards without reading payloads; return path/offset/shape/bytes."""
    root = Path(directory).resolve()
    index_path = root / "model.safetensors.index.json"
    index_doc = json.loads(index_path.read_text(), object_pairs_hook=_unique_object)
    index = index_doc.get("weight_map")
    if not isinstance(index, dict) or not index:
        raise ValueError("empty or invalid weight_map")
    specs = {}
    for shard in sorted(set(index.values())):
        path = (root / shard).resolve()
        if path.parent != root or path.suffix != ".safetensors" or not path.is_file():
            raise ValueError(f"invalid shard path: {shard}")
        with path.open("rb", buffering=0) as file:
            prefix = file.read(8)
            if len(prefix) != 8:
                raise ValueError(f"truncated header: {shard}")
            header_size = struct.unpack("<Q", prefix)[0]
            if not 2 <= header_size <= HEADER_LIMIT:
                raise ValueError(f"header size outside P5 bound: {shard}")
            raw = file.read(header_size)
            if len(raw) != header_size:
                raise ValueError(f"truncated header: {shard}")
            header = json.loads(raw, object_pairs_hook=_unique_object)
        payload_size = path.stat().st_size - 8 - header_size
        ranges = []
        for name, entry in header.items():
            if name == "__metadata__":
                continue
            if name in specs or index.get(name) != shard:
                raise ValueError(f"index/shard key mismatch: {name}")
            shape = entry.get("shape")
            offsets = entry.get("data_offsets")
            if (entry.get("dtype") != "BF16" or not isinstance(shape, list)
                    or any(type(n) is not int or n <= 0 for n in shape)
                    or not isinstance(offsets, list) or len(offsets) != 2
                    or any(type(n) is not int for n in offsets)):
                raise ValueError(f"unsupported BF16 tensor metadata: {name}")
            start, end = offsets
            tensor_bytes = math.prod(shape) * 2
            if start < 0 or end > payload_size or end - start != tensor_bytes:
                raise ValueError(f"invalid tensor extent: {name}")
            ranges.append((start, end))
            specs[name] = (path, 8 + header_size + start, tuple(shape), tensor_bytes)
        cursor = 0
        for start, end in sorted(ranges):
            if start != cursor:
                raise ValueError(f"overlapping or incomplete payload: {shard}")
            cursor = end
        if cursor != payload_size:
            raise ValueError(f"trailing or truncated payload: {shard}")
    if set(specs) != set(index):
        raise ValueError("index contains missing tensor keys")
    return specs


def _copy_tensor(file, offset, target, staging, guard, rss=lambda: 0):
    import torch
    file.seek(offset)
    flat = target.view(-1)
    total = target.numel() * 2
    peak_rss = rss()
    for start in range(0, total, len(staging)):
        guard()
        size = min(len(staging), total - start)
        view = memoryview(staging)[:size]
        read = 0
        while read < size:
            count = file.readinto(view[read:])
            if not count:
                raise ValueError("checkpoint truncated during tensor read")
            read += count
        source = torch.frombuffer(view, dtype=torch.bfloat16)
        flat[start // 2:(start + size) // 2].copy_(source, non_blocking=False)
        if target.device.type == "cuda":
            torch.cuda.synchronize(target.device)
        peak_rss = max(peak_rss, rss())
        del source, view
    return peak_rss


def stream_into_meta_model(model, specs, *, device, ignored_keys=(),
                           chunk_bytes=CHUNK_BYTES, guard=lambda: None, rss=lambda: 0):
    import torch
    if sys.byteorder != "little" or not 2 <= chunk_bytes <= CHUNK_BYTES or chunk_bytes % 2:
        raise ValueError("unsupported byte order or staging size")
    expected = dict(model.named_parameters(remove_duplicate=False))
    for module_name, module in model.named_modules():
        for name, value in module._buffers.items():
            if value is not None and name not in module._non_persistent_buffers_set:
                expected[f"{module_name}.{name}".lstrip(".")] = value
    ignored = set(ignored_keys)
    missing = set(expected) - set(specs)
    extra = set(specs) - set(expected) - ignored
    if missing or extra or ignored & set(expected):
        raise ValueError(f"checkpoint mismatch: missing={sorted(missing)} extra={sorted(extra)}")
    for name, tensor in expected.items():
        _, _, shape, _ = specs[name]
        if tuple(tensor.shape) != shape or tensor.dtype != torch.bfloat16:
            raise ValueError(f"shape/dtype mismatch: {name}")
        if isinstance(tensor, torch.nn.Parameter) and tensor.device.type != "meta":
            raise ValueError(f"parameter was not initialized on meta: {name}")
    guard()
    staging = bytearray(chunk_bytes)
    ordered = sorted(expected, key=lambda name: specs[name][:2])
    metrics = {
        "tensor_count": 0,
        "bytes_loaded": 0,
        "max_single_tensor_bytes": max(specs[name][3] for name in ordered),
        "staging_bytes": chunk_bytes,
        "peak_process_rss_bytes": rss(),
    }
    current_path, file = None, None
    try:
        with torch.no_grad():
            for number, name in enumerate(ordered, 1):
                path, offset, shape, tensor_bytes = specs[name]
                if path != current_path:
                    if file is not None:
                        file.close()
                    file = path.open("rb", buffering=0)
                    current_path = path
                guard()
                target = torch.empty(shape, dtype=torch.bfloat16, device=device)
                metrics["peak_process_rss_bytes"] = max(
                    metrics["peak_process_rss_bytes"],
                    _copy_tensor(file, offset, target, staging, guard, rss),
                )
                parent, _, leaf = name.rpartition(".")
                module = model.get_submodule(parent)
                if leaf in module._parameters:
                    module._parameters[leaf] = torch.nn.Parameter(target, requires_grad=False)
                elif leaf in module._buffers:
                    module._buffers[leaf] = target
                else:
                    raise ValueError(f"destination disappeared during load: {name}")
                del target
                metrics["tensor_count"] = number
                metrics["bytes_loaded"] += tensor_bytes
                if number % 25 == 0 or number == len(ordered):
                    print("P5_MARK=STREAM_PROGRESS " + json.dumps(metrics, sort_keys=True), flush=True)
            for module in model.modules():
                for name, value in module._buffers.items():
                    if value is not None:
                        if value.device.type == "meta":
                            raise ValueError(f"uninitialized buffer: {name}")
                        module._buffers[name] = value.to(device)
    finally:
        if file is not None:
            file.close()
        del staging
    target_device = torch.device(device)
    for name, tensor in list(model.named_parameters()) + list(model.named_buffers()):
        if tensor.device != target_device:
            raise ValueError(f"model tensor outside target device: {name}={tensor.device}")
    return model, metrics


def load_qwen_bf16(directory):
    """Guarded streaming load for the selected Qwen3.8-27B checkpoint."""
    import accelerate
    import psutil
    import torch
    import transformers
    from transformers import AutoConfig, AutoModelForMultimodalLM, GenerationConfig

    versions = check_versions(transformers.__version__, accelerate.__version__)
    if not torch.version.hip or not torch.cuda.is_available():
        raise RuntimeError("P5 BF16 feasibility requires ROCm GPU")
    rss = lambda: resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024

    def guard():
        available = psutil.virtual_memory().available
        if available < MIN_HOST_AVAILABLE:
            raise RuntimeError(f"P5 host headroom guard: available={available} < {MIN_HOST_AVAILABLE}")
        cgroup_headroom = _cgroup_headroom_bytes()
        if cgroup_headroom is not None and cgroup_headroom < MIN_CGROUP_HEADROOM:
            raise RuntimeError(
                f"P5 cgroup headroom guard: remaining={cgroup_headroom} < {MIN_CGROUP_HEADROOM}"
            )

    started = time.perf_counter()
    guard()
    specs = checkpoint_metadata(directory)
    config = AutoConfig.from_pretrained(directory, local_files_only=True, trust_remote_code=False)
    if (config.model_type != "qwen3_5"
            or config.architectures != ["Qwen3_5ForConditionalGeneration"]
            or config.tie_word_embeddings or config.text_config.tie_word_embeddings
            or getattr(config, "quantization_config", None)):
        raise ValueError("unsupported P5 model configuration")
    with accelerate.init_empty_weights(include_buffers=False):
        model = AutoModelForMultimodalLM.from_config(
            config, dtype=torch.bfloat16, trust_remote_code=False
        )
    if type(model).__name__ != "Qwen3_5ForConditionalGeneration":
        raise ValueError("unexpected P5 model implementation")
    ignored_contract = getattr(model, "_keys_to_ignore_on_load_unexpected", set())
    if r"^mtp.*" not in ignored_contract:
        raise ValueError("Qwen MTP loading contract changed")
    ignored = {key for key in specs if key.startswith("mtp.")}
    print(
        f"P5_MARK=MODEL_META_READY loader=streaming_bf16_v2 ignored_mtp={len(ignored)}",
        flush=True,
    )
    model, metrics = stream_into_meta_model(
        model, specs, device="cuda:0", ignored_keys=ignored, guard=guard, rss=rss
    )
    model.config._name_or_path = str(directory)
    model.name_or_path = str(directory)
    model.generation_config = GenerationConfig.from_pretrained(directory, local_files_only=True)
    model.eval()
    guard()
    metrics.update(versions)
    metrics["seconds"] = time.perf_counter() - started
    metrics["ignored_mtp_tensors"] = len(ignored)
    metrics["rss_scope"] = "Linux process lifetime high-water mark through end of streaming load"
    print("P5_MARK=STREAMING_LOAD_DONE " + json.dumps(metrics, sort_keys=True), flush=True)
    return model, metrics


def load_streaming_model(directory):
    """Compatibility alias for the reviewed P5 loader entrypoint."""
    return load_qwen_bf16(directory)
