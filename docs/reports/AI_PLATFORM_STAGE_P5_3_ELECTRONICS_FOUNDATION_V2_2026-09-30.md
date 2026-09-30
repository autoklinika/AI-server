# AI Platform — Stage P5.3 Electronics Foundation v2

Date: 2026-09-30
Base model: Qwen3.8-27B
Parent adapter: electronics-foundation-v1 R1
Branch: stage-p5.3/electronics-foundation-v2

## Objective

Expand electronics reasoning with new physical/electrical domains without retraining the v1 curriculum and without accepting gains that erase v1 skills.

Acceptance is dual-holdout:
- new v2 holdout must improve by at least 5% versus frozen R1 baseline,
- frozen v1 holdout may regress by at most 3% versus selected R1.
## Dataset v2

Training:
- 155 records,
- 31 new categories,
- 59,453 tokens,
- mean 383.57 tokens/record,
- max 438 tokens,
- SHA-256: bbead16839dccbecf8fb4b4f0373d80c88bc9cb98540a1dd40b7ec448dfe061a.

Holdout:
- 24 records,
- 8 separate unseen categories,
- 9,179 tokens,
- mean 382.46 tokens/record,
- max 405 tokens,
- SHA-256: f3eaaef82fe4f6203591518e74b3d031cbbafa51dd2c1ab41524dc5031978fd5.

All 213 v1 train+holdout records were checked for exact and high-shingle overlap. Dataset gate and readiness tests PASS.
## New reasoning domains

V2 adds topics including AC impedance, RLC resonance and Q, capacitive/inductive coupling, transformer ratio and saturation, optocoupler CTR, Zener shunt regulation, current sources/mirrors, MOSFET gate charge and Miller plateau, switching loss, RC/RCD snubbers, SOA, thermal resistance/runaway, inrush/eFuse behavior, reverse-polarity MOSFETs, logic thresholds/level shifting, ADC sample-and-hold/reference noise, four-wire measurement, high-speed return paths, transmission-line reflections, common-mode EMI and ground loops.

The v2 holdout uses different families such as charge pumps, instrumentation amplifiers, TIA stability, crystal startup, DAC settling, stubs, foldback and common-mode chokes.
## Frozen baseline before v2 training

Selected electronics-foundation-v1 R1 evaluated on the new v2 holdout:
- token-weighted loss: 1.059440,
- mean case loss: 1.060268,
- median case loss: 1.036448,
- perplexity: 2.8848,
- records: 24,
- target tokens: 4,566.

This baseline was captured before the selected R1 adapter saw any v2 training record.

## First v2 attempt — new-only curriculum

Run ID: electronics-foundation-v2-r1-20260930

Training:
- source adapter: selected electronics-foundation-v1 R1,
- steps: 40/40 PASS,
- learning rate: 5e-5,
- training time: 704.001 s,
- throughput: 21.685 tokens/s,
- adapter SHA-256: 1b116857370e31a8155b351e42e06e572e6a49d6aa4ac7d7f94ac5ca8f07086d.

New v2 holdout improved from 1.059440 to 0.698678: +34.0521% relative improvement.
However the frozen v1 holdout regressed from 1.165698 to 1.259807: 8.0732% regression.

Dual-holdout gate: FAIL because the permitted v1 regression is at most 3%.
The new-only adapter is retained for audit but is not selected.

## Replay remediation

To prevent catastrophic forgetting, the rejected adapter is not used as the next base. Replay training restarts from the selected v1 R1 adapter.

Replay dataset:
- 155 new v2 records,
- 52 sampled v1 train-only replay records,
- total 207 records,
- no v1/v2 holdout records,
- deterministic seed 20260930,
- first 40 examples after trainer shuffle: exactly 30 v2-new + 10 v1-replay,
- replay dataset SHA-256: f3fbe5d921cb27c57845d8cdbd4155666f638b2211a62081f8133db3a1204e69.

Replay calibration uses LoRA r=8, 40 steps and a reduced learning rate of 3e-5.
Selection remains subject to the same dual-holdout gate.

## Replay result — PASS

Run ID: electronics-foundation-v2-replay-r1-20260930

Training:
- parent adapter: selected electronics-foundation-v1 R1,
- replay mix: 30 new-v2 + 10 v1 replay examples in the first 40 shuffled steps,
- steps: 40/40 PASS,
- learning rate: 3e-5,
- LoRA rank: 8,
- trainable parameters: 58,363,904,
- training time: 702.902 s,
- mean step time: 17.571 s,
- throughput: 21.771 tokens/s,
- peak VRAM allocated: 57,185,078,784 bytes,
- peak VRAM reserved: 59,169,046,528 bytes,
- adapter SHA-256: 96c6565a6b1f29c1c86716e90c966aef09915009bd1041639bdd545e1383c84c.

Dual holdout:
- v2 baseline loss: 1.059440,
- selected v2 loss: 0.726067,
- v2 relative improvement: 31.4669%,
- frozen v1 reference loss: 1.165698,
- selected v1 loss: 1.160553,
- v1 relative regression: -0.4414% (slight improvement),
- required v2 improvement: >=5%,
- maximum allowed v1 regression: <=3%,
- dual-holdout gate: PASS.

The replay strategy solved the catastrophic-forgetting failure from the new-only run.

## Selection

Selected electronics foundation v2 adapter:
- run: electronics-foundation-v2-replay-r1-20260930,
- stable alias: /srv/ai-data/training/p5/adapters/electronics-foundation-v2/current,
- adapter SHA-256: 96c6565a6b1f29c1c86716e90c966aef09915009bd1041639bdd545e1383c84c,
- status: selected_for_next_stage_not_deployed.

The rejected new-only adapter is retained at:
- /srv/ai-data/training/p5/adapters/electronics-foundation-v2/rejected-new-only-r1

Post-run:
- GPU busy: 0%,
- VRAM idle: ~163 MiB,
- host MemAvailable: ~27 GiB,
- new MES ring-full events: 0.

P5.3 ELECTRONICS FOUNDATION V2 = PASS.

The next electronics expansion must again use new domains plus replay protection and the same dual-holdout policy. The selected v2 adapter is not yet the production automotive adapter.
