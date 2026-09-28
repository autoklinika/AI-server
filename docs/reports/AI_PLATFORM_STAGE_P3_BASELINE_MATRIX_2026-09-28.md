# AI Platform — Stage P3 Baseline Matrix

Date: 2026-09-28
Branch: stage-p3/baseline-matrix-v1
Parent: merged Stage P2 benchmark runners.

## Purpose

Prepare the first reproducible automotive baseline without starting training.
P3 separates retrieval, reranking, LLM reasoning, end-to-end RAG and decision
routing so a later improvement can be attributed to the correct subsystem.

## Matrix

Development gate order:
1. raw-vs-reranked retrieval on dev,
2. fixed-evidence reasoning and end-to-end RAG on dev,
3. decision/router zero-shot baseline on dev,
4. only after dev gate: holdout,
5. only after holdout gate: challenge.

Training remains forbidden by matrix contract.

## Router baseline

Initial checkpoints stay independent from the large LLM:
- fastino/GLiNER2.5-multi-Decide,
- fastino/GLiNER2.5-Decide,
- fastino/gliner2.5-small-v1.

The local adapter uses one classification call with two heads:
- route: reasoning / knowledge_rag / graphify / telemetry / vision / tool,
- tools: multi-label knowledge.search / graphify.query / vision.analyze /
  agent.ers / telemetry.read / none.

No generative fallback is used. The optional router-benchmark dependency keeps
GLiNER2/PyTorch outside normal production and CI installs.

## Resource measurement

P3 adds a system-level sampler using Linux /proc/meminfo and DRM
mem_info_vram_used when available. Per case it records baseline, peak, final,
sample count, and peak deltas for RAM and VRAM.

This is deliberately system-scoped. On the current 96 GiB UMA carve-out it is
not valid to claim that the delta belongs exclusively to one model if other
platform services are resident.

LLM/RAG throughput is computed only from returned output_tokens and execution
duration. If usage is unavailable, throughput is null rather than estimated.

The RAG Platform API now exposes provider usage as an additive response field;
existing clients remain compatible.

## GLiNER2.5 API basis

The official GLiNER2 interface supports AutoExtractor.from_pretrained and
classification using runtime-provided label sets. Multi-label classification
supports an explicit threshold, so route and tool heads can remain model-agnostic.
The multilingual Decide checkpoint is included specifically for the Polish-heavy
golden set, while English Decide and small-v1 remain comparison subjects.

P3 does not install these models yet. Model download/inference begins only after
the code gate and environment readiness check.

## Current gate status

Focused P3 + P2 runner/Knowledge tests: PASS.
Full repository regression after rebase onto merged P2: PASS.
No training job, checkpoint download, sudo action, or production cutover has been
performed by P3 development work.
