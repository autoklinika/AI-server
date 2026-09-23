# AI Platform — Stage J3 canonical ingestion / reindex / hybrid — DEV gate

**Data:** 2026-09-23
**Status:** DEV PASS / production migration pending merge
**Branch:** `stage-j3/canonical-ingestion`

## Zakres

Stage J3 materializuje trwałą warstwę wiedzy poza Qdrantem i dodaje kontrolowany
reindex oraz exact/keyword/hybrid retrieval.

Zaimplementowano:
- Alembic `0003_knowledge_canonical`;
- PostgreSQL/SQLAlchemy canonical tables;
- content-addressed immutable object store SHA-256;
- idempotent Markdown ingestion;
- versioned `chunk_profile` i `index_profile`;
- pending/failed/completed/superseded index jobs;
- BGE-M3 projector przez Gateway/Resource Manager;
- wersjonowaną kolekcję Qdranta i payload indexes;
- exact/keyword canonical backend;
- dense + lexical RRF hybrid;
- operator CLI i read-only ECU importer.
## Source safety

EcuRepairService był używany wyłącznie read-only.

- cache: `/srv/ai-data/knowledge/source-cache/EcuRepairService`;
- commit: `0ee98b94705b691d7347c8a6a5676ac63159e359`;
- origin jest weryfikowany przed ingestion;
- dirty checkout blokuje importer;
- dry-run wykrył 19 plików Markdown;
- żaden test/dev krok nie wykonał commit/push/checkout ani zapisu w source cache.

Canonical ingest kopiuje dokładne źródłowe bajty do content-addressed object store,
więc późniejsza zmiana checkoutu nie zmienia historycznej `DocumentVersion`.

## Idempotency / recovery

Testy potwierdzają:
- ten sam plik drugi raz nie tworzy nowej version/chunk set;
- zmiana SHA-256 tworzy nową version i pending job;
- starszy pending/failed job jest superseded;
- powrót do wcześniejszej treści reużywa historyczną version i requeue job;
- zmiana chunk profile nie koliduje z istniejącymi chunkami;
- completed projection nie wykonuje się drugi raz;
- failed projection zapisuje błąd i jest retryable;
- immutable object zachowuje stare bajty po zmianie source path.
## Migration evidence

Na świeżej tymczasowej SQLite wykonano:

```text
upgrade -> 0001 -> 0002 -> 0003 : PASS
downgrade 0003 -> 0002          : PASS
```

Po upgrade istnieją wszystkie pięć tabel `knowledge_*`; po kontrolowanym downgrade
zostały usunięte. Produkcyjny rollback po zapisaniu wiedzy **nie** będzie używał
downgrade, tylko pozostawi addytywne tabele przy rollbacku aplikacji.

## Live J3 smoke

PASS:

```text
canonical ingest
 -> pending job
 -> scheduled BGE-M3 through Resource Manager
 -> Qdrant projection + canonical payload/provenance
 -> text-only KnowledgeService query
 -> attributed result
```

Smoke używa tymczasowej SQLite i tymczasowej kolekcji Qdranta. Kolekcja została
usunięta po teście.
## Hybrid retrieval

J3 routing:

```text
exact / keyword -> current canonical chunks
semantic        -> dense Qdrant
hybrid / auto   -> dense + lexical -> RRF
```

Testy potwierdzają m.in. exact part number `0 281 007 439`, lexical `--end-at`
oraz przypadek, w którym dense daje poprawny chunk na #2, a lexical #1 i hybrid
promuje właściwy canonical chunk bez ujawnienia fizycznych backendów.

Pierwszy lexical scorer jest wymienialny i ma granicę skalowania; przyszły FTS/GIN
lub sparse-vector backend nie zmienia `KnowledgeQuery`.

## Stan po lokalnej walidacji

- full pytest suite: 100% PASS;
- compileall: PASS;
- `git diff --check`: PASS;
- Qdrant temporary collections: 0;
- Resource Manager active=0 / queued=0;
- GPU `recovery_required=false`;
- EcuRepairService source cache: clean.
## Production gate po merge

Po zielonym CI i merge do `main`:
1. wykonać backup PostgreSQL przed `0003`;
2. `alembic upgrade head` na produkcyjnej DB;
3. utworzyć canonical object-store directory;
4. wykonać read-only ingestion 19 Markdownów ECU;
5. ponowić ten sam ingestion i potwierdzić idempotency;
6. wykonać pending reindex do `knowledge_dense_bge_m3_1024_v1`;
7. sprawdzić exact/semantic/hybrid na realnych pytaniach ECU;
8. potwierdzić 0 failed jobs, RM idle, Qdrant ready i source cache clean.

Dopiero ten zestaw zamyka J3 jako production-complete.
