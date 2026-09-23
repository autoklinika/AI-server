# Stage J — Knowledge Service: wymagania architektoniczne

Data: 2026-09-23
Status: DRAFT / wymaganie zatwierdzone, wybór silnika retrieval oczekuje na benchmark J0

## Cel

Knowledge Service ma być niezależną warstwą wiedzy dla domen AI Platform (w pierwszej kolejności ECU i WVC, później kolejne domeny).

## Wymaganie: dostęp człowieka do wiedzy

Warstwa wiedzy nie może być wyłącznie zapleczem dla agentów/LLM. Użytkownik musi mieć możliwość bezpośredniego przeglądania i wyszukiwania zgromadzonej wiedzy.

Interfejs użytkownika ma zapewnić co najmniej dwa tryby:

### 1. „Szukaj”

Tryb bez generowania odpowiedzi przez LLM. Ma prezentować bezpośrednie wyniki retrieval:
- oryginalny fragment dokumentu,
- wynik trafności / ranking,
- nazwę i typ źródła,
- domenę,
- numer strony lub lokalizację w źródle, jeśli dostępne,
- metadane techniczne,
- możliwość otwarcia pełnego źródła i kontekstu fragmentu.

### 2. „Zapytaj AI”

Tryb RAG:
- Knowledge Service wykonuje retrieval,
- model generuje odpowiedź na podstawie dostarczonego kontekstu,
- odpowiedź pokazuje wykorzystane źródła,
- każde źródło powinno prowadzić do oryginalnego fragmentu / strony dokumentu,
- użytkownik powinien móc porównać odpowiedź AI z materiałem źródłowym.

## Zasada architektoniczna

Hermes, Telegram, Discord, agenci i inne klienty nie powinny komunikować się bezpośrednio z konkretną bazą wektorową.

Jedynym publicznym kontraktem ma być Knowledge Service API.

Dzięki temu backend retrieval (np. Qdrant, pgvector, Weaviate lub inny) może zostać wymieniony bez przebudowy klientów AI Platform.

## Wymagania retrieval dla domen technicznych

System musi dobrze obsługiwać jednocześnie:
- wyszukiwanie semantyczne,
- dokładne oznaczenia i tokeny techniczne,
- hybrid search (dense + lexical/sparse),
- filtrowanie po metadanych i domenie,
- provenance i wskazanie konkretnego źródła,
- wersjonowanie i ponowne indeksowanie dokumentów,
- możliwość późniejszego rerankingu wyników.

## Status wyboru silnika

Qdrant jest aktualnym kandydatem preferowanym, ale NIE jest jeszcze decyzją ostateczną.

W Stage J0 należy wykonać porównanie co najmniej:
- Qdrant,
- pgvector + PostgreSQL FTS,
- Weaviate,
- OpenSearch,
- Milvus,
- Vespa.

Decyzję należy podjąć na podstawie benchmarku reprezentatywnego dla ECU/WVC, a nie wyłącznie listy funkcji producenta.

## Minimalny benchmark J0

Zestaw testowy powinien obejmować:
1. zapytania semantyczne,
2. dokładne kody/oznaczenia, np. 5508, GMS11000, MPC564MZP56, BTS141TC,
3. zapytania mieszane: naturalny język + dokładny kod,
4. filtrowanie po domenie/pojeździe/typie dokumentu,
5. pomiar Recall@K / MRR lub nDCG,
6. latency p50/p95,
7. zużycie RAM/CPU/dysku,
8. złożoność utrzymania, backupu i odtwarzania.

Dopiero wynik J0 powinien zamrozić ADR dotyczący silnika retrieval.
