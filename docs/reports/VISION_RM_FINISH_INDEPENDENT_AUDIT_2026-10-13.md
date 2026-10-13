# Niezależny audyt finish / cross-UID — DEV, 2026-10-13

**NO-GO.** Źródła gałęzi `feature/vision-rm-system-security-20261013`, baza
`41c81d6`; zmiany niecommitowane, do przeglądu nadzorującego. Bez wdrożenia,
restartu, E2E, inferencji, zmian GPU lub produkcji. Nie zmieniono manifestów
hash, poświadczeń, jednostek systemd ani istniejącego observera. Nie powstał
nowy RM/scheduler. Vision pozostaje oddzielone od WVC/automotive/ECU.

## Dowody i granice wnioskowania

Dowody runtime 21:17 pochodzą od operatora i z dwóch wcześniejszych raportów,
nie z ponownego odczytu usług w tej sesji: worker CPU UID 994 PASS, kontroler
UID 993, brak sekretu kontrolera w workerze, marker DEV absent, runner FAIL.
Nie przechwycono odpowiedzi finish. Różnica repo/staging wyklucza przypisanie
wszystkich obecnych warunków kodu do historycznej próby.

Potwierdzone statycznie oraz mockami: `scope_members_or_terminal` używa UID
procesu kontrolera; dla pustego/znikłego scope UID 994 przy UID 993 zwraca
unknown. Nie zmieniono tego na pozytywny dowód. `not-found` pozostaje odmową.
Parser dodatkowo odrzuca duplikaty pól, śmieci i nieoczekiwane klucze.

## Dokładna ścieżka błędu

`runner.run → finally → request(finish) → ControlBroker.request`:

1. Zły peer UID/PID, niezgodny hash/argv/cgroup runnera, zła sesja, brak sesji
   po restarcie brokera albo inne birth ticks: `denied`, bez wywołania RM.
2. Jeśli broker zna use, DELETE use. HTTP 401/403, 404/409/500, błąd transportu,
   brak poświadczenia/nieprawidłowy plik, błędny JSON albo `released:false`
   mogą zakończyć ścieżkę przed pozytywnym cleanupem. Dawny serwer IPC sprowadzał
   wiele z tych przypadków do `gateway_error`; runner do jednego RuntimeError.
3. `end_external_use` może zwrócić false przed `leave_vision` (nieznane ID),
   albo true dla już zakończonego use. Sama odpowiedź nie dowodzi nowej próby
   sprawdzenia scope. Przy właściwym żywym use `leave_vision` sprawdza PID,
   scope, idle, VRAM i FD; sukces usuwa marker i ustawia llm.
4. Dopiero potem DELETE lease. Jego wyjątek/odpowiedź false pozostawia
   **marker absent pomimo nieudanego finish**. Możliwa utrata odpowiedzi po
   skutecznym DELETE; możliwe wcześniejsze `release_when_idle`, które powoduje
   usunięcie lease podczas end_external_use, a następne DELETE zwraca false.
   To hipotezy przebiegu 21:17, nie ustalona przyczyna.
5. `finally` dotychczas zastępował pierwotny wyjątek; timeout `systemctl stop`
   mógł też pominąć finish. Sam napis o blocked lease nie dowodzi ani markera,
   ani istnienia lease. Zatrzymanie systemd-run nie dowodzi końca potomków.

Brak markera jest zgodny z udanym use cleanup i późniejszym błędem lease,
lecz nie wyklucza innych błędów, restartu/utraty stanu czy różnic stagingu.
Nie ma podstaw do wskazania jedynej przyczyny incydentu.

## Znaleziska według istotności

- **Wysoka, potwierdzona w kodzie:** po utracie/błędnej odpowiedzi begin use
  może istnieć w RM, ale broker nie zapisuje use_id. `release()` zwraca true
  również dla odroczonego zwolnienia z aktywnym use. Dawny broker mógł zgłosić
  released i zapomnieć sesję bez cleanupu. RM nadal przypina use — nie dowiedziono
  faktycznego przedwczesnego otwarcia GPU. Poprawka DEV ustawia
  `admission_uncertain` **przed** POST; nieznany wynik blokuje finish i ponowne
  begin, wymaga recovery. Bez automatycznego retry nieidempotentnego POST.
- **Wysoka, blokada dowodu:** brak cross-UID terminal attestation i brak
  ciągłego powiązania instancji jednostki. PID+birth eliminuje reuse tylko
  dla obserwowanego procesu; nie obejmuje potomków. Ten sam tekst nazwy scope
  nie gwarantuje tej samej instancji systemd. Nie naprawiono przez zgadywanie UID.
