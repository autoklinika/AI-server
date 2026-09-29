# AI Platform — Stage P5.0 Training Readiness — 2026-09-29

## Status

P5.0 is **BLOCKED / fail-closed** pending a clean GPU/MES recovery and a post-recovery ROCm training probe.

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
