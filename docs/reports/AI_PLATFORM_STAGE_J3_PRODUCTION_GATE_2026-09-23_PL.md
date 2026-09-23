# AI Platform — Stage J3 production gate

**Data:** 2026-09-23
**Status:** PRODUCTION PASS
**Main:** `28464479781519e56aa16ec82aef6e77041f7165`

## Zakres zaakceptowany

Stage J3 uruchomił produkcyjnie:
- canonical persistence w PostgreSQL;
- immutable content-addressed object store;
- read-only ingestion EcuRepairService;
- idempotentne wersjonowanie/chunking;
- retryable/supersedable index jobs;
- BGE-M3 dense projection do Qdranta;
- exact/keyword retrieval z canonical DB;
- semantic retrieval z Qdranta;
- hybrid/auto przez reciprocal-rank fusion.

Qdrant pozostaje odbudowywalną projekcją, a nie źródłem prawdy.
## Backup / schema

W chwili rozpoczęcia production acceptance baza była już na
`0003_knowledge_canonical` wskutek równoległego wykonania migracji. Nie ma więc
uczciwego pre-0003 backupu z tego gate'u.

Przed **pierwszym canonical ingestionem** wykonano backup bieżącej DB:
- `/srv/ai-data/backups/knowledge/ai_bridge_pre_j3_ingest_2026-09-23.dump`;
- size: 36,307,155 bytes;
- mode: 0600;
- SHA-256: `b3a487737b0779df17968643dfd1797786170663d290f8e2ab23a000944555db`.

Tabele `knowledge_*` były wtedy puste, Qdrant nie miał produkcyjnej kolekcji,
a canonical object store nie zawierał jeszcze produkcyjnej wiedzy.

Rollback aplikacji nie wymaga schema downgrade. Po zapisaniu canonical data
`alembic downgrade 0002_ventilation_analysis` jest operacją destrukcyjną i nie
jest zwykłą procedurą rollback release.
## Incydent pierwszego production ingestu

Pierwsza próba ingestionu po merge PR #73 ujawniła różnicę między SQLite a
PostgreSQL: przy `autoflush=False` SQLAlchemy mógł flushować nowy chunk zanim
jego nowa `DocumentVersion` była fizycznie zapisana, co aktywowało FK violation.

Skutek był fail-closed:
- transakcja PostgreSQL została w całości wycofana;
- wszystkie pięć tabel knowledge nadal miało 0 rekordów;
- Qdrant nadal miał 0 kolekcji;
- EcuRepairService pozostał clean;
- powstał jeden content-addressed immutable object przed transakcją DB; został
  bezpiecznie wykorzystany ponownie przy retry dzięki SHA-256.

Naprawa:
- jawny parent flush po insert Source, Document i DocumentVersion;
- testy SQLite uruchamiane z `PRAGMA foreign_keys=ON`;
- PR #75 CI SUCCESS;
- hotfix scalony jako `2846447`.
## Produkcyjny ingestion

Źródło ECU:
- repo: `autoklinika/EcuRepairService`;
- read-only cache: `/srv/ai-data/knowledge/source-cache/EcuRepairService`;
- source HEAD: `0ee98b94705b691d7347c8a6a5676ac63159e359`;
- working tree po całym gate: clean.

Pierwszy poprawny ingest:
- sources: 1;
- documents: 19;
- document versions: 19;
- chunks: 67;
- index jobs: 19 pending;
- immutable object files: 19.

Drugi ingest tych samych plików:
- new versions: 0;
- new chunks: 0;
- wszystkie istniejące job IDs zachowane.

Po reindexie trzeci ingest również zwrócił 0 nowych wersji/chunków i 0 pending jobs.
## Reindex / Qdrant

Produkcja używa:
- collection: `knowledge_dense_bge_m3_1024_v1`;
- model: `bge-m3`;
- dimensions: 1024;
- distance: cosine;
- chunk profile: `md-heading-2400-v1`;
- index profile: `dense-bge-m3-1024-cosine-v1`.

Reindex zakończył:
- 19/19 jobs `completed`;
- 0 `failed`;
- attempts=1 dla wszystkich pierwszych projekcji;
- Qdrant status: `green`;
- points: 67;
- payload indexes: `domain`, `namespace`, `source_type`, `source_id`,
  `document_id`, `version_id`, `chunk_profile`.

Ponowne uruchomienie workera po zakończeniu wybrało 0 jobów.
## Integrity / provenance

Wszystkie 19 `DocumentVersion.storage_uri` wskazują immutable file objects.
Dla 19/19 obiektów ponownie policzono SHA-256 i wynik był identyczny z
`knowledge_document_versions.content_sha256`.

Każdy punkt Qdranta niesie canonical provenance:
- `source_id`;
- `document_id`;
- `version_id`;
- `chunk_id`;
- `chunk_profile`;
- `content_sha256`;
- `source_revision`.

Zmiana lub utrata Qdranta nie usuwa kanonicznej wiedzy. Kolekcję można odbudować
z PostgreSQL + immutable object store.
## Real retrieval probes

Exact:
- query: `0 281 007 439`;
- wynik #1: `components/bosch/0281007439/README.md`;
- backend logiczny: `knowledge-primary`.

Semantic:
- query: `Co było rzeczywistą przyczyną SPN 107 FMI 3 w CASE-0001?`;
- case README był #1;
- jawny chunk `6. Root cause` z informacją o uszkodzonym przewodzie był w Top-3.

Hybrid:
- `0 281 007 439 SPN 107 FMI 3` -> właściwy komponent Bosch #1;
- `K82 AFDPS signal` -> workshop pinout #1;
- backend logiczny pozostał `knowledge-primary`, fusion `rrf-v1`.

To spełnia J3; dokładniejszy reranking odpowiedzi opisowych pozostaje kolejnym gate'em.
## Finalny stan operacyjny

Po acceptance:
- PostgreSQL: 1 source / 19 docs / 19 versions / 67 chunks / 19 jobs;
- jobs: 19 completed / 0 failed;
- Qdrant: green / 67 points;
- Resource Manager: active=0 / queued=0;
- GPU residency: `llm`;
- `recovery_required=false`;
- EcuRepairService: clean, HEAD bez zmian;
- AI-server: `main`, clean.

## Wniosek

**Stage J3 = PRODUCTION COMPLETE.**

Następny logiczny etap Knowledge Service:
- PDF parser/OCR i ingestion źródeł binarnych;
- learned sparse / lepszy lexical backend dla większego corpus;
- reranker;
- publiczne API/operator UI `Szukaj`;
- RAG `Zapytaj AI` z cytowaniem i otwieraniem źródła.
