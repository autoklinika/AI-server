# Stage J4 — final Knowledge Service surface

J4 closes Stage J. It adds:
- page-aware PDF ingestion with OCR fallback;
- deterministic technical-evidence reranking;
- public Platform API `Szukaj`;
- public Platform API `Zapytaj AI` (RAG);
- source/document opening;
- immutable Stage J release and Stage I rollback gate.

## PDF ingestion

Dry-run:

```bash
PYTHONPATH=src .venv/bin/python deploy/stage-j4/ingest_ecu_pdfs.py --dry-run
```

Production import:

```bash
PYTHONPATH=src .venv/bin/python deploy/stage-j4/ingest_ecu_pdfs.py
PYTHONPATH=src .venv/bin/python deploy/stage-j3/reindex_pending.py
```

The importer is read-only against EcuRepairService and stores original PDF bytes
in the canonical content-addressed object store.
Poppler `pdftotext -layout` is primary. Pages below the configured text-quality
threshold use Tesseract OCR. OCR does not replace an existing PDF text layer; both
are preserved when OCR adds information.

Portable OCR bootstrap (no system package installation):

```bash
deploy/stage-j4/install_tesseract_portable.sh
```

Pinned runtime:
- Tesseract 5.5.0
- English + Polish trained data
- location `/srv/ai-data/tools/tesseract-portable`

## Platform API

All routes live under the existing protected Platform API boundary:

```text
POST /api/v1/knowledge/search
POST /api/v1/knowledge/ask
GET  /api/v1/knowledge/documents/{document_id}
GET  /api/v1/knowledge/documents/{document_id}/content
```

`search` performs retrieval/reranking only and does not require a generative LLM.
`ask` is RAG:
1. hybrid/semantic retrieval;
2. technical evidence rerank;
3. bounded source context;
4. scheduled structured generation;
5. claim-level citation validation;
6. response with citations and openable `document_id`.

Every generated claim must carry its own `source_refs`. Unknown citations or
invalid structured output fail closed with `rag_invalid_response`.

Physical names (`Qdrant`, `Ollama`, model file names, storage paths) are not part
of the public Knowledge response.

## Stage J release

Build/release metadata uses:
- stage `J`;
- migration `knowledge-service-v1`;
- `platform_api_contract_version=1` (additive v1 routes);
- `knowledge_service_contract_version=1`;
- rollback point `stage-i-30626dcc60f8`.

Production data preparation is now executed automatically and fail-closed by
Stage J `10_build_install`. The manual ingestion commands above remain useful for
development/recovery diagnostics, but are not a substitute for the production gate.

Production order:

```text
00_preflight
10_build_install
20_cutover
30_smoke
40_rollback
50_rollback_smoke
60_reactivate
70_reactivate_smoke
90_finalize
```
Stage J smoke validates:
- existing Platform API and observability;
- raw Knowledge search;
- RAG answer with citations;
- document metadata/content opening;
- WVC;
- Hermes;
- messaging boundary;
- media preflight;
- Stage I rollback where Knowledge endpoints are absent.

## Explicitly not Stage J

- AI Control Center GUI;
- knowledge graph / GraphRAG;
- multi-node retrieval;
- distributed index workers.

Those remain later platform stages. The stable Knowledge API is the boundary they
will consume.
