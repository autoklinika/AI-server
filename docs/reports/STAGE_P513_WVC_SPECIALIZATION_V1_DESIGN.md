# Stage P5.13 — WVC specialization v1

Date: 2026-10-03

## Boundary

P5.13 trains a standalone WVC LoRA continuation from the accepted P5.11
`automotive-specialization-v1` adapter on Qwen3.8 27B.

It does not continue P5.12. P5.12 remains DEV/rejected for promotion because
the WVC baseline exposed temporal/cause-effect regressions and its independent
diagnostic review found repetition and physical-boundary weaknesses.

The P5.13 adapter remains separate from the base model. No merge into Qwen3.8
weights and no production cutover is part of the training step.

Parent:
- `/srv/ai-data/training/p5/adapters/automotive-specialization-v1/current`
- accepted source SHA-256:
  `46f38a1d4a4c26ce7800a4e05be8cbcb23da8b8f460e6f7faa8a73d577defdcb`

## Curriculum

96 project-owned WVC records cover 16 reasoning dimensions, six controlled
variants each:

1. validity gate,
2. command vs execution,
3. actuator feedback,
4. common vs local event,
5. sensor disagreement,
6. sensor-bus quality,
7. fault temporal sequence,
8. adjacent-window order,
9. setpoint/pollutant causality,
10. missing-signal boundary,
11. alarm scope boundary,
12. baseline absence,
13. VOC/NOx index semantics,
14. evidence hierarchy,
15. WVC domain boundary,
16. recovery is not root cause.

Every target explicitly separates observation, hypotheses and non-conclusions,
requires one discriminating next check, A/B interpretations, missing evidence
and a confidence boundary.

## Replay

64 train-only records preserve accepted prior skills:
- P5.11 automotive: 32,
- electronics foundation v1: 10,
- electronics foundation v2: 11,
- electronics foundation v3: 11.

Total: 160 rows. Replay fraction: 40%.

## Evaluation isolation

The frozen WVC corpus is evaluation-only:

`/srv/ai-data/evaluation/wvc-baseline/ollama-0.32.14-p511-vs-p512-20261003/corpus.json`

SHA-256:
`ae70251542d5d69ebac94d83b995238ea869e7e0282d62ed19d2f7501573e22a`

Preparation performs a host-side leakage gate and records the immutable corpus
identity. The training container deliberately does not mount evaluation data.
The prepared dataset has zero normalized-question overlap with the frozen ten
WVC questions under the configured shingle gate.

A separate 12-case synthetic smoke is also `training_eligible=false`.

## Dataset and token gates

- 96 new + 64 replay = 160,
- category balance = 6 per WVC dimension,
- exact duplicates = 0,
- max new-row near similarity = 0.808696 < 0.90 gate,
- max smoke/train similarity = 0.009804 < 0.58 gate,
- exact Qwen3.8 chat-template validation = 160/160,
- max full length = 582 tokens,
- max assistant target = 313 tokens,
- max allowed = 768,
- truncation = 0.

Canonical training dataset SHA-256:
`6dc44cc49e3f94e34a01e0c4c3d375a4d0ec3815fd74d581bd7353539c956957`

## Training contract

- base: Qwen3.8 27B BF16,
- parent: P5.11 standalone LoRA,
- LoRA rank: 8,
- fresh AdamW,
- learning rate: 1e-5,
- 160 microsteps,
- gradient accumulation: 4,
- 40 optimizer steps,
- max length: 768,
- `enable_thinking=false`,
- `HSA_USE_SVM=0`,
- pinned training image:
  `sha256:415b8e68c15d5bf9f7eeb6c4b697327953c600c875456ec5b12fccc1eb5414f8`.

Training is protected by the Resource Manager lease and the P5 GPU/host
watchdog. No service restart is performed by the runner.

## Post-training gate

A successful training process proves only training integrity.

The adapter must then:
1. pass manifest/hash/tensor/runtime conversion checks,
2. produce DEV model `qwen3.8:27b-p4-64k-gpu-p513-wvc-dev`,
3. pass the 12-case disjoint WVC smoke,
4. replay the immutable 10-case frozen WVC corpus against the same P5.11
   production baseline,
5. show no new GPU/MES failures,
6. undergo manual semantic review for validity gating, command-vs-execution,
   temporal order, causal restraint, evidence hierarchy, missing signals,
   WVC-domain fidelity and repetition.

Production remains P5.11 until a separate user decision.
