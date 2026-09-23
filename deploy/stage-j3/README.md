# Stage J3 — canonical persistence and idempotent reindex

## Scope

J3 makes the Stage J2 knowledge model durable:

```text
Source -> Document -> DocumentVersion -> Chunk -> IndexJob
```

PostgreSQL is the canonical persistence layer. Qdrant remains a disposable,
rebuildable projection. EcuRepairService is consumed strictly read-only.

## Schema migration

J3 adds Alembic revision `0003_knowledge_canonical` after the existing
`0002_ventilation_analysis`.

Tables:
- `knowledge_sources`
- `knowledge_documents`
- `knowledge_document_versions`
- `knowledge_chunks`
- `knowledge_index_jobs`

The migration is additive. Normal application rollback should leave these tables
in place; do **not** downgrade a production DB after canonical knowledge has been
ingested unless the data has been explicitly backed up and removal is intended.
## Read-only ECU ingestion

Inventory only:

```bash
PYTHONPATH=src .venv/bin/python deploy/stage-j3/ingest_ecu_markdown.py --dry-run
```

Ingest all current Markdown documents:

```bash
PYTHONPATH=src .venv/bin/python deploy/stage-j3/ingest_ecu_markdown.py
```

The importer:
- verifies the cache origin is `autoklinika/EcuRepairService`;
- refuses a dirty source checkout;
- records the exact source Git commit on every version;
- never writes to the EcuRepairService checkout;
- is idempotent for identical content;
- creates a new immutable version only when content SHA-256 changes;
- creates/reuses a deterministic reindex job.

A selected file can be ingested with repeated `--path relative/file.md`.
## Reindex worker

```bash
PYTHONPATH=src .venv/bin/python deploy/stage-j3/reindex_pending.py
```

The worker reads only pending/failed jobs for the configured index profile,
generates document embeddings through AI Gateway / Resource Manager, replaces the
current document projection in the versioned Qdrant collection, then marks the
job completed.

Default profile:
- model: `bge-m3`
- dimensions: 1024
- collection: `knowledge_dense_bge_m3_1024_v1`
- chunk profile: `md-heading-2400-v1`
- index profile: `dense-bge-m3-1024-cosine-v1`

A completed job is not executed again. A failed job is retryable. When a newer
document version appears, older pending/failed jobs are marked `superseded`.
## Live smoke

```bash
PYTHONPATH=src .venv/bin/python deploy/stage-j3/smoke_canonical_reindex.py
```

The smoke uses a temporary SQLite canonical store and a temporary Qdrant
collection, but the real BGE embedding path through Resource Manager. It validates:

```text
canonical ingest
 -> pending job
 -> scheduled embedding
 -> Qdrant projection
 -> text-only KnowledgeService query
 -> result with canonical provenance
```

The temporary Qdrant collection is deleted after the smoke.

## Recovery properties

If Qdrant is lost, recreate the collection and requeue/rebuild from canonical
DocumentVersion/Chunk rows. If embedding fails, the index job remains retryable.
If the same document is ingested twice without content changes, no duplicate
version or chunk set is created.

J3 does not make Qdrant source of truth and does not change client contracts.
## Retrieval in J3

J3 adds canonical exact/keyword retrieval and RRF hybrid fusion:

```text
exact / keyword -> current canonical chunks
semantic        -> Qdrant dense
hybrid / auto   -> dense + lexical -> RRF
```

Operator check:

```bash
PYTHONPATH=src .venv/bin/python deploy/stage-j3/query_knowledge.py \
  "0 281 007 439" --mode hybrid
```

The initial lexical scorer is deterministic BM25-style scoring over current
canonical chunks after domain/source/filter selection. It is intentionally
backend-neutral. A future PostgreSQL FTS/GIN or sparse-vector implementation can
replace it behind the same KnowledgeBackend contract.

## Deliberately outside this checkpoint

- PDF parsing/OCR;
- learned sparse-vector model and reranking;
- public Knowledge HTTP API / GUI;
- multi-worker distributed index claims.

The first J3 production worker is intentionally single-run/single-host. Future
parallel workers require an explicit per-job claim/locking contract before they
are enabled.
