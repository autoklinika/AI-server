# AI Platform — Stage P3 Baseline Preparation

Date: 2026-09-28
Branch: stage-p3/baseline-v1
Entry baseline: P0/P1/P2 merged to main.

## Goal

Prepare authoritative LLM/router/retrieval-RAG baseline execution before any
automotive training. P3 keeps benchmark execution model-independent and separates
routing, retrieval, reranking and reasoning quality.

## P3 implementation

P3 adds benchmark-only router adapters:

- majority-knowledge-v1 — class-imbalance floor,
- rules-v1 — pipeline sanity adapter only,
- GLiNER2 local adapter — real decision-model evaluation.

GLiNER2 supports joint or separate route/tool classification heads and records
per-case CPU latency plus process peak RSS.


Router scoring now includes:

- route accuracy,
- macro-F1,
- tool-selection recall,
- exact tool-selection accuracy,
- false-positive tool rate,
- latency,
- peak RAM.

Macro-F1 is mandatory because 41/51 router cases currently route to
knowledge_rag; majority accuracy alone would therefore be misleading.

## Knowledge JSONL ingestion

A canonical JSONL ingestor was added for atomic ERS facts. Each JSONL record
becomes one canonical Knowledge chunk with stable record_id and source revision.

The source-cache dry run at ERS commit
81909b30ef18ca2053bd7496d6faeb814d4e9866 found four JSONL documents:

1. DIAGNOSTIC_KNOWLEDGE.jsonl,
2. Automotive Semiconductor Corpus MANIFEST.jsonl,
3. Microchip J1939 AN930 SOURCE_FACTS.jsonl,
4. NXP TJA1021 SOURCE_FACTS.jsonl.

Ingestion is idempotent and fails closed for malformed, duplicate or missing IDs.


## Dataset state

Current golden dataset validation:

- 72 total cases,
- 58 LLM,
- 61 retrieval/RAG,
- 51 router,
- 31 dev / 23 holdout / 18 challenge,
- 61 Polish / 9 English / 2 bilingual,
- 52 unique evidence source IDs,
- 10 OEM manifest sources,
- all records training_exclusion=true.

ERS provenance and coverage-policy gates: PASS.

## Reproducibility gate

Official live baselines now require clean Git worktrees for AI-server and ERS.
Dirty-tree execution is possible only with explicit --allow-dirty and is marked
exploratory in subject metadata.

GLiNER2 live execution additionally requires a pinned Hugging Face revision SHA.
The exact model revision is stored in the run artifact.

The GLiNER runtime fingerprint records Python, Torch, GLiNER2 version and SHA-256
of the actually loaded gliner2/models/base.py implementation.


Pinned candidate revisions resolved on 2026-09-28:

- fastino/gliner2.5-small-v1:
  7132dc4561c3f94563c6147e75ffa8ef34c4964a
- fastino/GLiNER2.5-multi-Decide:
  a35a0cd3b7a0f00f2effc576f454cd48fa98aa5f
- fastino/GLiNER2.5-Decide:
  5a7adf72a23b4d311abae6ce050d7f0012bb3416

## Exploratory router findings — not authoritative baseline

The following measurements were made before the clean-worktree gate existed.
They validate the benchmark design but MUST NOT be stored as accepted baseline
results because the AI-server worktree was dirty.

Majority-class floor shows route accuracy about 77–83% across splits while
macro-F1 stays around 0.22. This confirms strong class imbalance.

rules-v1 scores 100% but is deliberately dataset-shaped pipeline logic and is
not a model-quality baseline.


GLiNER2.5 small 74M, joint zero-shot:
- dev: route accuracy 60.9%, macro-F1 0.133, ~60 ms/case, ~1.21 GB RSS,
- holdout: 33.3%, macro-F1 0.151, ~59 ms/case,
- challenge: 53.8%, macro-F1 0.358, ~58 ms/case.

GLiNER2.5 multi-Decide 287M benefits strongly from separate described heads.
Dev calibration improved route accuracy from 39.1% joint to 69.6% separate.
The selected dev-only configuration is described labels, separate heads and
threshold 0.5. Threshold 0.7/0.8 did not improve tool selection.

With that exploratory configuration:
- holdout route accuracy 60.0%, macro-F1 0.405, ~244 ms/case, ~3.13 GB RSS,
- challenge 38.5%, macro-F1 0.250, ~260 ms/case.

GLiNER2.5-Decide 340M, separate heads:
- dev: route accuracy 82.6%, macro-F1 0.670, ~778 ms/case,
- holdout: 80.0%, macro-F1 0.705, ~569 ms/case,
- challenge: 76.9%, macro-F1 0.474, ~833 ms/case,
- peak RSS about 4.28 GB.


