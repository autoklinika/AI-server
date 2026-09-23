# Stage J2 — Embedding/canonical foundation

## Baseline

- embedding: `bge-m3`
- dimensions: `1024`
- distance: cosine
- heading-aware chunk target: około `2400` znaków
- Gateway: `http://127.0.0.1:11435`
- Qdrant: `http://127.0.0.1:6333`

To jest konfiguracja indeksu, nie publiczny kontrakt. Zmiana modelu/chunkingu
wymaga reindex, ale nie zmian klienta Knowledge Service.

## E2E smoke

```bash
PYTHONPATH=src .venv/bin/python deploy/stage-j2/smoke_knowledge_e2e.py
```

Smoke wykonuje pełną ścieżkę:

```text
tekst dokumentu
  -> EmbeddingProvider przez AI Gateway / Resource Manager
  -> tymczasowy dense vector w Qdrant
  -> KnowledgeService.search(text only)
  -> query embedding wewnątrz Knowledge Service
  -> Qdrant retrieval
  -> wynik z source attribution
```

Kolekcja smoke jest zawsze usuwana w `finally`.

## Canonical model

Qdrant nie przechowuje jedynej kopii wiedzy. Backend-neutralna tożsamość to:

```text
Source -> Document -> DocumentVersion -> Chunk
```

`DocumentVersion` wiąże SHA-256 i source revision. `Chunk` ma deterministyczny
ID, SHA-256 tekstu i locator. `acl_policy_id` jest neutralną referencją do
przyszłej polityki dostępu i nie jest implementacją auth w Qdrancie.

## Następny krok

J3: trwały canonical store + ingestion z idempotentnym reindexem. Następnie
exact/full-text/sparse/hybrid retrieval i reranking.