- **Wysoka, ryzyko wymagające walidacji:** brak dowodu containment potomków
  przed admission. User manager działa pod tym samym UID co model; model może
  potencjalnie używać jego bus/uruchamiać inne jednostki. Pusty cgroup.procs
  obejmuje tylko dany cgroup, nie podgrupy ani procesy przeniesione poza niego.
  `setsid` nie opuszcza cgroup, ale nie wyczerpuje modelu ucieczki. Runnerowe
  sandbox flags nie są same w sobie dowodem sandboxu procesu uruchomionego
  przez innego managera. Nie przeprowadzono exploita. Snapshot FD/VRAM nie
  wyklucza uśpionego potomka, który otworzy GPU po zwolnieniu.
- **Średnia, potwierdzona:** utrata etapu błędu i maskowanie wyjątku pierwotnego.
  Poprawione w DEV. `finally` zachowuje obiekt pierwotnego wyjątku, dodaje stałą
  notatkę; CLI kończy exit 1 bez surowego tracebacka. Diagnostyka ma wyłącznie
  stałe stage/reason i opcjonalny liczbowy HTTP status. Nie zawiera URL, ścieżek
  prywatnych, session/use/lease ID, bearer, scope token ani treści HTTP/wyjątku.
  Przed wejściem do bloku pracy CLI podaje jedynie ogólne `vision_runner_failed`.

`use_cleanup` i `lease_release` są osobnymi etapami. Denial peer/sesji celowo
pozostaje jednym `denied`, bez ujawniania stanu sesji nieuprawnionemu klientowi.
Nieznany format odpowiedzi jest błędem; liczba 1 nie zastępuje boolean true.
Timeout stop nie pomija próby finish; wyłącznie niezależny RM ocenia możliwość
release. Niezerowy stop jest konserwatywnie błędem runnera, nawet gdy później
RM potwierdzi cleanup. Błąd nie zawsze oznacza istniejący marker.

## Propozycja terminal attestation — NIE IMPLEMENTACJA / NIE WDROŻENIE

Nie dodano pozornego pozytywnego prototypu opartego na przekazywanych booleanach.
Bez zaufanego kolektora i dowodu containment taki prototyp testowałby jedynie
własne założenia. Poniższy wąski protokół dotyczy **istniejącego** observera;
rozszerzenie jego roli i uprawnień wymaga decyzji architektonicznej użytkownika.

| Mechanizm | Wartość | Niewystarczające elementy / warunki |
|---|---|---|
| Późne systemctl show | Negatywna kontrola loaded/active | GC/not-found nie dowodzi końca; nazwa może zostać użyta ponownie |
| PID + birth + UID + cgroup | Powiązanie admission z żywym workerem | Nie obejmuje potomków, boot/restart i kolejnych instancji scope; rozważyć pidfd |
| D-Bus Subscribe + śledzenie job/unit | Historia konkretnej instancji i przejść | JobRemoved(done) oznacza koniec job, nie automatycznie terminalny workload; start job też kończy się done |
| RefUnit + obserwacja właściwości | Może zatrzymać GC podczas audytu | Wymaga sprawdzenia dostępności/uprawnień w lokalnej wersji; zmienia lifetime jednostki, więc nie jest czysto pasywnym odczytem |
| Ograniczona atestacja root observer | Może połączyć kernel, manager i istniejące FD/VRAM | Nie rozwiązuje containment samym odczytem; ProtectHome=yes ukrywa /run/user |

