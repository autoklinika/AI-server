# AI Platform — Stage P5.12 post-training review — 2026-10-03

## Result

**QUALITY_GATE=FAIL — DO_NOT_PROMOTE_TO_PRODUCTION**

Production remains on `qwen3.8:27b-p4-64k-gpu-p511` with `automotive-specialization-v1`.

## Training and runtime evidence

- run: `diagnostic-reasoning-v1-20261002T225922Z`
- training: 160 microsteps / 40 optimizer steps, `P5_12_TRAINING_INTEGRITY=PASS`
- source adapter SHA-256: `14f52f936e3a562ee3ca9e2e05715ae76a612a752b72b2a4c045dca9b3f3bb4f`
- adapter tensors: 992
- host watchdog: PASS; Resource Manager lease released
- GPU error baseline/final: 12 / 12 (delta 0)
- post-training regression tests: 80/80 PASS
- DEV runtime: `qwen3.8:27b-p4-64k-gpu-p512-dev`
- runtime GGUF SHA-256: `0c75c21fe3a69945ad70e9f6339d7c23a5a4b2aca521b62ede2d717576fecbd7`
- runtime conversion/smoke command: PASS, RC=0

## Two-model smoke

All 24 generations completed: the same 12 unseen cases on P5.11 and P5.12.
Heuristic score: P5.11 = 52/124 (41.9%); P5.12 = 55/124 (44.4%).
Unsupported-component flags: P5.11 = 1; P5.12 = 0.
The heuristic improvement is too small to justify promotion and requires manual review.

## Evaluator audit

The anchor scorer is not valid as a standalone promotion metric. Scoring the user prompts themselves, with no diagnostic answer, produces **29/124 = 23.4%**. In `P512-SMOKE-06`, the prompt alone scores **6/11**, exactly the score obtained by P5.11 when it effectively echoes the task instead of answering it.

Root causes:
- substring anchors can be satisfied by copied prompt text;
- anchor presence does not validate semantic direction, causal order, negation, or whether a proposed test actually discriminates the stated hypotheses;
- `high_information_next_measurement` is derived only from two anchor hits;
- duplicated answer blocks are not penalized.

Therefore the 41.9%/44.4% figures are telemetry only. Manual semantic review is authoritative for this gate, and the evaluator must be corrected before it is reused as a promotion signal.

## Manual review blockers

- SMOKE-01: P5.12 asks for input/output measurements on an unidentified IC; that premise still depends on knowing function/pins.
- SMOKE-03: weak channel isolation; it reintroduces the swapped load and does not clearly separate return/ground-path failure from driver failure.
- SMOKE-06: duplicated answer block indicates generation-quality instability.
- SMOKE-08: test is less direct than measuring coil state plus contact voltage drop under load at the failure instant.
- SMOKE-10: does not explicitly solve the known probe-loading problem with a sufficiently non-invasive/buffered clock measurement.
- SMOKE-11: misses the key common-mode/input-range boundary despite the good-channel comparison.
- SMOKE-12: semantically better than its heuristic score; simultaneous rail/MCU-supply/enable timing is useful, so the anchor scorer under-rates it.

## Independent shadow audit

A second audit used six newly authored paraphrased diagnostic cases, run deterministically on both P5.11 and P5.12. Raw prompts and responses are preserved in `docs/reports/evidence/stage-p512-shadow-audit-2026-10-03.json`.

Findings:
- P5.12 is materially better on the driver-vs-path voltage-drop case, non-invasive oscillator probing, and relay coil-vs-contact discrimination.
- CAN long-stub discrimination is comparable and technically useful on both models.
- The current-sense case still misses the key input common-mode/range check and good-channel boundary, so the important SMOKE-11 weakness generalizes outside the official fixture.
- Generation repetition regresses sharply: exact repeated non-trivial lines occur in **4/6 P5.12** shadow responses versus **1/6 P5.11**. P5.12 repeats substantial blocks in SHADOW-01, -02, -04 and -05.

This independent sample confirms that P5.12 contains real diagnostic gains, but also confirms a generation-quality regression and incomplete transfer of the intended physical-boundary reasoning.

## Decision

P5.12 training integrity and runtime engineering are accepted, but diagnostic quality is not.
Do not create a stable `diagnostic-reasoning-v1/current` alias and do not change the Stage O production model.
A corrective follow-up should target the failed physical-boundary cases while replaying P5.11/P5.12 strengths and retaining the standalone-LoRA contract.
