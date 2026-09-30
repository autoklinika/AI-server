# AI Platform — Stage P5.0 Training Readiness — 2026-09-29

## Status

P5.0 is **BLOCKED / fail-closed** pending a memory-safe model load and a real
eight-step BF16 LoRA feasibility run. Operator-supplied post-reboot evidence
confirms tiny BF16 matmul and Conv1d forward/backward PASS with MES_COUNT=0.
The degraded-boot observations below are historical.

No production Qwen3.6 cutover was performed. The frozen P4 benchmark was not modified.

## Baseline and branch

- branch: `stage-p5/training-readiness-v1`
- base main: `d93efb595d6337aa311e0e5e05bfc1faf335f91a`
- selected base model: `Qwen/Qwen3.8-27B`
- checkpoint revision: `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`
- frozen P4 dataset SHA-256: `1f829de1eacdd8e19905e28f2d086161f94fd93c691bee586d6171976d0f8edf`

## Host snapshot

- Ubuntu 26.04 LTS
- kernel: `7.0.0-31-generic`
- CPU: AMD Ryzen AI 9 HX 470, 12C/24T
- GPU: Radeon 890M-class integrated GPU
- configured GPU/UMA memory reported by amdgpu: `103079215104` bytes (~96 GiB)
- host-visible RAM: ~30 GiB
- free storage at audit: ~3.3 TiB

## Training environment

Isolated container:
- image: `ai-platform-p5-train:rocm7.2.1-v1`
- PyTorch: `2.9.1+rocm7.2.1`
- ROCm/HIP: 7.2.1
- Transformers: 5.17.0
- PEFT: 0.21.0
- TRL: 1.14.0
- Accelerate: 1.15.0
- Datasets: 5.0.1

The host production Python environment was not modified.

## Checkpoint

The official BF16 training checkpoint is present under:

`/srv/ai-data/training/p5/models/Qwen3.8-27B`

Size is ~52 GiB on disk, 18 safetensors shards. The upstream model is multimodal and uses the Qwen3.5 architectural implementation internally (`Qwen3_5ForConditionalGeneration` / `qwen3_5` config), which is expected for Qwen3.8.

## Finding 1 — mmap checkpoint-load stall

Initial BF16 loading with the default Transformers/safetensors mmap path reproduced a deterministic-looking stall:

- `P5_MARK=MODEL_LOAD_START` reached
- no `MODEL_LOAD_DONE`
- ~51.8 GiB VRAM allocated/flat
- ~1 CPU core effectively busy
- no disk bottleneck
- no initial OOM
- run remained stuck for ~39 minutes

Transformers 5.17 exposes `disable_mmap=True` directly on `from_pretrained`.

A buffered one-shard probe on the original ~3.7 GiB shard completed:
- buffered read: ~1.02 s
- safetensors decode: ~0.66 s
- re-save: ~1.27 s

This proves the local NVMe/checkpoint data path is healthy and supports avoiding mmap for P5 training.

## Finding 2 — large buffered shards exceed safe host-RAM cgroup budget

With `disable_mmap=True` and the original large shards:

- 16 GiB container limit: cgroup OOM, Python killed at ~16.7 GiB anonymous RSS
- 20 GiB container limit: cgroup OOM, Python killed at ~20.9 GiB anonymous RSS
- the host itself retained memory headroom; the cgroup worked as intended
- `AMD_SERIALIZE_COPY=3` did not remove the buffered-loader RAM peak

The container limit was intentionally not raised further because that would reduce production host safety margin.

## Mitigation prepared — small buffered shards

A reproducible re-sharder was added at:

`deploy/stage-p5/training/prepare_buffered_checkpoint.py`

It produced:

`/srv/ai-data/training/p5/models/Qwen3.8-27B-buffered-512m`

Validation:
- tensors: 1199 / 1199
- output shards: 118
- total indexed weight bytes: 55,563,008,304
- model index SHA-256:
  `f814b730f404aa5e354f1c48a6296ee554687970195e57acb4ddd7d325c6cd65`

