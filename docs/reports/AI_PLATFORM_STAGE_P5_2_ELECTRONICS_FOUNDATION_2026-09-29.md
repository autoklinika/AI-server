# AI Platform — Stage P5.2 Electronics Foundation

Date: 2026-09-29
Base model: Qwen3.8-27B
Branch: stage-p5.2/electronics-foundation-v1

## Objective

Teach the base model reusable electronics reasoning before adding automotive/OEM specialization.

The adapter must learn first-principles reasoning:
- identify known data and unknowns,
- choose the correct circuit model or physical law,
- derive a conclusion rather than guess,
- select a discriminating measurement when evidence is incomplete,
- interpret the measurement,
- state the answer and confidence separately.

Exact OEM pinouts, revisions, procedures and downloaded vendor text are intentionally excluded from this foundation.

## Dataset v1

Source class: project-owned derived electronics principles; no external text copied.

Training:
- 189 records
- 37 categories
- SHA-256: 7c11610a9e2c6a6ce373038164cb3427c89c16bb64a07122218cc40df525a7ac
- 72,593 tokens
- mean 384.09 tokens/record
- max 416 tokens

Holdout:
- 24 records
- separate problem families
- SHA-256: 385cb2b78755784d1ca086e0c37fbca8247c7af1f9b86d64ed8a132eabcc3e58
- 8,448 tokens
- mean 352 tokens/record
- max 367 tokens

Dataset/readiness gate: PASS.

## Reasoning curriculum

Covered areas include:
- Ohm/Kirchhoff, series/parallel and source impedance,
- voltage dividers, pull-up/pull-down and RC,
- diode/clamp/TVS behavior,
- BJT and MOSFET switching, body diode and gate drive,
- high-side, low-side, half-bridge/dead-time,
- inductive energy and flyback,
- capacitor ESR and decoupling,
- LDO, buck and boost power stages,
- op-amp and comparator/hysteresis,
- shunt/current sensing, ADC and PWM,
- low-pass filtering,
- open/short reasoning,
- DMM and oscilloscope limitations,
- scope grounding and differential measurement,
- PCB short/current-injection localization,
- thermal diagnostics,
- connector/contact resistance,
- relay diagnostics,
- reset/brownout/power sequencing,
- open-drain logic and measurement reference.

Every target answer follows:
DANE -> MODEL/PRAWO -> WNIOSKOWANIE -> POMIAR/KONTROLA -> ODPOWIEDŹ -> PEWNOŚĆ.

## Pre-training holdout baseline

Pure Qwen3.8-27B, no electronics adapter:
- records: 24
- target tokens: 3,765
- mean case loss: 1.557365
- token-weighted loss: 1.560165
- median case loss: 1.574840
- perplexity: 4.7596
- evaluation time: 103.07 s
- baseline artifact: /srv/ai-data/training/p5/evals/electronics-base-v1.json

This frozen holdout is not used for LoRA optimization.

## Round R1 — 40-step calibration

Run ID: electronics-foundation-v1-r1-20260929

Training:
- steps: 40/40 PASS,
- LoRA rank: 8,
- target modules: 496,
- trainable parameters: 58,363,904,
- max_length: 448,
- learning rate: 1e-4,
- model load: 15.266 s,
- training time: 710.934 s,
- mean step: 17.772 s,
- throughput: 21.615 tokens/s,
- peak VRAM allocated: 57,211,530,240 bytes,
- peak VRAM reserved: 59,301,167,104 bytes,
- adapter SHA-256: 9b52b30908baf29f21856ec2f0777dfd6b7d2e4a7f3b83b521127917c3034935.

Post-run GPU returned to idle (~163 MiB VRAM) and MES ring-full recurrence remained zero.

## R1 frozen-holdout result

The exact same 24-record frozen holdout was evaluated before and after training.

Base Qwen3.8:
- token-weighted loss: 1.560165,
- perplexity: 4.7596,
- mean case loss: 1.557365.

Electronics R1:
- token-weighted loss: 1.165698,
- perplexity: 3.2082,
- mean case loss: 1.163343,
- median case loss: 1.197434.

Improvement:
- absolute token-weighted loss: 0.394467,
- relative improvement: 25.2837%,
- required minimum: 5%,
- P5.2 electronics holdout gate: PASS.

R1 is therefore accepted as evidence that the LoRA learned transferable electronics reasoning patterns beyond the training records. It is still an experimental foundation adapter and is not yet a production automotive adapter.

## Round R2 — staged continuation and early stop

R2 resumed the R1 adapter weights with a fresh optimizer, used the same deterministic shuffle, and advanced to records 41–80 (start_index=40). Learning rate was reduced from 1e-4 to 5e-5.

Run ID: electronics-foundation-v1-r2-20260929

Training:
- steps: 40/40 PASS,
- resume mode: adapter_weights_only_fresh_optimizer,
- source adapter: R1,
- start index: 40,
- learning rate: 5e-5,
- training time: 705.949 s,
- mean step: 17.647 s,
- throughput: 21.666 tokens/s,
- peak VRAM allocated: 57,224,953,856 bytes,
- peak VRAM reserved: 59,382,956,032 bytes,
- adapter SHA-256: eb4541ec5e5de3028b50c6f6bbcaec045405543b29c319ee0f7ebd317b3308f8.

R2 frozen-holdout:
- token-weighted loss: 1.181073,
- perplexity: 3.2579,
- mean case loss: 1.178269,
- relative improvement vs base: 24.2982%,
- relative change vs R1: -1.3190% (regression).

R2 remains substantially better than the untuned base, but it is worse than R1 on the same frozen unseen holdout. Therefore the training series is early-stopped at R1.

Selected electronics foundation adapter:
- run: electronics-foundation-v1-r1-20260929,
- adapter SHA-256: 9b52b30908baf29f21856ec2f0777dfd6b7d2e4a7f3b83b521127917c3034935,
- stable alias: /srv/ai-data/training/p5/adapters/electronics-foundation-v1/current,
- status: selected_for_next_stage_not_deployed.

R2 is retained for audit at the r2 alias but is not selected.
