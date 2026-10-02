# AI Platform — Stage P5.11 Automotive Specialization v1

Date: 2026-10-02

Status before GPU run: **TRAINING DATA / RUNNER READY; QUALITY ACCEPTANCE DEFERRED**.

## Purpose

Continue Qwen3.8-27B LoRA training from the selected electronics-foundation-v3 adapter with a strong automotive-electronics specialization. The independent evaluation corpus will be expanded over time and does not gate this training run.

This stage does not consume P5.10 acquisition/evaluation candidates and does not open protected golden/final/test material.

## Training composition

- 155 project-owned automotive diagnostic reasoning records from automotive_curriculum_v2.
- 28 original Polish evidence-first scenarios authored from the curated ERS Diagnostic Knowledge fields topic, subtopic, generalizable_pattern, diagnostic_use, and source_id; source_fact is not copied into training.
- 61 replay records selected only from v1/v2/v3 electronics TRAIN files.
- total: 244 records.
- replay: exactly 25%.
- 53 automotive/electronics categories in the new 183-record portion.

## Training contract

- base: Qwen3.8-27B BF16 buffered checkpoint.
- parent: electronics-foundation-v3/current.
- LoRA rank: 8; adapter remains standalone and is not merged into base weights.
- learning rate: 2e-5.
- context cap: 640 tokens; tokenizer preflight measured maximum 531 tokens, so no target truncation is needed.
- schedule: 244 once-through microsteps accumulated into 64 optimizer steps (52 groups of four and 12 groups of three).
- fresh optimizer; parent LoRA weights are resumed.
- stability profile: HSA_USE_SVM=0.

## Runtime safety

The runner refuses to start with more than 2 GiB VRAM already used, a resident Ollama model, low host memory, or an unexpected /dev/kfd owner. It records current-boot kernel baselines and aborts on new MES WAIT_REG_MEM, MES ring buffer is full, AMDGPU reset/fault, KFD/GPUVM or relevant IOMMU fault evidence.

Failure preserves run logs, telemetry and evidence and never advances the stable alias. Success requires finite losses/gradients, exactly 244 microsteps and 64 optimizer steps, valid LoRA files/manifest, zero GPU-error delta and released resources before atomically updating automotive-specialization-v1/current.

## Acceptance boundary

A successful P5.11 run means **training integrity PASS**, not final quality acceptance. Automotive quality/regression acceptance remains pending future independent evaluation material as it is accumulated.