These exploratory results suggest a real quality/latency frontier:
340M currently gives the best routing quality; 74M gives the lowest CPU cost;
287M sits between them. None has production-grade tool selection in zero-shot
or simple calibration, so router-specific training remains justified.

No model ranking is accepted from these exploratory runs. The authoritative
comparison must be repeated from clean committed code with pinned model revisions.

## Training boundary

P3 still performs no SFT, LoRA/QLoRA, preference optimization, continued
pretraining or distillation. Router fine-tuning is considered only after the
authoritative routing baseline is persisted.

Large-LLM automotive training remains blocked until LLM fixed-evidence and
retrieval/RAG baselines are also complete.

## Validation

Focused P3/router/JSONL/runner/evaluation tests: PASS.
Dataset schema, ERS provenance and coverage policy: PASS.
Full repository regression is required before the implementation commit.


## Authoritative router baseline v1

After committing the P3 implementation, router baselines were repeated from a
clean worktree with pinned Hugging Face revisions. Raw run artifacts, evaluation
artifacts, confusion matrices and summary are stored under:

benchmarks/automotive_v1/results/router/p3-2026-09-28/

All runs use:
- AI-server commit 31ccb42855a06539785469dbe8dfdc1f2af7cc46,
- ERS commit 81909b30ef18ca2053bd7496d6faeb814d4e9866,
- dataset SHA-256 1f829de1eacdd8e19905e28f2d086161f94fd93c691bee586d6171976d0f8edf.


Authoritative route accuracy / macro-F1:

| Subject | Dev | Holdout | Challenge |
|---|---|---|---|
| majority floor | 82.6% / 0.226 | 80.0% / 0.222 | 76.9% / 0.217 |
| GLiNER2.5 small 74M | 60.9% / 0.133 | 33.3% / 0.151 | 53.8% / 0.358 |
| GLiNER2.5 multi-Decide 287M | 69.6% / 0.553 | 60.0% / 0.405 | 38.5% / 0.250 |
| GLiNER2.5 Decide 340M | 82.6% / 0.670 | 80.0% / 0.705 | 76.9% / 0.474 |

CPU mean per-case latency was about 58–61 ms for 74M, 246–253 ms for 287M,
and 571–753 ms for 340M. Peak RSS was about 1.21 GB, 2.98–3.00 GB and
4.28 GB respectively.

Tool exact accuracy remains weak even for 340M: 39.1% dev, 53.3% holdout and
46.2% challenge. This blocks production adoption of any tested checkpoint as a
complete route+tool policy.


Across all 51 router cases, 340M route recall is:
- graphify: 100%,
- reasoning: 100%,
- telemetry: 100%,
- tool/agent handoff: 100%,
- vision: 66.7%,
- knowledge_rag: 78.0%.

This identifies the first router-training curriculum targets: knowledge-vs-other
boundary precision, vision recall, and independent multi-tool selection.

The majority floor's high raw accuracy is not evidence of good routing; it gets
100% recall only for knowledge_rag and 0% for every minority route. Macro-F1 is
therefore the primary quality metric for router development.


## Production retrieval baseline — before JSONL sync

P3 also captured the current production Knowledge retrieval baseline before
applying the new record-level JSONL synchronization.

Runtime:
- release stage-o-491e982e627e,
- source SHA 491e982e627e8b550dcea0742693bb903009622f,
- Knowledge Service contract v1,
- hybrid retrieval, top-k 10.

Raw retrieval aggregate:
- dev Recall@1/3/5 59.6% / 76.9% / 92.3%, MRR 0.739,
- holdout 70.0% / 95.0% / 100%, MRR 0.829,
- challenge 73.3% / 93.3% / 100%, MRR 0.847.


With production reranking:
- dev Recall@1/3/5 59.6% / 96.2% / 100%, MRR 0.777,
- holdout 75.0% / 95.0% / 100%, MRR 0.843,
- challenge 80.0% / 93.3% / 100%, MRR 0.880.

Reranking therefore materially improves top-3/top-5 grounding with essentially
no observed latency penalty in this run (~254–260 ms/query).

Raw top-5 misses occur only on two dev cases: ERS-DK-0023 input protection and
Hatz CAN service-vs-customer topology. The reranker recovers both into top-5.

The pre-sync J1939 subgroup has raw Recall@1/3/5 55.6% / 77.8% / 88.9%;
reranking raises it to 66.7% / 88.9% / 100%. LIN has raw
66.7% / 100% / 100% and reranked 66.7% / 83.3% / 100%.

These artifacts are the A-side for an identical post-JSONL-ingestion A/B run.
