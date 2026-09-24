# ADR-004 — Stage J4: PDF/OCR, RAG i publiczne Knowledge API

**Status:** ACCEPTED
**Data:** 2026-09-24
**Zakres:** Stage J / Knowledge Service / API / RAG / PDF ingestion

## Kontekst

J0-J3 dostarczyły wymienny retrieval backend, canonical persistence, dense/lexical
hybrid i produkcyjny corpus Markdown. Do zamknięcia Stage J brakowało operator-facing
API, RAG z weryfikowalnymi źródłami oraz ingestu PDF z zachowaniem stron.

## Decyzja API

Knowledge Service jest wystawiany jako addytywna część istniejącego Platform API v1:

```text
POST /api/v1/knowledge/search
POST /api/v1/knowledge/ask
GET  /api/v1/knowledge/documents/{document_id}
GET  /api/v1/knowledge/documents/{document_id}/content
```

Nie powstaje drugi publiczny port ani osobna polityka auth. Route'y dziedziczą
Platform API policy, request IDs i observability.
## `Szukaj`

`search` zwraca surowy retrieval/rerank wraz z canonical provenance. Nie uruchamia
LLM generatywnego. Awaria lub brak modelu reasoning nie może blokować przeglądania
wiedzy.

Do klienta nie przeciekają fizyczne nazwy Qdranta, Ollamy, modelu ani storage path.

## `Zapytaj AI` / RAG

Pipeline:

```text
question
 -> semantic/hybrid retrieval
 -> technical evidence rerank
 -> bounded source context
 -> scheduler / reasoning-main
 -> structured claims
 -> claim-level source validation
 -> answer + citations
```

LLM dostaje wyłącznie wybrane SOURCE blocks. Każdy wygenerowany claim musi mieć
własne `source_refs`; nie stosujemy jednej globalnej listy cytowań do całego eseju.
Unknown/duplicate/invalid refs powodują fail-closed `rag_invalid_response`.

Gdy retrieval nic nie zwróci, LLM nie jest uruchamiany, a API zwraca
`insufficient_context=true`.
## Otwieranie źródeł

Każde cytowanie może zawierać:
- `document_id`;
- `version_id`;
- `chunk_id`;
- `page` dla PDF;
- `section` dla tekstowych źródeł;
- snippet.

`GET /knowledge/documents/{id}` pokazuje canonical metadane i chunki.
`GET /knowledge/documents/{id}/content` podaje oryginalny immutable obiekt tylko
wtedy, gdy storage URI znajduje się pod skonfigurowanym canonical object-store root.
Wewnętrzna ścieżka storage nie jest zwracana jako metadata API.

## PDF/OCR

Pierwszy PDF pipeline:
- oryginalne PDF bytes -> content-addressed object store;
- `pdfinfo` + `pdftotext -layout` jako podstawowa ekstrakcja;
- quality gate per page;
- Tesseract fallback tylko na słabe/puste strony;
- jeśli istnieje słaba warstwa tekstowa i OCR wnosi więcej, obie są zachowywane;
- page-aware chunking `pdf-page-2400-v1` bez mieszania stron;
- locator zawiera `page` i `extraction_method`.
Portable OCR jest instalowany poza systemem w `/srv/ai-data/tools/tesseract-portable`;
nie wymaga modyfikacji pakietów systemowych. Bootstrap ma przypięte wersje pakietów
Tesseract/leptonica i języki `eng+pol`.

## Reranking

Stage J używa deterministycznego `technical-evidence-v1`, który faworyzuje literalne
identyfikatory, token coverage i phrase match. Jest wymienialny. Learned reranker
lub sparse model mogą zastąpić tę warstwę bez zmiany publicznego API.

## Release / rollback

Stage J jest osobnym immutable release:
- stage: `J`;
- migration: `knowledge-service-v1`;
- Knowledge Service contract: `1`;
- rollback point: `stage-i-30626dcc60f8`.

Production gate ma wykazać J -> I -> J. Na Stage I Knowledge endpointy muszą być
nieobecne, a obserwowalność i wcześniejsze funkcje pozostać aktywne.

## Poza Stage J

AI Control Center GUI, GraphRAG/knowledge graph, multi-node retrieval i distributed
index workers pozostają późniejszymi etapami. Korzystają z API zdefiniowanego tutaj.
