# Stage O — odzyskanie akceptacji po reboot (DEV, 2026-10-15)

**Wniosek: SAFE dla zmian DEV; NOT SAFE / NO-GO dla rzeczywistego apply.**
Wybrano dopuszczony wariant raportu i procedury manualnej, bez implementacji
zapisu akceptacji. Normalne bramki Stage O/E pozostają bez zmian. Ten dokument
nie jest dowodem odbioru ani zgodą na release. Nie tworzono `accepted.json`.

Zakres: worktree `stage-o-acceptance-recovery-20261015`, branch
`fix/stage-o-acceptance-recovery-20261015`, wejściowy HEAD
`a93b394582933daa5a4ca3dfd7c1a1ec4c0f9179` (początkowo czysty).
Jedyny potencjalny cel recovery to `/opt/ai-platform/releases/stage-o-5e104ea69d0b`,
source `5e104ea69d0bfa342209acdc8dc88145b34ae72e`, a nie HEAD tego worktree.
Informacje o produkcyjnym zdrowiu, checksumach, artefaktach z 6 października
oraz reboot 15 października 08:51:43 CEST pochodzą ze zgłoszenia użytkownika.
Nie odczytywano ani nie walidowano produkcyjnych state/release/runtime.

## Kontrakt i przyczyna

- `deploy/stage-o/autopilot/gate.py`: `active_rollback_baseline()` wymaga
  zgodności metadata i `accepted_stage_o()` dla aktywnego Stage O. Brak
  `accepted.json` zatrzymuje preflight przed runtime.
- `90_finalize` używa source SHA bieżącego checkoutu, historycznego baseline,
  sumy `metadata/SHA256SUMS` zapisanej w `installed.json`, obecności final smoke,
  aktualnego symlinku, schematu/tabel i `e.runtime(...)`. Uruchomienie go z nowego
  brancha nie recertyfikuje starego release.
- `deploy/stage-e/autopilot/gate.py::runtime()` porównuje klientów i dokładną
  parę `[MainPID, InvocationID]` ComfyUI z baseline. Reboot/restart unieważnia
  tę ciągłość; ponowne użycie numeru PID jej nie przywraca. Baseline nie zapisuje
  boot ID, zatem nawet równość pary nie jest samodzielnym dowodem braku reboot.
- `smoke()` zapisuje historyczny wynik po runtime, Platform/GUI/benchmark smoke,
  Hermes i media preflight. Nie jest to świeży dowód po reboot. Nie należy
  uruchamiać całego smoke jako audytu read-only: zawiera żądania POST, wyszukiwanie
  i reranking. Stage E ma także ścieżki inference i wysyłki wiadomości.
- Finalize sprawdza istnienie `final-smoke.json`, nie analizuje jego treści ani
  kompletności całej sekwencji. GUI smoke sprawdza obecność pola `backup`, nie
  sukces i świeżość backupu. `accepted_stage_o()` nie wiąże akceptacji z hashem
  wszystkich dowodów. Nie wykorzystujemy tych ograniczeń jako furtki recovery.
- `40_rollback` recovery przełącza release i steruje usługami; nie jest
  read-only recertyfikacją i pozostaje poza zakresem zadania.

Przejrzano README Stage O/E, historyczny raport Stage E recovery, walidatory
Stage O/D, testy Stage O rollback/Stage E autopilot oraz projekcję operations
(`src/ai_bridge/platform/operations.py`) i monitor Stage K. Nie ma gotowego,
pełnego kontraktu read-only recertyfikacji po reboot. Podmiana baseline, pominięcie
parametru baseline w runtime albo przepisanie jego `comfy` na aktualne dane
usuwałoby wymagany dowód, zamiast go odtwarzać.

## Najmniejsza dopuszczalna procedura dla nadzorcy — obecnie NO-GO

Poniższe punkty to warunki przyszłego audytu; nie zostały wykonane i nie są
poleceniem apply. Każdy brak, błąd odczytu lub niejednoznaczność oznacza NO-GO.

1. Zabezpieczyć oryginalne osiem artefaktów: `baseline.json`, `installed.json`,
   `20_cutover.json`, `candidate-smoke.json`, `rollback.json`,
   `rollback-smoke.json`, `reactivate.json`, `final-smoke.json`. Utrwalić ich
   hashe, pochodzenie, właścicieli i czasy w odrębnym raporcie bez sekretów.
   Zweryfikować treści, kolejność i przypisanie do właściwego candidate/rollback,
   schema i rezultatów zagnieżdżonych. Brak któregokolwiek dowodu nie może być
   zastąpiony pustym JSON, obecnością pliku ani świeżym health.
