# Development Hygiene Policy — porządek po testach

**Status:** obowiązująca zasada operacyjna / do formalizacji po audycie  
**Data:** 2026-09-16  
**Repozytorium:** `autoklinika/AI-server`  
**Gałąź robocza:** `docs/pre-audit-ai-platform-principles-20260916`

## Cel

Ograniczyć narastanie bałaganu w repozytorium i na Serwerze AI podczas eksperymentów, testów, wdrożeń etapowych i diagnostyki.

## Zasada nadrzędna

Każdy skrypt, plik, konfiguracja, log, dump, katalog roboczy lub inny artefakt utworzony wyłącznie na potrzeby testu ma mieć jasno określony dalszy los.

Po **pozytywnym zakończeniu testu** wszystkie tymczasowe artefakty, które nie mają dalszej wartości operacyjnej, dokumentacyjnej, diagnostycznej ani regresyjnej, muszą zostać **od razu usunięte**.

Nie odkładamy sprzątania „na później”. Cleanup jest częścią definicji zakończonego testu.

## Co podlega cleanupowi

W szczególności:

- jednorazowe skrypty testowe i naprawcze,
- tymczasowe instalery i rollbacki, jeśli po finalizacji nie są już potrzebne,
- pliki `*.tmp`, `*.bak`, `*.old`, kopie robocze i snapshoty ad hoc,
- tymczasowe konfiguracje,
- pliki wynikowe użyte tylko do ręcznej walidacji,
- pomocnicze dumpy i logi diagnostyczne,
- katalogi robocze i tymczasowe worktree,
- testowe branche, jeśli nie mają już wartości,
- testowe usługi / unit files / timery,
- tymczasowe pliki w `/tmp`, `/opt`, `/srv` i katalogach projektu,
- niepotrzebne kontenery, obrazy, wolumeny i cache utworzone wyłącznie do testu,
- nieużywane modele lub artefakty pobrane wyłącznie na potrzeby zakończonego eksperymentu.

## Co należy zachować

Artefakt zostaje, jeżeli spełnia przynajmniej jeden z warunków:

- jest częścią finalnego rozwiązania,
- jest potrzebny do powtarzalnych testów regresyjnych,
- stanowi oficjalne narzędzie diagnostyczne lub operacyjne,
- jest wymagany do rollbacku produkcyjnego,
- dokumentuje istotny przypadek lub decyzję,
- jest potrzebny do audytu lub zgodności,
- został świadomie zaklasyfikowany jako `KEEP` lub `MIGRATE`.

Jeżeli plik zostaje, powinien otrzymać poprawną nazwę, lokalizację i dokumentację. Nie pozostawiamy trwałych elementów z nazwami sugerującymi tymczasowość typu `test2`, `final_fix3`, `stage_tmp` itp.

## Minimalna procedura zamknięcia testu

Po udanym teście:

1. potwierdzić wynik testu,
2. zidentyfikować wszystkie artefakty utworzone na jego potrzeby,
3. sklasyfikować je jako `KEEP`, `PROMOTE`, `ARCHIVE` albo `DELETE`,
4. elementy `DELETE` usunąć natychmiast,
5. elementy `PROMOTE` przenieść do docelowej lokalizacji i nadać im trwałą nazwę,
6. usunąć zbędne branche / worktree / pliki runtime,
7. sprawdzić `git status` i odpowiednie katalogi runtime,
8. dopiero wtedy uznać etap za zakończony,
9. w razie istotnej zmiany przygotować krótki raport i commit dokumentacyjny.

## Zasada dla automatyzacji i agentów

Narzędzia, agenci i przyszłe workflow AI powinny traktować cleanup jako część zadania testowego. Jeżeli system tworzy artefakt tymczasowy, powinien — tam gdzie to bezpieczne — znać jego właściciela, przeznaczenie i moment usunięcia.

Preferowane są:

- jawne katalogi tymczasowe,
- automatyczny cleanup po sukcesie,
- cleanup w `finally` / teardown tam, gdzie jest to bezpieczne,
- TTL dla wybranych artefaktów tymczasowych,
- idempotentne skrypty instalacyjne i rollbackowe,
- testy, które nie pozostawiają trwałego stanu bez wyraźnej potrzeby.

## Wyjątek bezpieczeństwa

Nie wolno automatycznie usuwać artefaktów potrzebnych do analizy nieudanego testu. Przy błędzie należy zachować dane diagnostyczne do czasu zakończenia analizy.

Zasada brzmi więc:

**udany test → natychmiastowy cleanup zbędnych artefaktów**  
**nieudany test → zachować materiał diagnostyczny do czasu wyjaśnienia problemu**

## Powiązanie z audytem

Podczas `AI Server Architecture & Runtime Audit v1` należy zwrócić szczególną uwagę na pozostałości po historycznych testach i eksperymentach. Po audycie ta polityka powinna zostać włączona do docelowej dokumentacji developerskiej / operacyjnej na `main`.