The training runner can select this checkpoint through `P5_MODEL_DIR` while retaining the 16 GiB host-RAM cgroup safety ceiling.

## Finding 3 — GPU/MES entered a degraded state

After the earlier GPU-side hang, later probes stopped before the first P5 Python phase marker. The training process entered kernel state `D` / `flush_workqueue`.

Kernel journal then repeatedly reported:

`amdgpu ... MES ring buffer is full.`

The old ComfyUI process was the long-lived owner of `/dev/kfd`. It was terminated in a controlled manner; its systemd unit has `Restart=always`.

After old KFD users disappeared:
- no training process remained
- no old KFD client remained
- VRAM returned to ~0.7 GiB
- the MES ring-full errors continued
- GPU busy continued reporting 100%

Therefore the current boot is considered GPU-runtime-degraded. Additional training measurements in this state are invalid.

## Additional ROCm 7.2.1 / gfx1150 training risk

The Radeon 890M belongs to the gfx1150 family. ROCm 7.2.x has known MIOpen limitations for gfx1150 backward convolution paths. Qwen3.8 uses hybrid linear-attention / Gated DeltaNet layers, including convolutional components, so a clean post-recovery backward probe is required before accepting ROCm 7.2.1 for full LoRA training.

## Confirmed post-incident GPU probe — 19:58 CEST

A minimal isolated ROCm probe was attempted after the large-model jobs were gone:

- PyTorch reported the AMD GPU as available;
- device discovery succeeded;
- a tiny 1024x1024 BF16 matmul with backward did **not** complete;
- the kernel immediately resumed repeated `amdgpu ... MES ring buffer is full` messages;
- the probe container was forcibly stopped;
- VRAM returned to idle (~155 MiB), but `gpu_busy_percent` remained at 100.

This confirms the current blocker is the GPU/KFD/MES runtime state, not Qwen3.8 checkpoint size alone. No further P5 training workloads may run in this boot.

The earlier 24 GiB cgroup diagnostic also ended in cgroup OOM at ~24 GiB anonymous RSS. The committed feasibility runner is therefore restored to the conservative 16 GiB / 16 GiB memory+swap ceiling while P5.0 remains fail-closed.

## Required next gate

Before P5.0 can PASS:

1. recover GPU/MES to a clean state;
2. verify no `MES ring buffer is full` recurrence at idle;
3. run a tiny ROCm BF16 matmul probe;
4. run a minimal Conv1d forward/backward probe on gfx1150;
5. load Qwen3.8 using the buffered/re-sharded checkpoint under the 16 GiB cgroup;
6. complete the 8-step BF16 LoRA feasibility run;
7. save and validate the LoRA adapter plus manifest;
8. record VRAM/RAM peak, step time, tokens/s and stability.

P5.1/P5.2 must not start until these checks pass.

## Alternate one-tensor loader — superseded by bounded loader below

The latest operator-provided evidence supersedes the degraded-boot assessment
above: after reboot, BF16 backward and Conv1d backward passed and MES_COUNT=0.
The remaining verified blocker is Transformers 5.17 `from_pretrained` CPU RSS
growth on Qwen3.8-27B / ROCm UMA until the 16 GiB memcg OOMs. mmap,
`disable_mmap`, 512 MiB resharding and `HF_DEACTIVATE_ASYNC_LOAD` did not resolve
it. These are supplied live findings, not probes repeated during this patch.

`deploy/stage-p5/training/streaming_model_loader.py` now constructs the model
from local config with Accelerate `init_empty_weights(include_buffers=True)`.
It validates the complete index and each shard's keys, shapes and dtypes against
meta model state metadata before copying weights. Missing keys (including tied
aliases omitted by a checkpoint), unexpected keys and mismatches fail closed.
No full CPU weight state dictionary or shard dictionary is constructed.

Each weight gets its own safetensors context: obtain exactly one CPU tensor,
assign directly to CUDA using `set_module_tensor_to_device`, synchronize, delete
the staging reference, and close the mapping before opening the next tensor.
Periodic GC runs every 16 tensors. This still uses safetensors mmap internally;
it bypasses the Transformers weight loader and limits the lifetime of each
mapping to a single tensor. The intended CPU payload bound is one largest tensor
(~2.5 GiB for this checkpoint), plus runtime overhead. Actual memcg/page-cache and
ROCm UMA accounting under the unchanged 16 GiB ceiling must be measured live.