2. Potwierdzić dokładny symlink current, pełny source SHA i tożsamość katalogu
   release. Porównać RELEASE, manifest, SHA obu usług oraz kontrakty właściwe
   dla historycznego źródła, nie dla nowych funkcji HEAD. Sprawdzić sumę samego
   SHA256SUMS względem oryginalnego installed oraz sumy plików i pokrycie całego
   oczekiwanego payloadu. Istniejący checker sprawdza wymienione wpisy i obowiązkowe
   metadata, ale sam nie dowodzi kompletności listy. Walidować też rollback
   i jego historyczną akceptację. SHA256 dowodzi spójności, nie autentyczności:
   potrzebne jest niezależnie zaufane pochodzenie instalacji/artefaktów lub
   porównanie do zaufanego builda dokładnego źródła. Zgodne, wspólnie podmienione
   metadata i checksumy nie wystarczają.
3. Zarejestrować osobno nowe boot ID, PID/InvocationID i czas audytu. Nie przypisywać
   im ciągłości historycznego ComfyUI. Read-only walidacja musi obejmować current,
   rzeczywiste cwd/procesy Gateway/Bridge, effective units/drop-ins/ExecStart,
   NeedDaemonReload, konfigurację i klientów z uprawnieniami oraz Hermes/timer.
   Porównywać do zaufanej konfiguracji dla tego release. Historyczny baseline nie
   zawiera pełnego snapshotu env/unitów; brak takiego punktu odniesienia to NO-GO,
   a nie przyjęcie bieżącej konfiguracji za poprawną. Nie ujawniać env/sekretów.
4. Uzyskać świeże, oznaczone czasem wyniki wyłącznie zweryfikowanych odczytów:
   health Gateway/Bridge/Platform, status kolejek i leases, queue ComfyUI,
   schema `0005_crt_projection`, zestaw CRT, stan Hermes, operations i backup.
   Dla backupu sprawdzić źródłowe monitor/daily/weekly, sukcesy, czasy i brak
   issues, w tym restore validation. Stage K używa limitów 36 h dla backupu
   i 192 h dla weekly; stary monitor PASS nie dowodzi aktualnej świeżości.
   Brak, UNKNOWN, FAIL, przyszłe/niespójne daty lub przeterminowane dowody dają
   NO-GO. Nie uruchamiać monitora, backupu ani restore (mogą pisać/wysyłać).
5. Utrzymać dwa osobne zestawy dowodów: historyczna sekwencja wdrożenia oraz
   świeża walidacja po reboot. Sprawdzić ich niezmienność i current ponownie
   przed decyzją; zmiana symlinku, commit, konfiguracji, usług lub artefaktów
   unieważnia raport. Przyszły apply wymaga ochrony przed równoległym deploy
   i ponownej walidacji pod wspólną blokadą. Sam raport offline nie eliminuje TOCTOU.
6. Dopiero po komplecie dowodów nadzorca może osobno zatwierdzić semantykę
   jednorazowej recertyfikacji i konkretny zapis akceptacji powiązany z tymi
   dowodami. Wymaga to oddzielnie zreviewowanego apply, przypiętego do pełnego SHA,
   bez nadpisania baseline i bez udawania zwykłego finalize. Obecny patch nie
   dostarcza apply ani instrukcji ręcznego skopiowania zwykłego `accepted.json`.

Brakuje tutaj oryginalnych artefaktów do niezależnej inspekcji, dowodu autentyczności
payloadu, historycznego punktu odniesienia konfiguracji/usług, świeżego read-only
raportu runtime i backup/status oraz osobnej autoryzacji apply. Dlatego nie można
uczciwie ogłosić recertyfikacji PASS. `/system_stats`, idle queue i HEALTH=OK
nie dowodzą `E_safe`; **GPU_REUSE_SAFE nie jest stwierdzone**. Żaden punkt procedury
nie upoważnia do inference, unload, handoff ani zmian modelu/LoRA/routingu/RM A/B.

## Testy i osobna analiza negatywna

Dodano 10 przypadków w `tests/test_stage_o_acceptance_recovery.py`. Pracują na
`tmp_path`, z zastąpionymi granicami system/HTTP i bez wrapperów produkcyjnych.
Test tożsamości wykonuje rzeczywistą funkcję Stage E runtime; finalize jest
rzeczywisty, ale walidacja rollback i odczyty schematu są izolowanymi atrapami.
Testy metadata wykonują wspólny rzeczywisty walidator metadata i checksumów.
Nie są dowodem walidacji produkcji ani kompletnego nowego recovery validatora.

Osobny przegląd negatywny po napisaniu testów:

