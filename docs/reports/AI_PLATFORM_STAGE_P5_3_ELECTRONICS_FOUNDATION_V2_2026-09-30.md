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
