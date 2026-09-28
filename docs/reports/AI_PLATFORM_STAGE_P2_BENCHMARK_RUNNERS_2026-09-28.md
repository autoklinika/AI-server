# AI Platform — Stage P2 Benchmark Runners

Date: 2026-09-28
Branch: stage-p2/benchmark-runners-v1
Parent: Stage P1 golden dataset expansion.

## Goal

Turn the model-independent benchmark contracts into executable, reproducible
runners without bypassing AI Platform resource management or binding the
benchmark to a specific model/provider/backend.

## Execution boundary

All live LLM and Knowledge execution goes through stable Platform API v1.
The runner never calls Ollama, Qdrant or embedding/reranker internals directly.

Platform readiness and Resource Manager readiness are checked before execution.
LLM/RAG benchmark jobs use background priority. Live CLI runs require an
explicit split or case ID and an output artifact path.

## Implemented runners

- fixed-evidence LLM reasoning through /api/v1/ai,
- raw retrieval through /api/v1/knowledge/search with rerank=false,
- retrieval plus TechnicalEvidenceReranker with rerank=true,
- end-to-end grounded RAG through /api/v1/knowledge/ask,
- isolated router-adapter contract for router benchmarks,
- dry-run mode for full selection/configuration validation without inference.

The Knowledge API received a backwards-compatible rerank boolean. Default is
true, preserving all existing clients. This is required because production
KnowledgeRuntime previously always reranked results, making a true retrieval-only
benchmark impossible through the stable API.

## Evidence-conditioned LLM track

Fixed-evidence reasoning resolves golden evidence from versioned ERS/AI-server
sources before the model call. Missing evidence aborts before Platform execution.
The prompt requires use of supplied evidence only and exact source IDs.

This track measures reasoning quality without retrieval variance.

## Evaluation boundary

Execution artifacts and evaluation artifacts are separate.

Automatic router scoring uses normalized route/tool observations.
Retrieval can use deterministic source-identity-v1 evaluation based on exact
repository locators/source URIs and atomic source IDs in JSONL evidence.
Semantic LLM/RAG evaluation requires an explicit EvaluationBundle carrying
an evaluator type, identifier and version. P2 does not silently invoke an
LLM-as-a-judge.

Finalization rejects:
- dry-run artifacts,
- mismatched run/evaluation IDs,
- duplicate evaluation case IDs,
- unknown result IDs/fact IDs,
- run artifacts whose case_count is inconsistent,
- a golden dataset whose current SHA-256 differs from the run artifact.

These checks prevent scoring historical output against changed gold data.

## P1 dataset state used by P2

Current working dataset contains 72 benchmark-only cases:
- 58 LLM,
- 61 retrieval/RAG,
- 51 router,
- 31 dev / 23 holdout / 18 challenge,
- 61 PL / 9 EN / 2 bilingual,
- 44 unique evidence sources,
- 10 OEM manifest sources,
- 72/72 training_exclusion=true.

Schema, provenance and coverage policy validation: PASS.

Dry-run selection over all splits:
- reasoning_fixed_evidence: 58 cases,
- retrieval_only: 61 cases,
- routing_zero_shot: 51 cases.

All three dry runs used the same dataset hash and expected endpoints.

## Production-contract smoke

Before adding the new rerank switch, one read-only retrieval smoke was executed
against the accepted Stage O Platform API for ERS-GOLD-0011 (Bosch exact part
number). Platform health and Resource Manager were ready.

Observed result:
- completed: yes,
- top-k: 10,
- latency: ~228 ms,
- correct ERS component document ranked #1,
- deterministic evaluator: source-identity-v1,
- Recall@1/3/5 = 1.0,
- MRR = 1.0,
- source_precision = 0.1 for top-10.

This smoke validated actual Knowledge source metadata behavior: internal
metadata.source_id is a ksrc_* identity, while source URI/repository path carries
the canonical ERS path. P2 scoring therefore does not equate internal Knowledge
IDs with golden source IDs.

## Safety / non-goals

P2 does not train or fine-tune a model. It does not download candidate models,
change the accepted logical LLM, directly access Qdrant, or alter Knowledge
canonical data. No sudo is required for the development implementation.

The new rerank=false API capability is not considered production-active until
the normal merge/deployment gate is completed. Until then, accepted Stage O
continues to behave exactly as before with reranking enabled by default.

## Next gate

After P1/P2 CI and merge, deploy the backwards-compatible runner/API change,
perform a minimal live smoke for raw versus reranked retrieval, then start P3
baseline runs. P3 must preserve split boundaries and record resource telemetry.
