# AI Platform — Stage J0/J1 Knowledge Foundation

**Data:** 2026-09-23
**Status:** IMPLEMENTATION + LIVE SMOKE PASS, bez produkcyjnego ingestion
**Branch:** `stage-j/knowledge-service-foundation`

## Cel

Rozpocząć Knowledge Service od Qdranta, zachowując możliwość późniejszej wymiany
backendu bez zmian po stronie Hermesa, Telegrama, Discorda, agentów, GUI i domen.

## Zrealizowane

- utrzymano istniejący neutralny kontrakt `KnowledgeBackend`;
- dodano stabilną warstwę `KnowledgeService` z walidacją source attribution;
- generowanie embeddingu jest odpowiedzialnością Knowledge Service, nie klienta;
- dodano prywatny `QdrantKnowledgeBackend` za kontraktem;
- publiczny/logiczny backend pozostaje `knowledge-primary`;
- Qdrant nie jest source of truth i ma być odbudowywalnym indeksem;
- zapisano ADR-001 i zaktualizowano target architecture/migration plan;
- zapisano wymagania operatora `Szukaj` i `Zapytaj AI`.
## Runtime Qdrant

Uruchomiono self-hosted Qdrant v1.19.1, przypięty digestem:
`sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10`.

Runtime:
- container: `ai-qdrant`;
- REST: `127.0.0.1:6333`;
- gRPC: `127.0.0.1:6334`;
- storage: `/srv/ai-data/qdrant/storage`;
- restart policy: `unless-stopped`;
- telemetry producenta: disabled;
- cluster/distributed mode: disabled;
- brak publicznej ekspozycji portów.

Deployment jest opisany w `deploy/stage-j/`; host nie wymaga Docker Compose,
ponieważ posiada idempotentny `qdrant_runtime.sh`.
## Walidacja

Test jednostkowy/kontraktowy potwierdza:
- translację neutralnego `KnowledgeQuery` do Qdranta;
- filtrowanie domeny/namespace/source type/metadanych;
- zachowanie URI/tytułu źródła i metadanych strony;
- brak nazwy Qdrant w wyniku logicznym klienta;
- możliwość podmiany backendu bez zmiany klienta Knowledge Service;
- możliwość podania zwykłego tekstu i wykonania embeddingu wewnątrz Knowledge Service;
- fail-closed, gdy backend zgubi source attribution.

Pełny istniejący suite `pytest` przeszedł 100% po zmianach.
Live smoke utworzył tymczasową kolekcję, zapisał fragment, wykonał semantic search
przez `KnowledgeService -> QdrantKnowledgeBackend`, potwierdził źródło i usunął kolekcję.
Po smoke `GET /collections` zwrócił pustą listę.
## Świadomie odłożone

Nie utworzono jeszcze produkcyjnej kolekcji wiedzy.
Nie zamrożono jeszcze embedding modelu, liczby wymiarów, chunkingu ani sparse modelu.
Pierwszy adapter J1 obsługuje jawnie `semantic`/`auto`; Knowledge Service może
wytworzyć embedding przez neutralny `EmbeddingProvider`, więc klient nie musi go znać.
`exact`, `keyword` i pełny `hybrid` mają być dodane jako kolejne capability,
a nie jako niejawne fallbacki.

## Następny logiczny gate

J2 powinien ustalić embedding + chunking na małym, rzeczywistym korpusie ECU/WVC,
zdefiniować kanoniczny Source/Document/Chunk model poza Qdrantem i dopiero wtedy
utworzyć produkcyjną kolekcję oraz ingestion pipeline.
