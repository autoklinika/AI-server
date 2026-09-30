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
