# ADR-001 — Stage J: Qdrant jako wymienny backend Knowledge Service

**Status:** ACCEPTED
**Data:** 2026-09-23
**Zakres:** Stage J / Knowledge Service

## Kontekst

Platforma potrzebuje wspólnej warstwy wiedzy dla ECU, WVC i kolejnych domen.
Warstwa ma obsługiwać retrieval dla agentów oraz bezpośredni dostęp człowieka.
Backend vector/retrieval nie może stać się publicznym kontraktem platformy.

## Decyzja

Qdrant jest pierwszym backendem retrieval Stage J, ale pozostaje implementacją wymienną.
Stabilną granicą dla klientów jest `Knowledge Service` i kontrakt `KnowledgeBackend`.
Hermes, Telegram, Discord, agenci, GUI i domeny nie mogą wywoływać Qdranta bezpośrednio.
Klient przekazuje pytanie i neutralne filtry; generowanie embeddingu oraz dobór strategii
retrieval pozostają wewnątrz Knowledge Service i nie są obowiązkiem klienta.

Logiczny identyfikator backendu wystawiany wyżej to `knowledge-primary`.
Nazwy produktu, kolekcji, URL, porty i składnia filtrów pozostają wewnątrz adaptera.
## Źródło prawdy i dane

Qdrant nie jest source of truth.
Dane kanoniczne obejmują dokumenty, pliki źródłowe, wersje, checksumy, provenance,
metadane, ACL i relacje potrzebne do odtworzenia indeksu.
Muszą być utrzymywane poza Qdrantem w trwałym storage/PostgreSQL/repozytoriach.

Indeks Qdranta jest pochodną danych kanonicznych i musi być możliwy do odbudowania.
Snapshot Qdranta może przyspieszać recovery, ale nie zastępuje backupu źródeł.

## Wymienialność

Zmiana Qdrant -> inny backend nie może wymagać zmian klientów Knowledge Service.
Nowy adapter musi przejść ten sam zestaw contract tests i zachować source attribution.
Migracja backendu odbywa się przez równoległy reindex, test jakości, przełączenie
konfiguracji `knowledge-primary` i zachowanie możliwości rollbacku.
## Interfejs dla człowieka

Knowledge Service ma docelowo udostępnić co najmniej dwa tryby:

1. **Szukaj** — surowe wyniki retrieval: fragment, trafność/ranking, źródło,
   dokument i strona/pozycja, bez interpretacji LLM.
2. **Zapytaj AI** — odpowiedź RAG z jawnymi źródłami oraz możliwością otwarcia
   oryginalnego fragmentu/dokumentu użytego do odpowiedzi.

Tryb „Szukaj” nie może być zależny od dostępności modelu generatywnego.

## Routing wiedzy

Exact identifiers i dane relacyjne nie są automatycznie kierowane do vector search.
Docelowy router może łączyć SQL/exact/full-text, dense/sparse retrieval, reranking,
pliki, live tools i przyszły graph. Qdrant jest jednym backendem tego systemu.
## Zakres J0/J1

Pierwszy adapter Qdranta implementuje semantic retrieval i source attribution.
`exact`, `keyword` i pełny `hybrid` pozostają kolejnymi capability Stage J;
nie udajemy ich przez niejawne fallbacki.
Model embeddingowy, wymiary kolekcji i polityka chunkingu wymagają benchmarku
na danych ECU/WVC i nie są zamrażane przez ten ADR.

Self-hosted Qdrant jest pinowany wersją, działa wyłącznie na loopback i ma
trwały katalog danych poza kontenerem. Telemetria producenta jest wyłączona.

## Kryterium zgodności

Backend jest wymienny, jeżeli:
- klient używa wyłącznie Knowledge Service;
- publiczny payload nie wymaga nazw produktu ani jego URL;
- wszystkie wyniki zachowują źródło;
- indeks można odbudować z danych kanonicznych;
- alternatywny adapter przechodzi te same contract tests.