Known non-persistent rotary `inv_freq` buffers are regenerated on CUDA through
the module's own `rope_init_fn`, with shape/dtype checks and restoration of its
original-frequency alias. Any other unresolved meta buffer or tensor attribute
fails closed. All registered parameters and buffers must finish on CUDA. Real
model-specific buffer compatibility remains a live validation risk.

The loader accepts Transformers 5.17.x / Accelerate 1.15.x; other major/minor
versions require explicit `P5_ALLOW_UNTESTED_LOADER_VERSIONS=1` in the Python
process environment. No override is enabled by the feasibility runner.
`STREAMING_*` and per-tensor `TENSOR_LOAD_*` markers report progress. The manifest
now includes `streaming_loader` with tensor count, loaded bytes, maximum single
tensor bytes, versions, elapsed seconds and peak process RSS. RSS uses Linux
`ru_maxrss`, a conservative process-lifetime high-water mark through load end,
so it includes peaks before loader entry and is not a memcg measurement.

Local validation: eight dependency-free unit tests passed using
`python3 -m unittest discover -s tests -p test_stage_p5_streaming_loader.py -v`.
They cover metadata-only planning, key/shape/dtype rejection, path confinement,
one-tensor staging lifetime, assignment failure, metrics, version guarding and
unresolved parameters/buffers. `py_compile` passed for the loader, training entrypoint
and tests; `bash -n` and `git diff --check` also passed. PyTorch, Transformers,
Accelerate, safetensors and pytest are absent from the local Python environment.
These mocks do not establish CUDA/ROCm behavior or the live RAM bound.

The supervising agent's real feasibility command, from this worktree, is:

```bash
P5_MODEL_DIR=/srv/ai-data/training/p5/models/Qwen3.8-27B-buffered-512m \
  bash deploy/stage-p5/training/run_feasibility.sh
```

This command was **not executed** during implementation. The existing runner
retains `--memory=16g --memory-swap=16g` and mounts this worktree's loader. No
Docker, production services or live model data were touched during this patch.
The next gate is a successful streaming load followed by all eight LoRA steps,
adapter/manifest validation and recorded memory/stability evidence.
**P5.0 remains pending; this implementation is not P5.0 PASS.**

## Selected bounded loader — review and real GPU run still required

The training entry point now imports `streaming_bf16_loader.py`. Concurrent
worktree edits were reconciled around this bounded loader; the alternate
one-tensor loader and its mock tests described above have been removed. The
alternative would reject the actual checkpoint's 15 auxiliary `mtp.*` keys and
depends on model-specific buffer reconstruction.

### Diagnosis and evidence limits

Docker image inspection was attempted but the socket returned permission denied.
The image's installed source could therefore **not** be verified here. The
following diagnosis is based on upstream 5.17.0 source and the supplied live
observations, not a claim to have inspected that container:

- [`modeling_utils.py`, `_load_pretrained_model`](https://github.com/huggingface/transformers/blob/v5.17.0/src/transformers/modeling_utils.py): buffered loading merges all decoded shards into a CPU dictionary before assignment. The mmap path retains all shard handles/slices. Device allocator warmup happens first. `device_map` selects destination placement; it does not bound CPU staging.
- [`core_model_loading.py`, `convert_and_load_state_dict_in_model`](https://github.com/huggingface/transformers/blob/v5.17.0/src/transformers/core_model_loading.py): materialization/collection precedes assignment. Disabling async changes scheduling, not the preceding buffering or handle lifetime. This does not prove a driver leak; mmap/UMA accounting remains a live measurement question.

The supplied controlled 72 GiB diagnostic reached ~7.3 GiB MemAvailable near
25% loading, with ~55 GiB device allocation. Raising cgroup limits is not the
remedy. Killed probes recovered to ~160 MiB device usage, 0% busy, no MES recurrence.

Header-only inspection of both real checkpoint directories passed: identical
names/shapes for 1,199 BF16 tensors, 118 buffered shards, and 55,562,855,904 tensor
payload bytes. The previous 55,563,008,304 figure includes shard headers.
Two shards still contain individual ~2.37 GiB tensors; the re-sharder does not
split a tensor. Thus a shard target alone is not a hard CPU memory bound.

### Implementation contract

The selected loader uses public `from_config` under Accelerate
`init_empty_weights(include_buffers=False)`: parameters are meta, small computed
buffers retain their real values and original precision. It validates BF16
headers, extents, shard/index membership, names, shapes and destination dtype
before any weight transfer. All language and vision weights are loaded. Only
auxiliary `mtp.*` keys are excluded, matching the pinned
[`Qwen3_5PreTrainedModel` loading contract](https://github.com/huggingface/transformers/blob/v5.17.0/src/transformers/models/qwen3_5/modeling_qwen3_5.py).
Other missing/unexpected keys fail; tied/quantized configurations are rejected.

One 64 MiB pageable bytearray is reused for direct, bounded `readinto` calls,
including inside the largest tensors. Each chunk is copied into its final device
allocation and synchronized before releasing the CPU tensor view and reusing the
buffer. Only one shard descriptor is open during transfer. There is no checkpoint
CPU state dictionary, mmap, prefetch, pinning, or allocator warmup. Parsing retains
metadata only; individual header reads are capped at 8 MiB. This is an application
staging bound, **not** a claim that total RSS, page cache or HIP allocations are
64 MiB. Safetensors 0.8 CPU `pread` slicing is deliberately avoided because its
[CPU slice branch](https://github.com/huggingface/safetensors/blob/v0.8.0/bindings/python/src/lib.rs)
reads the whole tensor before slicing.

The final loader accepts Transformers **5.17.x** and Accelerate **1.15.x**;
the target image reports 5.17.0 / 1.15.0. An explicit reviewed version override
exists in the final concurrent revision, but the feasibility runner does not
forward it; do not enable it for this gate. There is no fallback to
`from_pretrained`. Registered parameters and buffers must finish on the target
device. The checkpoint is treated
as immutable during validation/transfer. Per-chunk checks abort below **8 GiB
host MemAvailable**, and below **512 MiB cgroup headroom**. These guards complement,
and do not replace, the unchanged
`--memory=16g --memory-swap=16g` container limits. It is not an independent watchdog
for a hung HIP call. No production service, driver, kernel or model selection changed.

### Validation and next action

Nine actual CPU tensor tests passed with GPU visibility disabled, using the
existing `/opt/comfyui/venv/bin/python` read-only (torch 2.13.0+rocm10.0.0,
safetensors 0.8.0); this is **not** the target training image. Tests cover exact
values across nine shards, repeated reuse of one staging buffer, weak-reference
proof that CPU views die before the next read, large-relative-to-buffer tensors,
short reads, scalars, preserved FP32 buffers, malformed inputs, version mismatch,
headroom abort and cleanup after truncated reads. The production-sized checkpoint
was inspected through headers only; no full weights or GPU model were loaded.

```bash
HIP_VISIBLE_DEVICES=-1 CUDA_VISIBLE_DEVICES=-1 PYTHONDONTWRITEBYTECODE=1 \
  /opt/comfyui/venv/bin/python -m unittest discover -s tests \
  -p test_stage_p5_bounded_loader.py -v
```

Residual risks: exact-image `from_config`/buffer compatibility remains untested;
HIP bounce buffers, allocator retention, cgroup page-cache accounting and physical
UMA pressure require the real run. Chunk synchronization favors a strict lifetime
bound over load speed. The supervisor should inspect the installed 5.17.0 source
and review the final reconciled changes before running this command from the worktree:

```bash
P5_MODEL_DIR=/srv/ai-data/training/p5/models/Qwen3.8-27B-buffered-512m \
  bash deploy/stage-p5/training/run_feasibility.sh
```

No GPU feasibility run was launched. A load failure must stop the run; do not
increase the memory limit or bypass validation. P5.0 remains **BLOCKED** until all
eight steps, adapter/manifest validation and memory/stability review pass.

## P5.0 bounded streaming loader and live feasibility — PASS

After the controlled reboot, the ROCm runtime recovered cleanly. A 1024x1024 BF16 matmul with backward passed, a BF16 Conv1d forward/backward probe passed, GPU idle returned normally, and no new `MES ring buffer is full` message appeared.

The standard Transformers 5.17 loader remained unsuitable for this UMA host: both mmap and buffered loading accumulated enough memory-accounted pages to hit the 16 GiB container limit. A controlled 16 GiB run with the new bounded loader later established that the loader itself was healthy: it reached 800/1184 model tensors (~30.1 GB loaded) with only ~1.34 GB peak process RSS, but the container cgroup had only ~507 MiB headroom while the host still had ~27 GB `MemAvailable`. This demonstrates that the Docker memory cgroup is charging a material part of AMD UMA/GPU allocations; 16 GiB is therefore not a meaningful CPU-RAM ceiling for this training workload.

`deploy/stage-p5/training/streaming_bf16_loader.py` now bypasses Transformers weight loading. It constructs the selected Qwen3.8 implementation on meta, validates the safetensors index and payload extents, accepts only the model implementation's reviewed `^mtp.*` auxiliary-weight contract, and copies checkpoint payload directly to final CUDA allocations through a reusable 64 MiB CPU staging buffer. It never materializes a complete CPU tensor, shard dictionary, mmap weight map, or full CPU model state.

Checkpoint validation:
- checkpoint tensors: 1199, all BF16;
- expected model tensors: 1184;
- ignored upstream auxiliary MTP tensors: 15;
- total checkpoint payload: 55,562,855,904 bytes;
- model payload actually loaded: 54,713,457,120 bytes;
- largest source tensor: 2,542,796,800 bytes;
- CPU staging buffer: 67,108,864 bytes.

The successful real gate used a 48 GiB Docker cgroup accounting ceiling with swap disabled by setting `memory-swap` equal to `memory`. This is an UMA accounting allowance, not observed host CPU-RAM consumption. Independent host protection remains mandatory: the runner now monitors host `MemAvailable` and kills the training container below 8 GiB, while the loader also enforces the same headroom during streaming. Version, key, dtype, shape, path, payload-integrity, unresolved-meta and cgroup-headroom checks remain fail-closed.

Real Qwen3.8-27B BF16 LoRA feasibility result (`bounded-v2-48g-20260929T1919Z`):
- streaming model load: PASS;
- loaded tensors: 1184/1184;
- model load time: 12.826 s;
- streaming peak process RSS: 1,327,710,208 bytes;
- model-load VRAM after completion: 54,728,542,208 bytes;
- LoRA targets: 496 modules;
- trainable parameters: 29,181,952;
- training steps: 8/8 PASS;
- total training time: 89.224 s;
- mean step time: 11.151 s;
- throughput: 21.575 tokens/s;
- peak VRAM allocated: 56,209,041,408 bytes;
- peak VRAM reserved: 56,753,127,424 bytes;
- adapter tensor count: 992;
- adapter file size: ~112 MiB;
- adapter SHA-256: `e74e63af4a84771849372efb9d125bcf188ab912f3a82b4085a6a66b2430bc0a`;
- manifest status: `PASS`.

Post-run recovery:
- GPU busy: 0%;
- VRAM used after release: ~163 MiB;
- host `MemAvailable`: ~27 GiB;
- new MES ring-full events: 0.

The optimized `causal_conv1d` and `flash-linear-attention` packages are not installed in the isolated P5 image, so the feasibility run used correct but slower reference PyTorch implementations for those paths. This is a performance optimization opportunity, not a readiness blocker.

**P5.0 TRAINING READINESS = PASS.** The selected Qwen3.8-27B base can be loaded and trained with BF16 LoRA on this server using the bounded streaming loader and UMA-aware safety policy. P5.1 may proceed only through this validated loading/safety path unless a replacement path receives an equivalent gate.
