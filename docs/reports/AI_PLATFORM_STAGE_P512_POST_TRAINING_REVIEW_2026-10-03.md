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

## Manual review blockers

- SMOKE-01: P5.12 asks for input/output measurements on an unidentified IC; that premise still depends on knowing function/pins.
- SMOKE-03: weak channel isolation; it reintroduces the swapped load and does not clearly separate return/ground-path failure from driver failure.
- SMOKE-06: duplicated answer block indicates generation-quality instability.
- SMOKE-08: test is less direct than measuring coil state plus contact voltage drop under load at the failure instant.
- SMOKE-10: does not explicitly solve the known probe-loading problem with a sufficiently non-invasive/buffered clock measurement.
- SMOKE-11: misses the key common-mode/input-range boundary despite the good-channel comparison.
- SMOKE-12: semantically better than its heuristic score; simultaneous rail/MCU-supply/enable timing is useful, so the anchor scorer under-rates it.

## Decision

P5.12 training integrity and runtime engineering are accepted, but diagnostic quality is not.
Do not create a stable `diagnostic-reasoning-v1/current` alias and do not change the Stage O production model.
A corrective follow-up should target the failed physical-boundary cases while replaying P5.11/P5.12 strengths and retaining the standalone-LoRA contract.