Dokumentacja upstream rozróżnia UnitRemoved (wyładowanie) i JobRemoved (wynik
job), opisuje subskrypcje oraz RefUnit. Nie potwierdza to dostępności całego
API na tym hoście: [systemd D-Bus](https://raw.githubusercontent.com/systemd/systemd/main/man/org.freedesktop.systemd1.xml).
ProtectHome=yes ukrywa /run/user; samo bycie root nie usuwa tego ograniczenia
namespace: [systemd.exec](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.exec.xml).
Nie proponuję ogólnego wyłączenia ProtectHome. Ewentualny selektywny dostęp
lub inny kanał systemd wymaga osobnego projektu i testu w docelowym sandboxie.

### Konkretny kontrakt do review

- AF_UNIX, SO_PEERCRED: operacje terminalne tylko UID 993; UID 994 i pozostałe
  UID denied przed jakimkolwiek odczytem. Root server musi być uwierzytelniony
  również przez klienta. Żadnych zdalnych token actions, dowolnych URL/ścieżek,
  komend, nazw użytkownika ani flag systemctl.
- `register_scope_v1`: dokładnie version/op/pid/birth/scope_suffix; suffix
  12 małych cyfr hex, UID 994 i prefix wyprowadzane z konfiguracji root.
  Limit 512 B, ścisłe typy (bool nie jest int), odrzucanie extra/duplicate keys.
  Limit jednej rejestracji zgodny z jednym Vision use w istniejącym RM.
- Rejestracja przed wydaniem capability: observer sam weryfikuje żywy PID,
  birth przed i po odczycie, UID, dokładny kernel cgroup i jego tożsamość,
  instancję managera (boot, proces/birth/uwierzytelniony bus owner), InvocationID
  jednostki jeśli lokalne API zapewnia wiarygodną semantykę scope. Brak któregoś
  powiązania => odmowa. Subskrypcja musi działać przed pierwszym snapshotem,
  ze sprawdzeniem wyścigu na końcu rejestracji. Worker nie dostarcza evidence.
- Odpowiedź: opaque watch handle, epoch observera; handle wyłącznie w UID 993,
  nie do logów. `query_terminal_v1` przyjmuje wyłącznie handle+epoch; odpowiada
  pending/unknown/terminal i stały reason, bez ścieżek i PID innych użytkowników.
- Pozytywne terminal wymaga historii **tej samej instancji** od żywego admission
  do loaded/inactive/dead, powiązanego zakończenia workera, opróżnienia całego
  subtree oraz dowodu, że potomkowie nie mogli z niego wyjść. Obserwacja samego
  UnitRemoved/not-found/empty nigdy nie tworzy dowodu. Historia terminalna może
  przetrwać GC tylko w tej samej nieprzerwanej sesji observera i do krótkiego TTL.
- Disconnect, przepełnienie kolejki, restart observera/managera, zmiana ownera,
  epoch, nieznana kolejność zdarzeń, timeout, PID reuse, brak lub duplikat pól:
  unknown, rejestracja bezpowrotnie nieważna; recovery, nie rekonstrukcja z pustki.
- Containment wymaga root-enforced polityki wykluczającej bus-assisted launch,
  migrację/ponowne uruchomienie i nested descendants. Jeżeli odczytowy observer
  nie potrafi tego wykazać, **nie może wydać pozytywnej atestacji**. Alternatywą
  do decyzji jest root-managed granica wykonania w istniejącym RM (zmiana
  architektury), nie dodatkowy scheduler. Nie zostało to zaimplementowane.
- Dowód terminalny jest konieczny, ale nie wystarczający: istniejące idle,
  VRAM, GPU FD, marker i kontrola lease pozostają. Admission wymaga dowodu
  żywego procesu i containment; cleanup wymaga dowodu zakończenia wszystkich
  uprawnionych procesów. Te bramki nie są symetryczne.

## Testy i dokładne komendy

Wyłącznie Python stdlib i mocki dla nowych testów; żadnego połączenia z GPU,
realnym brokerem ani HTTP. Testy używają sztucznych wartości sekretów.

```
python3 -m unittest discover -s tests -p 'test_vision_rm_cleanup_diagnostics_dev.py' -v
python3 -m unittest discover -s tests -p 'test_vision_rm_crossuid_terminal_evidence_dev.py' -v
python3 -m unittest discover -s tests -p 'test_vision_observer_disconnect_dev.py' -v
python3 -m unittest discover -s tests -p 'test_vision_rm_executor_protected_file_dev.py' -v
```

Oczekiwane/zweryfikowane końcowo: odpowiednio 10, 9, 3 i 5 PASS (27 razem).
Zakres: HTTP statusy i redakcja, use/lease failure, unknown admission, peer UID,
PID reuse, zła sesja/scope, odmowa arbitralnych operacji, oryginalny wyjątek,
stop timeout, IPC, not-found/GC, duplikaty/śmieci, żyjący potomek w scope,
observer timeout/reset/EOF/wrong UID, złe birth w odpowiedzi, niedozwolony
remote URL przed odczytem credential/wywołaniem sieci.

Pierwszy import testu brokera przez pakiet zakończył się ModuleNotFoundError
(pydantic). Test ładuje teraz wyłącznie odpowiednie moduły stdlib; nie stubuje
logiki brokera. Systemowy Python 3.14 nie ma runtime dependencies aplikacji.
Sprawdzony istniejący CPU venv również nie ma pytest/httpx/pydantic_settings.
Nie instalowano pakietów; pełna macierz pytest/auth HTTP nie została wykonana.

Dodatkowe próby (nie są PASS):

```
python3 -m unittest discover -s tests -p 'test_verify_crossuid_dev_stage.py' -v
python3 -m unittest discover -s deploy/vision-rm-security -p 'test_verify_crossuid_dev_stage.py' -v
```

Pierwsza: 0 testów (zły katalog). Druga: 7 testów, 3 PASS, 3 FAIL, 1 ERROR.
Starszy zestaw sięga read-only do prawdziwego stagingu i systemctl show;
środowisko zgłasza STAGE_NOT_ROOT_OWNED oraz STAGE_SYSTEMD_UNAVAILABLE.
Nie zmieniano verifiera ani atestacji, nie uruchamiano/zatrzymywano usług.
Nie interpretować tego jako pomiaru produkcyjnego stanu z hosta operatora.

Mock reset/EOF dowodzi odmowy klienta przy utracie snapshotu; **nie dowodzi**
inwalidacji terminal history po restarcie, bo mechanizm nie istnieje.
Test żyjącego potomka obejmuje obecnego członka scope, **nie** rzeczywistą
ucieczkę poza cgroup. Pozostają wymagane testy uprzywilejowane tej granicy.

## Warunki odblokowania i następny krok operatora

1. Review tego diffu, szczególnie unknown begin i rozróżnienia release deferred.
2. Decyzja o containment i wąskiej atestacji istniejącego observera; implementacja
   i niezależny review bez osłabienia hash manifests, credential boundary i GPU gates.
3. Testy uprzywilejowane izolowanego DEV: reuse PID/unit, GC przed/po terminal,
   nested/escaped descendants, bus spoof/manager restart, observer restart,
   lost/reordered events, deadline, runner SIGKILL, HTTP denied i lost replies.
4. Dopiero po zaliczeniu powyższego: osobno autoryzowane staging + CPU-only E2E,
   zapisać bezpieczne stage/reason, oba release, brak markera, brak lease,
   stan DEV i niezależne potwierdzenie niezmienionej produkcji.
5. GPU/ROCm i cutover pozostają osobnymi bramkami właściciela projektu.

**Teraz nie ma rekomendowanej komendy start/retry/operator --apply.** Nie
uruchamiać wcześniejszych refresh/accept skryptów na podstawie samych testów
mock. Dalszą komendę administracyjną należy przygotować dopiero dla zatwierdzonego
rozwiązania i aktualnych, niezależnie sprawdzonych hashy stagingu.

## Nadzór i niezależna regresja po pracy Codexa

Kontroler projektu wykonał na rzeczywistym hoście (poza sandboxem Codexa) niezależnie wszystkie poniższe testy bez uruchamiania usług:

```bash
python3 -m unittest deploy/vision-rm-security/test_verify_crossuid_dev_stage.py -v
python3 -m unittest discover -s tests -p test_vision_rm_cleanup_diagnostics_dev.py -v
python3 -m unittest discover -s tests -p test_vision_rm_crossuid_terminal_evidence_dev.py -v
python3 -m unittest discover -s tests -p test_vision_observer_disconnect_dev.py -v
python3 -m unittest discover -s tests -p test_vision_rm_executor_protected_file_dev.py -v
git diff --check
```

**Wynik niezależny: 7 + 10 + 9 + 3 + 5 = 34/34 PASS, diff check PASS.**
Historyczne błędy testów stagingu u Codexa wynikały z dostępu do izolowanego systemd i plików root-owned. Na hoście kontrolera wykryto ponadto, że testy stanu jednostek były zależne od zgodności SHA runnera już zainstalowanego z niezatwierdzonymi poprawkami DEV. Zmieniono **wyłącznie testy**, aby odseparować kontrolę `UnitFileState` od świadomej rozbieżności w kodzie staged; nie zmodyfikowano weryfikatora produkcyjnego ani jakichkolwiek plików root-owned.

`DEV_STAGING_VERIFICATION=PASS` **nie jest** obecnie kryterium zaliczonym dla nowych źródeł — binarne stagingi są celowo przestarzałe wobec diffu i runner systemd pozostaje `failed`. Rzeczywistego CPU-only E2E nie ponawiano. **Security gate: NO-GO**.

Nadzór statyczny potwierdził, że zmiany source-only dotyczą Vision RM (broker, runner, parser dowodu, testy i dokumentacja). Nie wprowadzono drugiego Resource Managera, zmian modelu Qwen3.8, adapterów LoRA, restartów produkcji ani rozszerzenia uprawnień root observera.
