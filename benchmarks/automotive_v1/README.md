# Automotive Benchmark System v1

Status: P1 golden-dataset pilot gate after Stage O.

## Purpose

This benchmark layer answers one question before any automotive fine-tuning:
**did the candidate actually improve the ECU/electronics workload without
regressing grounding, routing, latency, or resource use?**

Knowledge, datasets, cases, provenance and scores are independent from model
family, inference provider and accelerator. Models are replaceable test subjects.

## Existing assets reused

- Stage J evidence-based retrieval benchmark and its source-commit capture.
- Qwen ventilation scenario pattern with explicit must/must-not behavior.
- ERS case provenance and separation of facts, hypotheses and confirmed causes.
- ERS Automotive Semiconductor Corpus v0: 22 OEM documents.
- ERS DIAGNOSTIC_KNOWLEDGE.jsonl: 28 atomic source-derived facts.
- Platform Resource Manager and stable Knowledge Service API.

The v1 layer does not replace those assets; it normalizes them into one eval contract.

## Architecture

1. **Source plane** — ERS cases, OEM corpus, canonical Knowledge sources.
2. **Golden dataset plane** — versioned JSONL with facts, evidence, forbidden
   claims, routing expectations, confidence and provenance.
3. **Suite plane** — three independent suites:
   - automotive-reasoning for large LLMs,
   - decision-models for routers/policy classifiers,
   - rag-knowledge for retrieval/reranking/RAG.
4. **Execution plane** — future live runners must enter the shared Resource
   Manager; direct provider bypass is prohibited.
5. **Observation plane** — provider-specific outputs are normalized before
   scoring. Deterministic scoring never depends on a model name.
6. **Result plane** — every run records dataset SHA-256, source Git revisions,
   suite version, runtime/resource metrics and per-case scores.

The checked-in JSON Schema is golden.schema.json; the executable source of
truth is ai_bridge.benchmarks.contracts.GoldenCase.

## Golden case invariants

Every required fact must be linked to explicit evidence. A case fails validation
if a required fact has no evidence locator. Golden data contains no preferred
LLM name. Router candidate names belong only to the router suite manifest.

Required fields include:

- question, category, difficulty and language,
- expected facts and source/evidence locators,
- acceptable reference answer and required concepts,
- forbidden claims,
- required tools and expected routing,
- grounding/fail-closed policy,
- expected confidence bounds,
- source/case provenance and reuse status.

## Suite boundaries

### Large LLM

Measures automotive reasoning, technical source work, incomplete-data behavior,
hallucination resistance, citations, tool use, PL/EN, multi-turn consistency,
latency, throughput and memory.

### Decision/router

Measures intent routing, Knowledge/RAG choice, Graphify/GraphRAG choice,
telemetry-vs-reasoning, tool selection, agent handoff, Vision requirement,
CPU latency, RAM and multilingual accuracy.

Initial required checkpoints are fastino/GLiNER2.5-Decide (340M),
fastino/GLiNER2.5-multi-Decide (287M) and fastino/gliner2.5-small-v1 (74M).

### Retrieval/RAG

Measures lexical, dense, hybrid, reranking, query expansion, aliases, part
numbers, MCU identifiers, DTC/case identity, architecture parameters, source
ranking, grounding, fail-closed and multi-turn context.

## Baseline gate

No SFT, LoRA/QLoRA, continued pretraining, preference optimization or
distillation is accepted before a reproducible baseline exists.

A training experiment must compare at least:
1. the current accepted baseline,
2. the candidate base model with the same RAG/tooling,
3. the tuned candidate with the same RAG/tooling.

The benchmark must retain per-dimension metrics. A single aggregate score is
not sufficient to accept a training change.

OEM documents marked retrieval_reference_only_pending_license_review may be
used as retrieval/evaluation references; they are not automatically approved
as training material.

## P1 golden dataset

The current golden.v1.jsonl contains 72 benchmark-only cases:

- 58 LLM-targeted,
- 51 router-targeted,
- 61 retrieval/RAG-targeted,
- 31 dev, 23 holdout and 18 challenge,
- 61 Polish, 9 English and 2 bilingual cases.

Hatz and Scania remain regression cases, not the scope boundary. Independent
OEM/reference evidence now includes driver/power sources plus NXP TJA1021 LIN
physical-layer facts and Microchip AN930 J1939 mechanics.

coverage_policy.json is a hard pilot-readiness gate. It checks total/target/
language/split counts, domain tags, unique evidence sources and OEM source
diversity. Declared gaps remain visible even when the gate passes.

Use ai-benchmark validate for schema/provenance/coverage validation and
ai-benchmark plan to create a non-executing reproducibility plan. The plan
explicitly forbids training and direct provider bypass.


## Evaluation tracks and contamination control

Golden cases are benchmark-only records. Every case carries
training_exclusion=true; future training/export pipelines must reject benchmark
records rather than merely ignore them by convention.

P1 uses explicit dev/holdout/challenge strata. Holdout and challenge cases
must never be used for SFT, LoRA/QLoRA, preference optimization, distillation
targets or synthetic-data prompting.

The LLM suite separates fixed-evidence reasoning from closed-book diagnostics and
tool/multi-turn behavior. Retrieval/RAG separates retrieval-only, retrieval plus
reranker, and end-to-end RAG. Router evaluation separates zero-shot, calibrated
and fine-tuned routing.

Canonical initial router checkpoints:
- fastino/GLiNER2.5-Decide (340M),
- fastino/GLiNER2.5-multi-Decide (287M),
- fastino/gliner2.5-small-v1 (74M).
