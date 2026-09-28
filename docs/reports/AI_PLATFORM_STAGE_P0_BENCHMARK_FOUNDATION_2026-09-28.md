# AI Platform — Stage P0 Benchmark Foundation

Date: 2026-09-28
Branch: stage-p/benchmark-foundation-v1
Entry baseline: Stage O production complete.

## Goal

Create a model-independent evaluation layer before any automotive training.
The layer separates large-LLM reasoning, decision/router quality and
retrieval/RAG quality, while preserving provenance and reproducibility.

## Audit: existing AI-server benchmarks

Stage J knowledge benchmark is a strong retrieval seed: 13 evidence-based
queries, exact source commits, Recall@1/3/5 and MRR, plus embedding/search
latency. Its current limitation is scope: dense retrieval, a small corpus and
hard-coded queries.

The historical Qwen ventilation benchmark contributes a useful safety pattern:
positive requirements plus explicit forbidden claims. It is domain-specific and
not a reusable automotive benchmark contract.

Control Center already exposes a read-only Benchmark app and stable Platform API.
Before P0, decision-models, automotive-reasoning and rag-knowledge were planned
catalog entries without a shared dataset or scoring contract.

## Audit: ERS data

ERS currently provides two real repair cases as regression material, but the
knowledge base is already broader than those cases:

- 22 verified OEM/reference documents in Automotive Semiconductor Corpus v0,
- 28 atomic source-derived diagnostic records with page-level provenance,
- NXP, ST, Infineon, TI, Renesas, Microchip and ADI coverage,
- output drivers, CAN physical layer, ECU power/protection and MCU material,
- explicit separation of source fact, generalizable pattern and diagnostic use.

Licensing is intentionally conservative. Corpus entries marked
retrieval_reference_only_pending_license_review are valid evaluation/retrieval
references but are not automatically approved as training data.

## Gaps found

- no common golden-case schema,
- no independent router suite,
- retrieval quality and reasoning quality could be confounded,
- no normalized observation/scoring contract,
- no dataset hash/run-plan contract,
- no cross-repository provenance validator,
- no baseline gate preventing premature fine-tuning.

## P0 implementation

Implemented under benchmarks/automotive_v1 and ai_bridge.benchmarks:

- strict GoldenCase contract and checked-in JSON Schema,
- three independent suite manifests: LLM, router, retrieval/RAG,
- golden.v1.jsonl seed with 14 cases and explicit forbidden claims,
- deterministic normalized scoring primitives,
- source-level Recall@K, MRR and nDCG@5 support,
- route/tool/fail-closed scoring,
- run planning with dataset SHA-256 and source Git revisions,
- execution contract requiring Resource Manager and forbidding training,
- optional ERS provenance validation against case/source registries,
- ai-benchmark CLI entry point.

Current golden seed distribution:

- 14 total cases,
- 10 LLM-targeted,
- 8 router-targeted,
- 12 retrieval/RAG-targeted,
- 12 Polish and 2 English cases,
- 14 distinct initial categories.

Scania S6 and Hatz remain regression cases only; OEM-derived electronics cases
form most of the technical scope.

## Attribution strategy

P1/P2 must preserve causal attribution between subsystems.

LLM reasoning will include an evidence-conditioned track using fixed canonical
source evidence. This measures reasoning without retrieval variance. A closed-book
track may be retained for diagnostics but must not be treated as the knowledge
source of truth.

Retrieval-only runs will score whether the correct evidence is found and ranked.
End-to-end RAG runs will then score retrieval plus grounded answer generation.
Router runs remain independent from the large LLM and measure routing/tool policy.

This structure lets a future change answer whether the gain came from the model,
embedding/retrieval, reranking, routing or training.

## Verified current host facts

Observed on 2026-09-28:

