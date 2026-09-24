# ADR-007 — Stage L0: ERS Domain source of truth i granice platformowe

**Status:** ACCEPTED FOR IMPLEMENTATION
**Data:** 2026-09-24
**Zakres:** Stage L / EcuRepairService Domain Platform

## Kontekst

Dotychczasowy EcuRepairService jest repozytorium wiedzy i źródłem read-only dla Knowledge Service.
Nie jest transakcyjną domeną AI Platform i nie przechowuje kompletnego stanu rzeczywistych napraw.

Stage L ma obsłużyć cały przypadek:
`case -> metadata -> artifacts -> measurements -> evidence -> diagnosis -> repair result -> reusable knowledge`.

Istniejące granice Platform API, Resource Manager v2, provider abstraction, Knowledge Service,
PostgreSQL, canonical immutable objects i Stage K DR muszą pozostać obowiązujące.

## Decyzja 1 — source of truth

Source of truth ERS składa się z dwóch części:

1. PostgreSQL — stan domenowy, relacje, lifecycle, wersje, audyt i provenance.
2. Wspólny immutable content-addressed Object Store — oryginalne bajty plików i trwałe wersje artefaktów.

GitHub, Knowledge Service ani Qdrant nie są source of truth przypadku naprawy.

## Decyzja 2 — Object Store

Stage L nie tworzy niezależnego folderowego magazynu ERS.

Nowe artefakty używają tego samego kontraktu content-addressed co Knowledge:
`SHA-256 -> immutable bytes -> atomic put -> verify`.

W L1 fizycznie można wykorzystać istniejący canonical object pool bez przenoszenia
obecnych obiektów Knowledge. Własność logiczna zostaje podniesiona do wspólnego
`ObjectStore`; ścieżka fizyczna nie jest elementem API domenowego.

## Decyzja 3 — identyfikatory

Każdy trwały obiekt domenowy ma niezmienny UUID jako klucz techniczny.
Case dodatkowo otrzymuje czytelny, monotoniczny `case_code`, np. `CASE-000001`.

Historyczne `CASE-0001` i `CASE-0002` są zachowane jako legacy aliases.
Identyfikator nie koduje producenta, ECU, DTC ani innej zmiennej wiedzy biznesowej.

## Decyzja 4 — mutability

Oryginalne bajty, measurements, evidence, diagnostic observations, artifact versions,
diagnosis runs i publikacje są append-only/immutable.
Bieżący nagłówek case może się zmieniać, ale każda istotna zmiana generuje audit event.

## Decyzja 5 — lifecycle

Lifecycle case jest oddzielony od chwilowego work state.

Case status v1:
`draft -> open -> resolved -> closed`

Dodatkowy terminalny status: `cancelled`.

`closed -> open` jest możliwe tylko przez jawny event `reopened`.
Stany typu diagnosing, awaiting_measurement, repairing i verifying są `work_state`,
a nie nowymi statusami lifecycle.

AI nie może zamknąć, potwierdzić root cause ani opublikować case samodzielnie.

## Decyzja 6 — Knowledge publication

Knowledge jest projekcją zatwierdzonej wersji case, nie replika bieżących tabel ERS.

Publikacja:
`ERS immutable publication snapshot -> Knowledge Service ingestion -> reindex`.

Źródło Knowledge dla nowych publikacji ma typ `repair-case`.
Metadane publikacji zawierają `case_id`, `case_code`, revision, publication ID i hash.
ERS zapisuje zwrócone `document_id/version_id/index_job_id`, ale nie zapisuje nic
bezpośrednio do Qdranta ani tabel `knowledge_*`.

## Decyzja 7 — AI execution

ERS prosi Platformę o capability, np. `reasoning` lub `structured-generation`.
Nie wybiera `ollama`, `qwen` ani fizycznego modelu.

Każdy kosztowny run przechodzi przez istniejący Resource Manager/admission.
Stage L nie tworzy własnej kolejki.

Do audytu ERS może zachować execution metadata zwrócone przez Platformę,
ale te dane nie są częścią kontraktu wyboru modelu.

## Decyzja 8 — DR

Stage K pozostaje jedyną architekturą backup/DR.

PostgreSQL dump już obejmie przyszłe tabele `ers_*`, ponieważ backupuje całą bazę.
Stage L1 musi dodatkowo rozszerzyć Stage K o enumerację immutable objects
referenced przez ERS artifact versions i ich realny isolated restore.

Nie wolno zakładać, że Knowledge canonical manifest zabezpieczy obiekt tylko dlatego,
że fizycznie leży w tym samym content-addressed pool.

## Decyzja 9 — Git ERS

Repo EcuRepairService pozostaje:
- reference/source content;
- dokumentacją;
- migration seed/historycznym corpus.

Po L1 nowe aktywne przypadki nie są prowadzone przez edycję Markdown jako runtime workflow.

## Konsekwencje

Pozytywne:
- model lokalny można wymienić bez migracji ERS;
- backend retrieval można odbudować lub wymienić;
- case history jest audytowalna;
- raw artifacts mają integralność SHA-256;
- zatwierdzona wiedza może być publikowana z trwałą tożsamością źródła;
- Stage K pozostaje wspólną ścieżką DR.

Koszty:
- L1 wymaga migracji relacyjnej i ObjectStore boundary;
- publikacja do Knowledge staje się jawnym procesem;
- CASE-0002 wymaga odzyskania oryginalnych plików do pełnej kompletności;
- potrzebne są testy integralności referencji PostgreSQL -> Object Store.

## Odrzucone alternatywy

- GitHub jako case database — brak transakcyjności i runtime semantics.
- Knowledge jako case database — retrieval nie jest source of truth.
- Qdrant jako case database — indeks ma pozostać rebuildable.
- ERS komunikujący się bezpośrednio z lokalnym modelem — łamie provider abstraction.
- Osobna kolejka ERS — łamie global admission.
- Folder per case jako canonical store — duplikacja storage i słabsza integralność.
- Fine-tuning przed benchmarkiem — brak danych potwierdzających przewagę.

## Rollback

ADR nie zmienia runtime. Wycofanie L0 oznacza wyłącznie cofnięcie dokumentacji przed rozpoczęciem L1.
