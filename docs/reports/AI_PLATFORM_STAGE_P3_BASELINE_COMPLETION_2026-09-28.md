# AI Platform — Stage P3 Baseline Completion

Date: 2026-09-28  
Branch: `stage-p3/baseline-completion-v1`

## Scope

P3 establishes the reproducible pre-training baseline for the current AI Platform.
No SFT, LoRA/QLoRA, preference optimization, continued pretraining or distillation
was performed.

The benchmark remains model-independent and keeps routing, retrieval/reranking,
fixed-evidence reasoning and end-to-end RAG as separate tracks.

## Entry state

- golden automotive dataset: 72 cases,
- router baseline and pre/post JSONL retrieval artifacts already persisted,
- production runtime during baseline: `stage-o-491e982e627e`,
- ERS source commit: `81909b30ef18ca2053bd7496d6faeb814d4e9866`.

## Router baseline

Authoritative CPU router results remained:

| Subject | Dev route acc / macro-F1 | Holdout | Challenge |
|---|---:|---:|---:|
| GLiNER2.5 small 74M | 60.9% / 0.133 | 33.3% / 0.151 | 53.8% / 0.358 |
| GLiNER2.5 multi-Decide 287M | 69.6% / 0.553 | 60.0% / 0.405 | 38.5% / 0.250 |
| GLiNER2.5 Decide 340M | 82.6% / 0.670 | 80.0% / 0.705 | 76.9% / 0.474 |

Tool exact accuracy is still insufficient for production route+tool policy.
No router checkpoint is promoted by P3.

## Retrieval baseline

Record-level JSONL ingestion was idempotent: all four JSONL sources were already
present at the same source revision. Reindex jobs completed successfully.

Post-reindex hybrid retrieval:

- raw dev Recall@1/3/5 = 59.6% / 82.7% / 92.3%,
- raw holdout = 70.0% / 95.0% / 100%,
- raw challenge = 73.3% / 93.3% / 100%,
- reranked dev = 59.6% / 96.2% / 100%,
- reranked holdout = 75.0% / 95.0% / 100%,
- reranked challenge = 80.0% / 93.3% / 100%.

Retrieval latency remained approximately 255–270 ms/query. Reranking remains the
accepted retrieval baseline.

## Fixed-evidence reasoning baseline

All 58 LLM-targeted cases executed successfully after fixing deterministic
representation of binary/PDF evidence.

| Split | Completion | Fact recall | Citation precision | Citation/grounding recall | Forbidden claims | Fail-closed |
|---|---:|---:|---:|---:|---:|---:|
| dev | 24/24 | 75.0% | 83.3% | 68.75% | 0% | 100% |
| holdout | 20/20 | 72.5% | 85.0% | 65.0% | 0% | 100% |
| challenge | 14/14 | 28.6% | 92.9% | 28.6% | 0% | 100% |

Mean generation-path latency was 11.28 s dev, 10.18 s holdout and 6.57 s
challenge.

The main quality weakness is omission: on difficult questions the model often
returns a safe but incomplete answer rather than hallucinating.

## End-to-end RAG baseline — limit=10

Dev completed 26/26 with zero execution errors.

- fact recall: 84.6%,
- citation precision: 96.2%,
- citation/grounding recall: 82.7%,
- forbidden claim rate: 0%,
- fail-closed accuracy: 100%,
- mean generation-path latency: 56.6 s,
- max latency: 95.9 s.

RAG materially improves answer completeness versus fixed-evidence reasoning, but
the current context/generation cost is too high.

## RAG A/B — limit=5

The smaller retrieval limit initially reduced typical prompt size and latency.
Examples fell from roughly 40–60 s to roughly 28–40 s after warm-up.

The candidate failed the dev gate on `ERS-GOLD-0010`:

- structured generation ran for the full 600 s benchmark request budget,- more than 10,500 output tokens were generated before timeout cancellation,
- the Resource Manager job correctly transitioned to `expired`,
- Ollama cancelled the active task when the platform timeout fired.

The full limit=5 run was intentionally aborted after the dev failure. It is not
an accepted baseline configuration.

A separate behavior was confirmed: terminating the benchmark client itself did
not immediately cancel the server-side job. This prompted a client-disconnect
cancellation fix.

## P3 completion fixes

### Deterministic binary evidence

Binary/PDF evidence locators no longer crash fixed-evidence benchmarks with
UTF-8 decode errors. They produce a deterministic metadata stub containing file
name, byte size and SHA-256; semantic facts still come from text sources.

### Bounded RAG output

RAG generation now has:

- `knowledge_rag_max_output_tokens = 1024`,
- concise/non-repeating prompt requirements,
- maximum claim text length reduced to 1600 characters,
- maximum insufficiency reason reduced to 800 characters,
- benchmark RAG request budget aligned to 300 s.

The generic LLM provider contract gained an optional `max_output_tokens`, mapped
to Ollama `num_predict`.

### Benchmark telemetry

Benchmark artifacts now record:

- output-token throughput in tokens/s,
- system-scoped RAM baseline/peak/final and peak delta,
- system-scoped VRAM baseline/peak/final and peak delta,
- RAG provider token usage.

System scope is intentional for the current UMA platform; P3 does not falsely
attribute shared memory to one model.

### Client-disconnect cancellation

Platform RAG now watches the HTTP client connection while provider generation is
active. If the client disconnects, the provider task is cancelled before the
Resource Manager lease is released.

## Validation

For each implementation step, focused tests passed. After the final changes the
full AI-server regression suite passed with no test failures and `git diff --check` passed.

## Gate status

P3 development implementation: **PASS**.

Current accepted baseline configuration remains:

- hybrid Knowledge retrieval,
- production reranker enabled,
- RAG `limit=10` as the reference baseline until the bounded-output patch is
  production-validated,
- current `reasoning-main` model only as the baseline subject, not as the
  selected future automotive model.

Production validation of the bounded-output/cancellation/telemetry patch is
required after merge before P3 can be marked production-complete.

After that gate, the next major activity is the comparative benchmark of large
LLM candidates using this frozen baseline, followed by model selection and only
then automotive training/fine-tuning experiments.
