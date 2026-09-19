# Development Hygiene Policy — porządek po testach

**Status:** OBOWIĄZUJĄCA GLOBALNA ZASADA WORKFLOW  
**Data formalizacji:** 2026-09-19  
**Zakres:** wszystkie obecne i przyszłe wspólne projekty

## 1. Cel

Zapewnić trwały porządek w repozytoriach i środowiskach runtime podczas eksperymentów, testów, wdrożeń etapowych i diagnostyki.

Ta polityka **nie dotyczy wyłącznie Serwera AI**. Obowiązuje we wszystkich obecnych i przyszłych projektach rozwijanych w tym workflow, m.in. AI-server, WVC, CRT, ECU Platform, EcuRepairService, PV_home oraz kolejnych projektach.

## 2. Zasada nadrzędna

Każdy skrypt, plik, konfiguracja, log, dump, katalog roboczy lub inny artefakt utworzony wyłącznie na potrzeby testu ma mieć jasno określony dalszy los.

Po **pozytywnym zakończeniu testu** wszystkie tymczasowe artefakty, które nie mają dalszej wartości operacyjnej, dokumentacyjnej, diagnostycznej ani regresyjnej, muszą zostać **od razu usunięte**.

Nie odkładamy sprzątania „na później”.

**Cleanup jest częścią Definition of Done.**

## 3. Co podlega cleanupowi

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
- tymczasowe pliki runtime,
- niepotrzebne kontenery, obrazy, wolumeny i cache utworzone wyłącznie do testu,
- nieużywane modele lub artefakty pobrane wyłącznie na potrzeby zakończonego eksperymentu.

## 4. Co należy zachować

Artefakt zostaje, jeżeli:

- jest częścią finalnego rozwiązania,
- jest potrzebny do testów regresyjnych,
- jest oficjalnym narzędziem diagnostycznym/operacyjnym,
- jest wymagany do rollbacku,
- dokumentuje istotny przypadek lub decyzję,
- jest potrzebny do audytu lub zgodności,
- został świadomie zaklasyfikowany jako `KEEP`, `PROMOTE`, `ARCHIVE` lub `MIGRATE`.

Jeżeli element zostaje na stałe, musi dostać:

- docelową nazwę,
- docelową lokalizację,
- dokumentację,
- właściciela/rolę,
- jasny powód utrzymania.

Nie pozostawiamy trwałych elementów z nazwami typu `test2`, `final_fix3`, `stage_tmp` itp.

## 5. Minimalna procedura zamknięcia testu

```text
test
 -> wynik
 -> klasyfikacja artefaktów
 -> cleanup / promote / archive
 -> kontrola runtime
 -> git status
 -> dokumentacja
 -> commit/merge
 -> DONE
```

Po udanym teście:

1. potwierdzić wynik,
2. zidentyfikować wszystkie artefakty testowe,
3. sklasyfikować je jako `KEEP`, `PROMOTE`, `ARCHIVE` albo `DELETE`,
4. `DELETE` usunąć natychmiast,
5. `PROMOTE` przenieść do docelowej lokalizacji i nadać trwałą nazwę,
6. usunąć zbędne branches/worktree/runtime files,
7. sprawdzić `git status`,
8. sprawdzić właściwe katalogi runtime,
9. przygotować dokumentację/raport, jeśli etap wprowadził istotną zmianę,
10. dopiero wtedy uznać etap za zakończony.

## 6. Nieudany test

Przy nieudanym teście nie usuwamy materiału potrzebnego do diagnozy.

```text
nieudany test
 -> zachowanie materiału diagnostycznego
 -> analiza
 -> naprawa / decyzja
 -> cleanup po zakończeniu diagnostyki
```

Materiał diagnostyczny nie staje się automatycznie trwałym archiwum.

## 7. Automatyzacja

Preferujemy:

- automatyczny teardown,
- `finally` / teardown hooks,
- jawne katalogi tymczasowe,
- TTL dla jobów i artefaktów,
- ownership metadata,
- idempotentne skrypty,
- automatyczne usuwanie worktree po testach,
- testy pozostawiające system w stanie sprzed testu, jeśli nie wykonują kontrolowanego deploymentu.

## 8. Rollbacki i backupy

Rollback/backup może pozostać po udanym wdrożeniu tylko tak długo, jak długo jest wymagany przez politykę recovery.

Po utworzeniu nowego verified recovery point stare backupy muszą zostać:

- usunięte,
- albo świadomie zarchiwizowane z opisanym okresem retencji.

Nie gromadzimy bezterminowo kolejnych `pre-stageXX`.

## 9. Wymaganie dla agentów i AI-assisted development

Każdy agent lub workflow wspierający development ma traktować cleanup jako część zadania.

W szczególności nie powinien kończyć pracy komunikatem „test przeszedł”, jeśli pozostawił zbędne:

- worktree,
- branche,
- pliki tymczasowe,
- test services,
- backupy ad hoc,
- katalogi jobów.

## 10. Definition of Done

Dla tasków wymagających testów:

**DONE = funkcja działa + testy PASS + cleanup wykonany + repo/runtime uporządkowane + istotne decyzje udokumentowane.**

To jest stała zasada workflow dla wszystkich projektów.
