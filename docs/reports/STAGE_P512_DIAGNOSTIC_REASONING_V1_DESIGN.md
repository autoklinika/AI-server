# Stage P5.12 — Diagnostic Reasoning / Fault Isolation v1

## Boundary

P5.12 continues the accepted P5.11 automotive-specialization-v1 LoRA on Qwen3.8 27B. The adapter remains standalone and must not be merged into the base model. Production main, the Stage O release, and the P5.11 production alias remain outside this DEV/training change.

Parent:
- /srv/ai-data/training/p5/adapters/automotive-specialization-v1/current
- expected source adapter SHA-256: 46f38a1d4a4c26ce7800a4e05be8cbcb23da8b8f460e6f7faa8a73d577defdcb

Quality remains PENDING_POST_TRAINING_SMOKE until a disjoint two-model diagnostic smoke is reviewed.

## Dataset contract

The new curriculum contains 96 project-owned synthetic records: 32 diagnostic categories with three controlled variants per category:
1. idle/load or transition boundary measurement,
2. cold/hot comparison,
3. equivalent-good-channel comparison with two load states.

Every authored record contains an observation, known facts, physical model, explicit unknowns, 2–5 hypotheses, one discriminating measurement across a physical boundary, predicted A/B results, branch-specific interpretations and next measurements, a diagnostic trap, a non-conclusion, and confidence/missing-data language.

Replay protects earlier capabilities:
- 32 train-only P5.11 automotive records,
- 10 electronics foundation v1,
- 11 electronics foundation v2,
- 11 electronics foundation v3.

Total training rows: 160. Replay: 64 / 160 = 40%. No holdout/eval/test source is eligible for replay.

The 12-item diagnostic smoke set is authored separately and training_eligible=false.

## Dataset gates

Preparation and validation fail closed on duplicates, excessive near-duplicate similarity, smoke/train leakage, category imbalance, malformed reasoning specs, generic non-discriminating measurements, missing branch interpretations, answer-revealing prompts, unsupported numeric/pin/part claims, and parts-cannon conclusions.

The exact Qwen3.8 chat template is validated with enable_thinking=false. All 160 rows must fit max_length=768 with zero truncation.

## Training contract

- base: Qwen3.8 27B BF16
- parent: P5.11 standalone LoRA
- rank: 8
- optimizer: fresh AdamW
- learning rate: 1e-5
- microsteps: 160
- accumulation: 4
- optimizer steps: 40
- max length: 768
- enable_thinking: false
- HSA_USE_SVM=0
- output: /srv/ai-data/training/p5/adapters/diagnostic-reasoning-v1/<run-id>

The runner never restarts services. It blocks on a resident Ollama model, unexpected /dev/kfd owners, unreadable GPU telemetry, new MES/GPUVM/reset evidence, insufficient host memory, or an unhealthy Resource Manager. An explicitly SIGSTOP-quiesced comfyui.service worker owned by the operator may remain as the only /dev/kfd owner.

Training reserves Resource Manager workload=llm, heartbeats the lease for the run, and releases it on success, failure, or signal. The ComfyUI-only external-use endpoint is not used.

## Post-training gate

Before any production merge/deployment: training integrity must pass; parent/dataset/adapter hashes and tensor count must validate; GPU error delta must be zero; the lease must be released; DEV GGUF conversion must pass; only qwen3.8:27b-p4-64k-gpu-p512-dev is created; and the same 12 unseen cases are compared on P5.11 and P5.12 by concrete diagnostic criteria, not style.

Production remains P5.11 until the user decides otherwise.
