# RTX 5060 Ti eGPU — GPU compute and bounded stability tests
Data: 2026-10-23 (CEST). Host: harrypotter-AI-Series, Ubuntu 26.04.1, NVIDIA Open 615.71.09.
Boot UUID: d05627f7-8703-40d8-bc36-971578675050.

## Environment
- Minisforum + TBGAA USB4 + JHL9480 bridge 0000:02:00.0 + RTX 5060 Ti 0000:03:00.0
- Both ends configured with **PCIe Gen3 + Hardware Autonomous Speed Disable (HA)** before driver load
- Current PCIe link after tests: **Gen3 x4, 8.0 GT/s** on bridge and GPU
- Maintenance boot: automatic GPU clients masked; NVIDIA loaded by explicit operator action
- GPU compute via minimal CUDA Driver API / PTX kernel, Python 3.14 stdlib and ctypes
- No PCIe writes, driver reload, GRUB changes, CUDA retries, or production service changes during these tests

## Tests and actual results
| Stage | Count of u32 elements | Inner integer iterations / element | Wall-clock load | Kernel launches | Integrity |
|---|---:|---:|---:|---:|---|
| small | 65,536 | 8 | Single dispatch | 1 | PASS, all 262,144 output bytes |
| short | 262,144 | 256 | 10 s | 2,231 | PASS, 1,048,576 bytes at both checkpoints |
| long | 1,048,576 | 512 | 40 s | 8,908 | PASS, 4,194,304 bytes at eight checkpoints |

Each invocation has independent, durable one-shot journal under this directory:
- once-d05627f7-8703-40d8-bc36-971578675050-small.jsonl
- once-d05627f7-8703-40d8-bc36-971578675050-short.jsonl
- once-d05627f7-8703-40d8-bc36-971578675050-long.jsonl

At each stage all CUDA_START events have matching CUDA_END events with rc=0. No STOP or CLEANUP_ERROR events. Module unload, VRAM free and context destruction succeeded for all stages. No orphan process held /dev/nvidia* after completion. After the long stage: NVIDIA GPU bound, TBGAA authorized, PCIe Gen3 x4 both ends, Ethernet and Wi-Fi operational, original boot UUID unchanged. PCIe AER counters (correctable/nonfatal/fatal) 0 on GPU and downstream bridge; kernel journal contains no NVIDIA Xid or GPU-fallen-off-bus event.

## Interpretation
**BOUNDED_TEST_PASS**: the tested sequence (context, VRAM transfers, arithmetic PTX dispatch, repeated kernel calls and transfers during 40 s) operated correctly without host reset or PCIe deterioration. This strongly improves confidence over the previous broken Gen1 behavior. It is **not** proof of 24/7 stability, maximum-GPU-power thermal behavior, hot-plug/suspend/reboot resilience, or the long-term reliability of the hardware.

**NOT_PERSISTENT**: Gen3+HA was set during this one-shot maintenance boot, without installing a persistent boot hook. On a subsequent normal boot the system may reset the bridge back to Gen1 and the failure could reappear. Keep this distinction before resuming production workloads.

Original executable: compute_probe.py (SHA256 b98ced3a8a8689b57fe29c013fa3974de619c0b9c104e2b0ba7a35ce610d3f96). Individual stage markers enforce one attempt per boot; never delete them to retry an unsuccessful stage.

CUDA load was a repetitive deterministic arithmetic kernel, not a full system/GPU stress benchmark or GPU thermal limit test.
