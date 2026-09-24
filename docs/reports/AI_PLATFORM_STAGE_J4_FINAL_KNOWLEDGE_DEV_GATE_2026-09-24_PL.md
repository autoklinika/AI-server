# AI Platform — Stage J4 final Knowledge Service — DEV gate

**Data:** 2026-09-24
**Status:** DEV PASS / production gate pending merge
**Branch:** `stage-j4/final-knowledge-api`

## Cel

Domknąć Stage J po produkcyjnym J3: dodać PDF/OCR, reranking, publiczne `Szukaj`,
pełny RAG `Zapytaj AI`, otwieranie źródeł oraz immutable Stage J release z rollbackiem
do Stage I.

## PDF/OCR

Pipeline został sprawdzony na wszystkich 13 PDF-ach EcuRepairService w tymczasowym
canonical store:
- 13 dokumentów / 13 wersji;
- 499 page-aware chunków;
- 8 stron wymagało OCR fallback;
- drugi pełny przebieg: 0 nowych wersji / 0 nowych chunków.

Schemat C81 05653201 miał słabą warstwę tekstową i wszystkie 6 stron skorzystało
z OCR. 36-stronicowa lista DTC 05653402 została poprawnie odczytana przez Poppler
bez OCR.
Portable Tesseract 5.5.0 (`eng+pol`) działa z
`/srv/ai-data/tools/tesseract-portable` bez instalacji pakietów systemowych.
Bootstrap z przypiętymi wersjami znajduje się w `deploy/stage-j4`.

## Retrieval / rerank

Dodano deterministyczny `technical-evidence-v1`, który po hybrid/dense retrieval
faworyzuje literalne identyfikatory, token coverage i phrase match.

Warstwa jest wymienialna i nie zmienia `KnowledgeQuery`. Test regresyjny potwierdza,
że literalny part number może awansować ponad ogólnie podobny wynik semantic.

## Publiczne API

Dodano do istniejącego Platform API:

```text
POST /api/v1/knowledge/search
POST /api/v1/knowledge/ask
GET  /api/v1/knowledge/documents/{document_id}
GET  /api/v1/knowledge/documents/{document_id}/content
```

`search` nie uruchamia LLM. API nie ujawnia fizycznych nazw backendów/modeli ani
canonical storage path.
## RAG

`ask` realizuje retrieval -> rerank -> bounded SOURCE context -> scheduled
`reasoning-main` -> structured claims -> citation validation.

Końcowy kontrakt wymaga **claim-level citations**: każdy claim ma własne
`source_refs`. Model nie może podać nieznanego ref; invalid response kończy się
fail-closed `rag_invalid_response`.

Pierwszy live RAG na 35B pokazał poprawną odpowiedź, ale używał globalnej listy
cytowań. Po tej obserwacji kontrakt został zaostrzony do claim-level grounding.
Drugi live test na realnej produkcyjnej wiedzy przeszedł: 4 claimy, każdy z własnymi
znanymi refs, `insufficient_context=false`. Najbardziej szczegółowy claim o braku
konieczności wymiany ECU/czujnika został dodatkowo zweryfikowany literalnie w
źródłowym CASE-0001 README.

## Platform boundary

Knowledge route'y dziedziczą istniejący Platform API auth/loopback policy,
request IDs i observability. Generacja RAG korzysta z istniejącego scheduler/
Resource Manager i capability `structured-generation`.
Gateway na Stage I nie miał dostępu do PostgreSQL. Stage J production gate dodaje
wyłącznie istniejące `AI_BRIDGE_DATABASE_URL` z chronionego AI Bridge env do
chronionego Gateway env bez wypisywania sekretu. Stage I ignoruje tę zmienną przy
rollbacku.

## Release / rollback

Dodano immutable release Stage J:
- migration `knowledge-service-v1`;
- observability contract 1;
- Knowledge Service contract 1;
- rollback `stage-i-30626dcc60f8`.

Gate wykonuje realny `J -> I -> J`. Kandydat/final smoke obejmuje search, RAG,
document/content, WVC, Hermes, messaging i media. Rollback smoke wymaga 404 dla
Knowledge routes przy zachowaniu Stage I observability.

## CI hardening

Wcześniejszy docs-only PR #76 ujawnił flaky queue timing test: na wolnym runnerze
request z timeout 0.1 s wygasał zanim kolejny request sprawdzał queue-full. Test
został ustabilizowany (2 s timeout, jawne oczekiwanie na queued_count), bez zmiany
semantyki schedulera.
CI workflow został rozszerzony o syntax/compile Stage J/J4 oraz osobny
`Validate Stage J release build`.

## Walidacja DEV

- targeted J4 + Platform API tests: PASS;
- real 13-PDF ingestion + idempotency: PASS;
- real Tesseract OCR fallback: PASS;
- live RAG through BGE retrieval + Resource Manager + qwen3.6:35b: PASS;
- claim-level RAG live validation: PASS;
- release/gate Python + shell syntax: PASS;
- pełny lokalny suite przed finalnym commitem: PASS;
- EcuRepairService pozostaje read-only i clean.

## Production gate po merge

1. backup DB przed PDF ingestion;
2. production ingest 13 PDF + drugi idempotency pass;
3. reindex pending PDF jobs;
4. integrity SHA wszystkich canonical objects;
5. merge/build immutable Stage J release;
6. `J -> I -> J` gate;
7. real Platform API search/RAG/source opening;
8. final documentation closure.
