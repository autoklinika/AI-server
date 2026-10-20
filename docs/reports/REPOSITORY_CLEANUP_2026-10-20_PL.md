# Porządkowanie repozytorium i GitHub — 20.10.2026

## Wykonane

- PR [#175](https://github.com/autoklinika/AI-server/pull/175) scalony do main po zielonym platform-ci dla dokładnego heada 13de9bf. Merge commit: a522e2631f0e9001f93b68f9ec4c44b242236e4f.
- 12 historycznych draftów (#160–#163, #165, #167–#173) zamkniętych bez merge, z oznaczeniem ARCHIVE. Gałęzie, commity i audyty zachowane. Nie oznacza to zamknięcia ustaleń bezpieczeństwa ani dopuszczenia N1.
- [#174](https://github.com/autoklinika/AI-server/pull/174) oznaczony REFERENCE; nadal draft. Nie wolno scalać całej gałęzi ze względu na odziedziczony stos DEV N1–N5.
- Lokalny main zaktualizowany do a522e26. Czysty worktree i lokalna gałąź zakończonego Stage K usunięte po potwierdzeniu, że commit jest w main. Zdalna gałąź Stage K pozostała: zwykły git push usuwający sprawdzony ref nie miał uwierzytelnienia. Nie usuwano żadnej gałęzi z niescaloną pracą.
- Przygotowano oddzielną gałąź cleanup/production-sync-20261020 bez zmiany usług produkcyjnych. README i [mapa repozytorium](../REPOSITORY_STATUS_2026-10-20_PL.md) wskazują aktualne odbiory.

## Czysta gałąź produkcyjna

Bazą jest aktualny main po #175. Import zmienia dziesięć plików runtime: sześć dotychczasowych oraz cztery nowe moduły. Wszystkie 239 plików źródłowych i benchmarków odpowiadają bajtowo manifestowi przyjętego overlay vision-radio-5d9d267489609ccb. Nie przeniesiono N1–N5, SHARED/Multi-GPU, managed-worker DEV ani n2-dev-blocked.

Dołączono źródła stałego wykonawcy RADIO, autostart/gotowość ComfyUI/Gateway/Hermes, narzędzia operacyjne i historyczne pakiety instalacyjne, testy CPU oraz raporty odbioru GPU i po restarcie. Jednorazowe skrypty zachowano jako ARCHIVE z opisem ich ograniczeń; nie są ponownie uruchamiane. W [gotowym opisie PR](../handoffs/PRODUCTION_SYNC_PR_2026-10-20.md) znajduje się docelowy zakres przeglądu.

## Walidacja przed publikacją

Testowany snapshot odpowiadał 959 plikom przygotowanego commita 76b4726; każdy plik sprawdzono SHA256 przed testem. Potem dodano wyłącznie ten raport, log testu i opis PR. Regresja runtime nie wymagała ponowienia dla dodatków dokumentacyjnych.

- Pełne testy: **1463 PASS, 9 SKIP, 0 FAIL**, 11 ostrzeżeń deprecacyjnych, 16,52 s. Nie deklarujemy wykonania pominiętych testów. [Pełny log](REPOSITORY_CLEANUP_CPU_TESTS_2026-10-20.log).
- Kompilacja Python src/tools/integrations/deploy: PASS.
- Składnia wszystkich skryptów shell w deploy: PASS.
- Control Center JavaScript: node --check PASS.
- Budowanie wydań D, E, F, G, H, I, J, L, M, O: **10/10 PASS**. Buildy korzystały z izolowanego snapshotu git i prawidłowych identyfikatorów stage-<litera>-<12 hex>. Pierwsza próba E miała błędny identyfikator w komendzie testowej i została odrzucona przed budową; poprawiona procedura przeszła wszystkie etapy bez zmiany kodu projektu.
- git diff --check i sprawdzenie odnośników nowych dokumentów: PASS.
- Ograniczona kontrola sygnatur kluczy prywatnych, tokenów GitHub i Telegram w nowych/zmienionych plikach: brak dopasowań. Nie jest to gwarancja pełnej klasyfikacji danych; raporty zawierają wewnętrzne ścieżki i szczegóły hosta.

Pomocniczy snapshot, dziesięć katalogów buildów i ich środowiska wirtualne zostały usunięte po zachowaniu logów i manifestu. Gotowa gałąź lokalna oraz gałąź z czterema nieopublikowanymi commitami pozostają, ponieważ zawierają pracę oczekującą publikacji.

## Oczekujące i przyczyna

Repozytorium autoklinika/AI-server ma widoczność **public**. Automatyczna kontrola dwukrotnie odrzuciła publikację nowych commitów i wewnętrznych raportów, uznając dotychczasowe ogólne polecenie za niewystarczającą zgodę na ten konkretny payload i destination. Nie próbowano obejść odmowy przez API.

Do zgody pozostaje publikacja czystej gałęzi cleanup/production-sync-20261020 do publicznego https://github.com/autoklinika/AI-server, utworzenie PR do main i merge dopiero po zielonym platform-ci na aktualnym headzie oraz aktualności gałęzi. PR #174 można zamknąć jako zastąpiony dopiero po przyjęciu czystego PR; jego historyczną gałąź należy zachować.
