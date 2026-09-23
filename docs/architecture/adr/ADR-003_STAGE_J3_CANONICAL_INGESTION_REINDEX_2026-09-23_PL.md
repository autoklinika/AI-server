# ADR-003 — Stage J3: canonical persistence, reindex i hybrid retrieval

**Status:** ACCEPTED
**Data:** 2026-09-23
**Zakres:** Stage J / Knowledge Service / ingestion / retrieval

## Kontekst

J2 wybrał pierwszy dense baseline, ale nie zapewniał jeszcze trwałego store dla
źródeł, wersji i chunków ani produkcyjnego mechanizmu reindexu. Sam Qdrant nie może
stać się źródłem prawdy.

Źródła Git/PDF mogą zmieniać ścieżki lub zawartość; samo zapamiętanie mutable
checkout path nie gwarantuje odtworzenia dokładnych bajtów wersji.

## Decyzja

Canonical persistence jest zapisywany w PostgreSQL:

```text
Source -> Document -> DocumentVersion -> Chunk -> IndexJob
```

Dokładne bajty każdej wersji dokumentu są dodatkowo zapisywane w lokalnym
content-addressed object store według SHA-256. `DocumentVersion.storage_uri`
wskazuje immutable object, nie mutable plik źródłowy.
Qdrant pozostaje wyłącznie projekcją current chunks.

## Idempotency

- identyczny `Source` / `Document` zachowuje stabilne ID;
- identyczny SHA-256 nie tworzy nowej `DocumentVersion`;
- `Chunk` identity obejmuje `version_id`, `chunk_profile`, ordinal i content hash;
- `IndexJob` identity obejmuje `version_id`, `chunk_profile`, `index_profile`;
- zakończony job nie jest wykonywany ponownie;
- failed job jest retryable;
- starszy pending/failed job może zostać `superseded` przez nową current version.

## Profile

Pierwszy produkcyjny profil:
- chunk: `md-heading-2400-v1`;
- index: `dense-bge-m3-1024-cosine-v1`;
- collection: `knowledge_dense_bge_m3_1024_v1`.

Profile są wewnętrzną konfiguracją. Publiczny klient nie podaje ich nazw.

## Retrieval

J3 wdraża:

```text
exact / keyword -> current canonical chunks
semantic        -> dense projection
hybrid / auto   -> dense + lexical -> RRF
```
Pierwszy lexical scorer jest deterministycznym BM25-style rankingiem na current
canonical chunks po filtrach domeny/source/metadata. Jest wymienny — może zostać
zastąpiony PostgreSQL FTS/GIN lub sparse vectors bez zmiany `KnowledgeQuery`.

## Source safety

Importer EcuRepairService:
- sprawdza expected GitHub origin;
- wymaga clean working tree;
- zapisuje source commit;
- tylko czyta źródłowy checkout;
- kopiuje dokładne bajty do canonical object store.

Żaden krok ingestion nie commit/push/checkout do EcuRepairService.

## Rollback

Migration `0003_knowledge_canonical` jest addytywna. Rollback aplikacji do wcześniejszej
wersji pozostawia nowe tabele, ponieważ starszy runtime ich nie używa.

Po zapisaniu produkcyjnych canonical data `alembic downgrade 0002...` jest
destrukcyjnym usunięciem wiedzy i nie jest zwykłą procedurą rollback release.

Qdrant można usunąć i odbudować bez utraty canonical data.

## Concurrency boundary

Pierwszy J3 index worker jest single-host/single-run. Nie deklarujemy bezpiecznej
wieloprocesowej konsumpcji kolejki. Multi-worker wymaga osobnego claim/locking
contract (np. row locking/skip locked) przed włączeniem.
## Poza zakresem

- PDF parser/OCR;
- learned sparse vector model;
- reranker;
- publiczny Knowledge HTTP API i GUI;
- knowledge graph.
