# AI Platform — Stage P4 LLM comparison — 2026-09-29

## Scope

Frozen automotive fixed-evidence benchmark, 58 LLM cases:
- 24 DEV
- 20 holdout
- 14 challenge

Dataset SHA-256:
`1f829de1eacdd8e19905e28f2d086161f94fd93c691bee586d6171976d0f8edf`

ERS source revision:
`81909b30ef18ca2053bd7496d6faeb814d4e9866`

Current benchmark branch revision:
`a5e0e54dbd166f238ebe11645b6b29035dbcdf73`

The semantic evaluator uses the same judge contract as the prior Qwen3.8 / gpt-oss review:
`gpt-5.6-sol-technical-benchmark-review / 2026-09-29-v1`.
## Current comparison

| Model | Structured completion | Fact recall | Citation precision | Citation recall | Mean latency | Mean throughput |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3.8 27B | 58/58 | 86.21% | 100.00% | 86.21% | 26.33 s | 6.41 tok/s |
| Granite 4.2 30B | 58/58 | 77.87% | 100.00% | 77.87% | 39.04 s | 3.95 tok/s |
| Nemotron Cascade 2 30B | 57/58 | 79.89% | 79.31% | 64.66% | 8.95 s | 21.01 tok/s |
| Ornith 1.5 35B | 58/58 | 80.17% | 81.03% | 62.07% | 7.69 s | 21.50 tok/s |
| gpt-oss 20B | 56/58 | 79.60% | 74.14% | 62.93% | 18.93 s | 9.93 tok/s |
| gpt-oss 120B | 56/58 | 68.10% | 85.78% | 64.66% | 26.02 s | 6.51 tok/s |

All semantically evaluated candidates recorded:
- forbidden claim rate: 0%
- Qwen3.8, Granite and Ornith: fail-closed accuracy 100%
- Nemotron: fail-closed aggregate 95.17% because the single structured failure was a fail-closed challenge case.

Mistral Small 4 119B completed 42/58 (72.41%) under the strict structured-output contract.
Its execution speed was strong (~12.8 tok/s), but 16 ValidationError cases make it operationally weaker for the current Platform contract.
## Execution notes

- Qwen3.8 27B remains the highest-quality measured candidate on the frozen automotive benchmark.
- Ornith 1.5 and Nemotron Cascade 2 are approximately 3x faster than Qwen3.8 on the measured physical-model path.
- Granite 4.2 is fully contract-stable but is the slowest candidate in this comparison.
- Larger total parameter counts did not produce higher automotive fixed-evidence quality in this round.
- MoE total parameter count must not be treated as equivalent to dense active compute per token.
- Semantic quality and execution reliability are evaluated separately; a model is not promoted solely because it is faster.

## Runtime isolation

The new candidate tests used staging Ollama 0.34.4 on localhost with ROCm and the 96 GiB unified-memory GPU.
Production Ollama remained on 0.32.14 and the production `reasoning-main` contract was not changed.

After the benchmark:
- staging model residency was cleared;
- production Resource Manager was `ready`;
- production active jobs = 0;
- production queued jobs = 0.

## Decision boundary

This report records evidence only. Selection or promotion of the base model remains an explicit user decision.