- AMD Ryzen AI 9 HX 470, 12 cores / 24 threads,
- Radeon 890M integrated GPU,
- DRM VRAM carve-out: 103079215104 bytes = 96 GiB,
- current VRAM use during observation: about 22.4 GiB,
- host-visible RAM after carve-out: about 30 GiB,
- /dev/kfd is present,
- rocminfo is not installed,
- Python/PyTorch training stack is not installed,
- Ollama currently runs qwen3.6:35b, 28 GB, reported 77% GPU / 23% CPU,
  with 262144 context configured.

## Practical workload assessment before measurement

- inference: already proven locally for the current 35B quantized workload;
- embeddings: practical now through the existing Gateway/Resource Manager;
- rerankers: expected to be practical; benchmark latency/memory before acceptance;
- router inference/training: practical, including CPU-first experiments;
- LoRA/QLoRA: technically plausible after ROCm/PyTorch validation; start at
  small/medium model sizes and measure tokens/s before larger experiments;
- full-parameter SFT / continued pretraining of large LLMs: not a sensible first
  workload on the integrated GPU despite the large memory carve-out;
- large-model QLoRA may fit in memory but memory capacity must not be confused
  with iteration speed. Compute and shared-memory bandwidth become the limiter.

No hardware choice is encoded into the benchmark model shortlist.

## Next gates

P1 — expand the golden set and source coverage, especially LIN/J1939, EEPROM/Flash,
sensors/actuators, schematics, PCB and insufficient-evidence adversarial cases.

P2 — implement Resource-Manager-backed live runners and provider adapters.

P3 — run baseline matrix for LLM, router and retrieval/RAG with resource telemetry.

P4 — decide whether measured gaps justify SFT, LoRA/QLoRA, preference work,
distillation, synthetic data, continued pretraining or RAG/reranking changes.

P5 — only then run the selected training experiment and compare against P3.


## Contamination policy

Golden cases are explicitly benchmark-only and carry training_exclusion=true.
The current seed is split=dev; P1 will add holdout and challenge strata.
Future training/export pipelines must reject benchmark records and preserve
document/case provenance so unseen-document and unseen-case evaluation remains
possible.

Run plans are track-specific. An LLM reasoning run cannot silently become an
end-to-end RAG run, and a retrieval run cannot be compared to a reranked run
without changing the recorded track.

## Current external compatibility verification

AMD ROCm 10.0 compatibility documentation currently lists Ryzen AI 400 APUs,
Radeon 890M / gfx1150 and Ubuntu 26.04 as supported combinations. AMD's GPU
specification page identifies Ryzen AI 9 HX 470 with Radeon 890M, RDNA 3.5,
gfx1150 and dynamic + carveout memory.

This establishes a supported software path, not a measured training speed.
The local host still lacks rocminfo and PyTorch, so P0 does not claim training
readiness.


Official router model cards were also verified before freezing checkpoint names:
fastino/GLiNER2.5-Decide is the 340M English decision/classification checkpoint;
fastino/GLiNER2.5-multi-Decide is the 287M multilingual checkpoint; and
fastino/gliner2.5-small-v1 is the 74M compact English boundary checkpoint.

External references checked on 2026-09-28:
- AMD ROCm 10.0 compatibility matrix
- AMD ROCm GPU specifications
- Hugging Face model cards under the fastino organization


## Development validation

- benchmark/API/Control Center focused regression: PASS,
- full AI-server pytest regression: PASS, exit code 0,
- benchmark module compileall: PASS,
- git diff --check: PASS,
- CLI schema/suite/provenance validation: PASS,
- non-executing run-plan generation: PASS.

Example frozen run-plan inputs before commit:
- golden dataset SHA-256: 6d1b0e9758f9663c75dfdab61f582512e710f6b01efc3209909fe5b4df3a87af
- ERS source commit: 2e52551e7550448a135d1a844798ce1b53aa432b
- track: reasoning_fixed_evidence

No sudo, service restart, production cutover, model download, benchmark inference
or training job was performed in P0.
