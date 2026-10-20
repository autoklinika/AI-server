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

## Publikacja zatwierdzona przez użytkownika

Po wcześniejszym wstrzymaniu publikacji użytkownik jednoznacznie zatwierdził cały zakres 80 plików, publiczne repozytorium `autoklinika/AI-server`, utworzenie PR i scalenie po zielonym CI. Utworzono [PR #176](https://github.com/autoklinika/AI-server/pull/176). Pierwszy opublikowany commit `a42f27359bb58d028e5a6850b5cbe17db8161552` ma identyczne drzewo jak zatwierdzony lokalny HEAD: `9a37ebfcf1a95c0cce2de0974b0689a774594fdf`. Następna zmiana uzupełnia tylko te dwa dokumenty o stan publikacji.

Bieżący wynik CI i stan scalenia są dostępne w PR #176. Merge wymaga zielonego `platform-ci` na aktualnym headzie; następnie #174 zostaje zamknięty jako zastąpiony, z zachowaniem historycznej gałęzi. Produkcja nie jest zmieniana przez tę operację. Lokalne oryginalne commity zachowano w gałęzi archiwalnej, ponieważ publikacja przez GitHub utworzyła równoważny commit o innym SHA.
