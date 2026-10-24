# RTX 5060 Ti — controlled PCIe Gen3 + HA load-test report

**Date:** 2026-10-23, host `harrypotter-AI-Series`, boot ID `067e4fa7-1585-4f81-86fd-30cd6cc4e6ea`.

## Acceptance verdict

**PASS — automated Gen3×4 + HA boot, CUDA inference via installed Ollama BGE-M3, bounded 60-second moderate-load stability, model unload and recovery checks.**

**Not yet verified:** near-180W/full-VRAM or prolonged (many hours) stress. One minute without errors cannot prove indefinite reliability or exclude recurrence of rare NVIDIA driver faults.

## Hardware and boot control

- RTX 5060 Ti (NVIDIA open driver **615.71.09**, 16,311 MiB reported VRAM) on 0000:03:00.0
- JHL9480 eGPU downstream bridge 0000:02:00.0 / TBGAA USB4 router
- Normal boot gate `ai-egpu-gen3-ha.service`: **PASS** at 16:02:30 CEST
- Earlier root `verify-ready`: **PASS** with `ctl2=0x0023` on GPU and `0x0063` on JHL9480, setting Gen3 and Hardware Autonomous Speed Disable. Root evidence is retained in conversation.
- Before and after inference both GPU and bridge: **8.0 GT/s x4 (PCIe Gen3×4)**; GPU driver `nvidia`; NVIDIA-SMI PCIe Gen=3, Width=4

## Method

- No CUDA toolkit installation, service reconfiguration, GRUB changes, PCI configuration writes, driver reload, or reboot.
- Existing model **bge-m3:latest** via localhost Ollama 0.40.7 /api/embed.
- Technical text read from existing AI Platform eGPU configuration reports, without network downloads.
- Preflight requires gate active, correct boot ID and PCIe Gen3×4, Resource Manager IDLE, 0 active/queued jobs, no existing loaded models, 0 AER, no Xid, and free RTX VRAM.
- Safety watcher checks NVIDIA-SMI temperature, power, utilization, used VRAM and link plus GPU/bridge sysfs AER; fresh kernel log error scans performed during test.
- Abort limits: temperature >73°C, power >155W, unexpected >8GiB GPU VRAM usage, link drift, AER/Xid, model response failure or test deadline.
- `ollama stop bge-m3:latest` at end; poll until /api/ps empty and NVIDIA VRAM released.

## Results

| Stage | Compute duration | Work | Peak utilization | Peak power | Max temp | Peak VRAM | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| Smoke | ~18s incl. first model initialization | 2 embeddings | 85% | 25.03W | 33°C | 858MiB | Compute PASS, initial cleanup race produced BLOCKED; later verified unloaded |
| Repetition | ~3s compute / ~5s total | 18 embeddings / 6 batches | 57% | 46.51W | 43°C | 862MiB | GPU_COMPUTE_PASS |
| 60s soak | **60.03s compute** | **808 embeddings / 202 batches** | **56%** | **49.41W** | **48°C** | **862MiB** | **GPU_COMPUTE_PASS** |

Continuous stage captured **78 telemetry samples**. Baseline was 32°C, 3.87W and 2MiB VRAM. Model cleanup succeeded with 1.91s memory-release wait; post-test script observed 36MiB, followed by independent NVIDIA-SMI confirmation of 2MiB.

## Independent post-test inspection (~16:31:40 CEST)

- NVIDIA-SMI: **P8, 38°C, 4.85W, 0% GPU utilization, 2MiB VRAM, Gen3×4**.
- `GET /api/ps`: empty model list; NVIDIA no compute processes.
- PCIe AER counts on root port 00:01.1, upstream bridge 01:00.0, downstream bridge 02:00.0 and GPU 03:00.0: **all 0** (correctable/nonfatal/fatal).
- Kernel journal: **no NVIDIA Xid**, no fallen-off-bus or PCIe AER error logs.
- Resource Manager: `IDLE`, no active/queued tasks, `recovery_required=false`; AI Gateway health HTTP 200.
- systemd: `ai-egpu-gen3-ha`, `nvidia-persistenced`, `ollama`, `ai-gateway`, `ai-bridge`, `ai-platform-radio`, `comfyui` all active.
- SSH and NetworkManager active.

## Interpretation and limitations

The actual RTX performed CUDA model inference and unloaded cleanly after an uninterrupted one-minute stress workload. The driver, PCIe target generation, width, kernel journal and AER stayed healthy. This qualifies the **automatic Gen3+HA boot and short/moderate CUDA workload** for use.

It does **not** qualify maximum 180W power draw, 16GB VRAM occupancy, heavy 27B LLM models with split GPU placement, repeated engine handoffs or long-duration random-fault behavior. Such qualification should be staged separately only if useful, without jeopardizing the current stable production state.

## Evidence files (all on server NVMe)

- `result-smoke.json`: first compute and transient early cleanup warning
- `result-sustained.json`: corrected shorter repeated test
- `result-soak.json`: detailed 78-sample/808-embedding 60s test
- `load_probe.py`, `soak_probe.py`: test sources
- `REPORT.md`: this decision report

No permanent daemon, scheduled load, driver changes or additional model downloads were introduced.