| Przypadek | Wynik / granica dowodu |
| --- | --- |
| Stary PID / nowy PID / nowa InvocationID | Trzy kombinacje są odrzucane przez realny runtime; brak accepted, baseline niezmieniony. |
| Reboot z ponownie użytym PID | Nowa InvocationID powoduje odmowę; boot ID nie jest sprawdzany przez stary kontrakt. |
| Zmieniony manifest | Realny checksum checker odrzuca zmianę, nawet komentarza. |
| Podmieniony SHA256SUMS | Finalize odrzuca niezgodność z installed. Wspólna podmiana obu wymaga niezależnego dowodu autentyczności. |
| Brak final-smoke | Finalize odrzuca przed runtime; inne brakujące artefakty muszą blokować przyszły audyt ręczny. |
| Niespójny source | Odrzucenie source baseline i niezależnie source manifestu względem RELEASE. |
| Zmieniony current / brak accepted | Finalize / preflight odmawiają. |
| Drift config/usług, błędny backup, brak świeżego runtime | Nie dodano walidatora ani testów pozorujących jego istnienie; warunki NO-GO procedury. |

Walidacja lokalna: **61 passed**, dwa ostrzeżenia deprecacji Starlette/httpx/AnyIO,
bez błędów testów. Polecenie:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/harrypotter/.cache/ai-server-agent-venv/bin/python -m pytest tests/test_stage_o_acceptance_recovery.py tests/test_stage_o_rollback_compat.py tests/test_stage_e_autopilot.py
```

Systemowy `python` nie istnieje, a `python3` nie ma pytest; wykorzystano istniejące
środowisko deweloperskie, bez instalacji zależności. Compileall Stage O/E i nowego testu: **PASS** (cache wyłącznie w `/tmp`).
`git diff --check`: **PASS**; nowe, nieśledzone pliki sprawdzono również
przez `git diff --no-index --check` względem `/dev/null`.

Nie wykonywano sudo, deploy, restartów, inference, push/merge/reset/clean ani
modyfikacji produkcyjnych plików. Nadzorca: przejrzeć DEV diff, pozyskać brakujące
dowody w osobno zatwierdzonym audycie, utrzymać NO-GO do ich oceny. Wszystkie
późniejsze działania root/apply/release wymagają odrębnej decyzji użytkownika.

## Dopisek DEV — walidator wstępny CHECK, 2026-10-15

**NO-GO dla recertyfikacji/apply; gotowy wyłącznie walidator wstępny offline.**
Na wejściowym HEAD `18c235bdffc6bd3c40e3a86862432677715f8840` sprawdzono
kod obu skryptów audytowych z `/tmp` (bez uruchamiania) i kontrakt producenta
artefaktów z Git source `5e104ea69d0bfa342209acdc8dc88145b34ae72e`.
Zgłoszone 33/33, 885 plików obu usług i świeże health/Stage K pozostają danymi
od użytkownika, nie nową niezależną walidacją produkcji. Historyczny baseline
nie obejmuje pełnych env, efektywnych unitów/drop-inów, konfiguracji A/B,
preload script ani pełnej tożsamości modeli/adapterów. Potrzebny jest niezależny,
zatwierdzony **przed reboot** snapshot tych danych z wiarygodnym pochodzeniem
(np. chronione archiwum konfiguracji/backup z udokumentowanym zatwierdzeniem,
czasem i powiązaniem z release). Bieżąca kopia, własny digest ani dodatkowe
pole `PASS` tego nie zastępują. Nie potwierdzono dostępności takiego źródła.

Dodano jeden skrypt `deploy/stage-o/recover_acceptance_once.py`. Domyślnie
wyłącznie drukuje JSON `CHECK / NO_GO`, kończy się kodem 2 i nie czyta produkcji.
Nie ma implementacji ani opcji `--apply`; także deklaracje approval/lock nie
uruchomią zapisu. Bezpośrednie uruchomienie używa shebang `python3 -I -B -S`;
przy wskazywaniu interpretera należy zachować te flagi, ponieważ startup Pythona
może pisać bytecode **przed** wykonaniem kodu skryptu. Brak importów gate,
subprocess, HTTP, locków, instalacji i ścieżki zapisu accepted/attestation.

Opcjonalne `--expected-source <pełny pinned SHA> --evidence-dir <katalog kopii>`
sprawdza dokładnie osiem nazw, ścisły schemat zapisany przez historyczny gate,
powiązania identities, kolejność/czasy smoke, zagnieżdżone wyniki CC/benchmark,
liczniki i historyczny format klientów. Odrzuca duplikaty kluczy, NaN, symlinki
również w rodzicach, hardlinki, FIFO, nadmiarowe pliki i pliki ponad 1 MiB;
odczyt stosuje O_NOATIME bez fallbacku i ponownie sprawdza metadane.
Naprawia słabość audytu `/tmp`: candidate/final nie mogą używać
`ROLLBACK_NOT_REQUIRED`, a samo zagnieżdżone `status=PASS` nie wystarcza.
Wynik strukturalny to najwyżej `CONSISTENT_UNAUTHENTICATED`, **nigdy odbiór**.

Granice są celowe: skrypt nie uwierzytelnia oryginałów/owner/mode/immutability,
rollback accepted, manifestu/checksum coverage/Git payload, klientów bieżących,
current, konfiguracji, runtime, NAS ani Stage K. Każdy pozostaje jawną blokadą
`NOT_VERIFIED`/`UNAUTHENTICATED`, nawet dla poprawnej strukturalnie kopii.
Testy podmiany manifestu/checksumy, konfiguracji, klientów i nowego PID dowodzą
odmowy **autoryzacji**, nie implementacji detekcji wszystkich driftów.
Powtórny stat to diagnostyka zmian, nie pełna ochrona przed TOCTOU; bez
transakcji nie istnieje ścieżka publikowania akceptacji. W przyszłości konieczne
są wspólna blokada Stage O, ponowna pełna walidacja, ochrona mutable inputs,
nowy boot ID i osobna datowana immutable recovery-attestation z digestem,
write-once atomic/fsync oraz accepted dopiero na końcu. Historyczny finalize
nie przeszedł; health/hash nie dowodzą E_safe. A, B, modele i LoRA zamrożone.

Walidacja CPU/offline: **155 passed, 2 ostrzeżenia deprecacji**, polecenie:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/harrypotter/.cache/ai-server-agent-venv/bin/python -m pytest -o addopts='' -q -p no:cacheprovider tests/test_stage_o_recovery_check.py tests/test_stage_o_acceptance_recovery.py tests/test_stage_o_rollback_compat.py tests/test_stage_o_default_model.py tests/test_stage_e_autopilot.py
```

