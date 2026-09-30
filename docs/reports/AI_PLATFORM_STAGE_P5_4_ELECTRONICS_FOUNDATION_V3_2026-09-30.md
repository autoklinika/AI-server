# AI Platform — Stage P5.4 Electronics Foundation v3

Date: 2026-09-30
Base model: Qwen3.8-27B
Parent adapter: selected electronics-foundation-v2 replay R1
Branch: stage-p5.4/electronics-foundation-v3

## Objective

Add practical board-level electronics diagnostics: measurement strategy, waveform interpretation, good-vs-bad channel comparison, intermittent PCB faults and dynamic protection behavior.

V3 starts with replay protection from both v1 and v2. Acceptance is triple-holdout:
- v3 holdout must improve by at least 5% versus selected-v2 baseline,
- v2 frozen holdout may regress by at most 3%,
- v1 frozen holdout may regress by at most 3%.

## Dataset v3

Training:
- 150 new records,
- 30 new practical-diagnostics categories,
- 62,695 tokens,
- 30,755 target tokens,
- mean 417.97 tokens/record,
- p95 443,
- max 451 tokens,
- SHA-256: c7c618e66e23b141fb9bcfff8c898f6761f065986688519148c86c341344f02d.

Holdout:
- 24 records,
- 8 unseen categories,
- 10,113 tokens,
- 4,920 target tokens,
- mean 421.38 tokens/record,
- max 437 tokens,
- SHA-256: 53c42d955bc956ded5911ad25650029293eda02c34f7f82aedcb4979e7dd52ca.

All 392 prior v1+v2 train/holdout records were checked for exact and high-shingle overlap. Dataset/readiness gates PASS.

## Replay protection

Replay training pool:
- 150 v3-new records,
- 30 v2 train-only replay records,
- 20 v1 train-only replay records,
- total 200 records,
- no holdout records,
- deterministic shuffle seed: 20261003,
- first 40 shuffled examples: 30 v3-new + 5 v2-replay + 5 v1-replay,
- replay SHA-256: 6934bf23be9e8ffad34dfa56cdc04d545243ccaf4a2a69681da1e4c0ae4408a3.

Training defaults:
- LoRA r=8,
- 40 steps,
- max_length=480 (v3 max tokenized record is 451),
- learning rate=2e-5,
- parent adapter=electronics-foundation-v2/current,
- UMA safety policy inherited from P5.0/P5.2.

## Frozen baseline before v3 training

Selected electronics-foundation-v2/current evaluated on the new v3 holdout:
- records: 24,
- target tokens: 4,920,
- token-weighted loss: 0.947101,
- mean case loss: 0.946837,
- median case loss: 0.954510,
- perplexity: 2.5782,
- evaluation time: 140.884 s.

This v3 holdout is frozen and is not used for training or replay.

## First v3 training attempt — runtime abort

Run ID: electronics-foundation-v3-replay-r1-20260930

The replay-protected training started correctly from selected electronics-foundation-v2 and completed 13 steps with finite loss/gradients. During the transition to the next step the AMD GPU entered a degraded MES state:
- last completed step: 13,
- GPU busy: 100%,
- repeated kernel message: `MES ring buffer is full`,
- Docker kill could not receive a container exit event,
- no adapter was written to the partial output directory,
- repository remained clean and all prior selected adapters remained intact.

The last completed example was hbridge_recirculation; the next shuffled example was comparator_propagation_glitch. This correlation is recorded for reproduction but is not treated as proof that the example caused the GPU hang.

The run is classified ABORTED_RUNTIME_GPU_MES and is not eligible for evaluation or selection.

## MES watchdog hardening

The v3 runner now snapshots the kernel MES error count before starting and rechecks it every five seconds while training. Any new `MES ring buffer is full` event triggers `P5_MES_WATCHDOG=TRIGGERED`, attempts immediate container termination, and marks the run failed before acceptance.

This watchdog supplements the existing 8 GiB host-memory floor; it does not replace a host reboot if the GPU is already hard-wedged and cannot process a kill event.

## Post-reboot reproduction check

After the MES hang, the host was rebooted. Post-reboot:
- GPU busy returned to 0%,
- VRAM returned to ~163 MiB,
- boot MES count returned to 0,
- BF16 matmul forward/backward passed.

The exact shuffled step-14 example (comparator_propagation_glitch) was then isolated into a one-record probe and trained for one step from selected v2:
- loss: 1.083978,
- grad norm: 3.0696,
- result: PASS,
- post-probe MES count: 0.

Therefore the earlier hang was treated as a nondeterministic ROCm/MES runtime incident rather than a deterministic dataset failure.

## Successful retry — PASS

Run ID: electronics-foundation-v3-replay-r2-20260930

Training:
- parent adapter: electronics-foundation-v2/current,
- replay mix in first 40 shuffled examples: 30 v3-new + 5 v2-replay + 5 v1-replay,
- steps: 40/40 PASS,
- learning rate: 2e-5,
- max_length: 480,
- LoRA rank: 8,
- trainable parameters: 58,363,904,
- model load: 15.506 s,
- training time: 746.731 s,
- mean step time: 18.667 s,
- throughput: 21.834 tokens/s,
- peak VRAM allocated: 57,342,813,184 bytes,
- peak VRAM reserved: 58,537,803,776 bytes,
- adapter SHA-256: 2fbcbd394318576d2a50924ad2e3f7b452306566243ede24dd524c6d1b549183,
- MES errors during retry: 0.

## Triple-holdout result — PASS

New v3 holdout:
- baseline selected-v2 loss: 0.947101,
- v3 selected loss: 0.726006,
- relative improvement: 23.3445%,
- required minimum improvement: 5%.

Frozen v2 holdout:
- selected-v2 reference loss: 0.726067,
- v3 selected loss: 0.745390,
- relative regression: 2.6613%,
- maximum allowed regression: 3%.

Frozen v1 holdout:
- selected-v2 reference loss: 1.160553,
- v3 selected loss: 1.155325,
- relative regression: -0.4504% (slight improvement),
- maximum allowed regression: 3%.

P5.4 triple-holdout gate: PASS.

## Selection

Selected electronics foundation v3 adapter:
- run: electronics-foundation-v3-replay-r2-20260930,
- stable alias: /srv/ai-data/training/p5/adapters/electronics-foundation-v3/current,
- adapter SHA-256: 2fbcbd394318576d2a50924ad2e3f7b452306566243ede24dd524c6d1b549183,
- status: selected_for_next_stage_not_deployed,
- official foundation for P5.5/P6: yes,
- artifact kind: standalone LoRA adapter,
- merged into Qwen3.8 base weights: no.

The aborted r1 MES run produced no adapter and remains documented only as a runtime incident. The isolated reproduction probe was removed after validation.

Post-selection:
- GPU busy: 0%,
- VRAM idle: ~163 MiB,
- boot MES count: 0.

P5.4 ELECTRONICS FOUNDATION V3 = PASS.