Nowe testy używają wyłącznie tmp_path/in-memory; argument `--apply` jest testowany
wyłącznie jako odrzucona, nieistniejąca opcja izolowanej kopii skryptu. Sprawdzono
brak nowych plików/bytecode oraz brak zmian metadanych/atime kopii przy CHECK.
Pierwszy przebieg wykrył startup bytecode; poprawiono shebang i zweryfikowano
oba wspierane sposoby uruchamiania. AST i compile w pamięci: PASS;
`git diff --check` oraz analogiczna kontrola nowych plików: PASS.
Dotychczasowy test recovery i standardowe gate Stage O/E pozostawiono bez zmian.
Prywatny przegląd DEV: brak dowodu pozwalającego na GO, brak operacji produkcyjnych,
sudo/root, GPU, commit/push/merge. Następny krok: review diffu i ustalenie, czy
istnieje niezależne historyczne archiwum konfiguracji; jeśli nie, potrzebna jest
osobno zaprojektowana i zatwierdzona manualna recertyfikacja, nie odtworzenie
pozornej ciągłości historycznej.

## Uzupełnienie nadzorcy — porównanie NAS Stage K, 15.10.2026

Po zakończeniu prac Codexa wykonano dodatkowy niezależny audyt READ-ONLY
historycznych archiwów `PlatformConfig` w GlobalNAS. Zweryfikowano manifest
`COMPLETE`, hash SHA-256 archiwum oraz kompletność i hash każdego z 17 elementów
dla czterech zestawów dziennych: `20261006T003014Z`,
`20261007T003014Z`, `20261010T003013Z`, `20261014T003015Z`.
Wszystkie cztery: 17/17 plików zgodnych z manifestem, zero błędów.
Zestaw 14.10 sprzed reboot: 17/17 hashy identycznych z plikami obecnymi
w systemie; między zestawami 6, 7, 10 i 14.10: zero różnic w tych plikach.

To istotny niezależny punkt odniesienia dla jednostek systemd i drop-inów
Gateway, Bridge, ComfyUI, Ollama, analizy i Hermes, ale nie dla pełnej
historycznej konfiguracji: backup PlatformConfig nie zawiera sekretnych plików
`.env`, nie dowodzi zawartości działających procesów, nie jest podpisaną
atestacją konfiguracji, nie odtwarza historycznego PID/InvocationID i nie
dowodzi `E_safe`. Bez dalszej weryfikacji pochodzenia oraz wyraźnego
zatwierdzenia odmiennego kontraktu akceptacji `RECOVERY_APPLY=NO_GO`.
Nie wykonano `sudo`, restore, zmiany unitów ani stanu produkcji.
