# AI Platform — Stage O: jednorazowa recertyfikacja, protokół decyzji

Data audytu: 2026-10-15 (CEST). Status: **CODE_READY_IN_DEV/PROD_BLOCKED; AKCEPTACJA NIEZAPISANA.**
Dotyczy wyłącznie istniejącego release `stage-o-5e104ea69d0b` i pełnego SHA
`5e104ea69d0bfa342209acdc8dc88145b34ae72e`, nie poprawki A, Vision ani handoff GPU.

## Fakty zweryfikowane

1. Operator wykonał przygotowany, sprawdzony SHA-256, read-only audyt ośmiu root-owned dowodów transakcji Stage O:
   **33/33 PASS**. Historyczne `candidate-smoke`, `rollback-smoke`, `final-smoke`,
   ich kolejność, targety, poprzedni zaakceptowany rollback, baseline i zainstalowane checksumy
   były spójne. Historycznego `accepted.json` brak.
2. Niezależne read-only porównanie serwera: aktualny symlink/release oraz wszystkie
   wymienione checksumy PASS; 885 tracked plików źródłowych obu usług na release
   identycznych z dokładnym źródłowym commitem; brak aktywnych jobów/leasów i markeru recovery;
   Gateway, Bridge, Ollama P511, ComfyUI, timer analizy i Control Center zgłaszają zdrowie.
   Użyto odczytów API, bez inference/handoff/reset/restart.
3. Stage K monitor/daily/weekly PASS, weekly restore PASS, NAS `//globalnas.local/AI_Platform`
   widoczny jako CIFS. Kopie PlatformConfig z `20261006T003014Z`, `20261007T003014Z`,
   `20261010T003013Z`, `20261014T003015Z`: integralne manifesty i archiwa,
   **17/17 plików** każda, zero różnic pomiędzy kopiami. Bieżące 17 plików
   ma identyczny SHA-256 do kopii sprzed reboot z 14 października.
4. Szyfrowane zestawy PlatformSecrets z `20260924T164644Z` i `20260925T075350Z`
   to kompletne manifesty: SHA-256 pakietów `.age` i manifestów PASS.
   Oba zawierają ścieżki `/etc/ai-bridge/ai-bridge.env` i `/etc/ai-gateway/ai-gateway.env`.
   Obecne pliki mają zapisane rozmiary i tryby dostępu; czasy modyfikacji wcześniejsze niż backup.
   **Nie odszyfrowywano** pakietów, nie odczytywano ani nie publikowano treści sekretów.
5. System uruchomił się ponownie 15.10 o 08:51:43 CEST. ComfyUI ma nowy PID i
   `InvocationID`; wymagana przez dawne `90_finalize` ciągłość tożsamości
   nie może być po reboot potwierdzona. `90_finalize` nie zakończył się PASS.

## Dokładnie pozostałe ryzyko

- Nie udowodniono **bajtowej zgodności historycznych .env** sprzed 6 października
  z aktualnymi bajtami. Manifesty szyfrowanych backupów zawierają ścieżki, tryby i rozmiary,
  a nie per-plikowy hash jawnej treści. Timestamps/mode/size nie są równoważne SHA-256.
- Snapshot PlatformConfig obejmuje 17 wymienionych unitów/systemd, ale nie jest
  kryptograficznie podpisanym pomiarem wszystkich efektywnych runtime env.
- Późniejszy uruchomiony model i adapter zostały potwierdzone API/digestami,
  lecz brak osobnego dowodu, że wszystkie historyczne parametry procesu są identyczne.
- Sam `HEALTH=ok` lub pusty `/api/ps` **nie dowodzi `E_safe`**. Dowód `E_safe`
  nie jest warunkiem *samej* diagnostycznej recertyfikacji Stage O, gdy handoff
  pozostaje wyłączony; nie wolno zatem ogłaszać `GPU_REUSE_SAFE=VERIFIED`.
- Istniejący `accepted_stage_o()` akceptuje konwencjonalne `accepted.json` i nie
  rozróżnia historycznego finalize od odzyskania akceptacji. Nie wolno zapisywać
  tego pliku bez jawnego rozszerzenia semantyki procedury jednorazowej.

## Decyzje wymagane przed jakimkolwiek zapisem

**DECISION-1 (właściciel):** Czy przyjąć wąski wyjątek od wymogu historycznej
bajtowej zgodności dwóch `.env`, przy udokumentowanych dowodach: dwa poprawne
szyfrowane backupy z września, mtime/mode/size, bieżące poprawne endpointy
i niezmienione 17 unitów? To świadoma decyzja ryzyka operacyjnego; nie należy
interpretować jej jako dowodu identyczności. Alternatywnie, zweryfikować
plaintext hash historycznych `.env` *lokalnie* z legalnie dostępnym kluczem age,
bez ujawniania treści i bez zapisów sekretów na dysk.

**DECISION-2 (osobna zgoda właściciela po decyzji 1):** Przyjąć jednorazowy
kontrakt `RECOVERED_POST_REBOOT` dla dokładnie tego release, z osobnym dowodem
recertyfikacji i bez twierdzenia, że `90_finalize` przeszedł po reboot.
Przyszła minimalna implementacja zapisu, jeśli upoważniona, musi:
(a) walidować wszystko na nowo pod jedną blokadą transakcyjną Stage O,
(b) chronić przed drift/race, (c) nie nadpisywać historycznych 8 plików,
(d) atomowo utrwalić osobne `recovery-attestation.json` (pełne SHA,
boot ID, datowane wyniki weryfikacji, odwołanie do wyjątku/akceptacji)
i dopiero potem kompatybilny `accepted.json` z jawnie odróżnioną genezą;
(e) wykonać read-only smoke Gateway/Bridge/Comfy/UI/Stage K, bez GPU handoff.
Przed produkcyjnym zapisem wykonać review narzędzia i testy negatywne w DEV.

## Werdykt

- **HISTORICAL_EVIDENCE=PASS** (33/33 odczyty root z wyniku operatora).
- **CURRENT_OPERATION=PASS** w przeprowadzonych odczytach.
- **PRE_REBOOT_UNITS=PASS** w zakresie 17 kopii Stage K.
- **SECRETS_ARCHIVE_INTEGRITY=PASS**, **HISTORICAL_ENV_BYTE_IDENTITY=NOT_VERIFIED**.
- **E_SAFE=NOT_VERIFIED**; GPU handoff nadal wyłączony.
- **ONE_TIME_RECERTIFICATION_WRITE=NO_GO** do decyzji właściciela i testów implementacji.
- **PRODUCTION_DEPLOY_B=NOT_RUN**; `main` zawiera B, aktywny release nadal stary.
- **RM_A=DEV_ONLY**.

Protokół jest raportem, nie skryptem apply ani formalnie wykonaną akceptacją.

## Wcześniejsza aktualizacja DEV — preflight (stan przed implementacją writer)

Właściciel **zatwierdził DECISION-1**, identyfikator zapisu w projekcie:
`STAGE-O-2026-10-15-DECISION-1`. Wyjątek obejmuje wyłącznie brak historycznej
bajtowej zgodności `/etc/ai-bridge/ai-bridge.env` i
`/etc/ai-gateway/ai-gateway.env`. Nie jest dowodem identyczności zawartości,
autoryzacją zapisu, wdrożenia, merge ani osłabienia standardowego gate.
DECISION-2 pozostaje osobną decyzją operatora.

Dodano `deploy/stage-o/recover_acceptance_preflight.py`: wykonywalny, wyłącznie
odczytowy etap planu preflight, zawsze `NO_GO` (exit 2), bez implementacji apply.
Po osobnym dostarczeniu i review kodu operator może uruchomić **wyłącznie check**:

```sh
python3 -I -B -S deploy/stage-o/recover_acceptance_preflight.py --check --expected-source 5e104ea69d0bfa342209acdc8dc88145b34ae72e
```

Polecenie nie zostało wykonane na produkcji. Wymaga istniejącej blokady
`/var/lib/ai-platform/stage-o/executor.lock`; nie tworzy jej ani katalogów.
Weryfikuje root-owned komponenty ścieżek, dokładny target `current`, osiem
oryginałów (0600, katalog 0700), strukturę zagnieżdżoną, historyczne czasy,
kolejność i hashe pod tą samą blokadą co standardowy gate. Obce pliki,
`accepted.json`, częściowe `recovery-attestation.json`, symlinki i zauważone
zmiany podczas odczytu powodują odrzucenie. Hash odczytanego oryginału nie
jest niezależnym dowodem historycznej niezmienności. Stary PID pozostaje
wartością historyczną, nie dowodem ciągłości po reboot.

**Status: BLOCKED dla recovery acceptance.** Zaimplementowano ograniczony
preflight, nie pełną recertyfikację. Raport programu wymienia niewykonane
aktywne weryfikacje: niezależne źródło Git/archiwum i rollback accepted,
pełny payload/metadata, klienci i efektywna konfiguracja/runtime, brak zmian
i handoff, queue/leases/idle, świeży Stage K/restore/NAS oraz integralność
manifestów szyfrowanych backupów i metadane dokładnie dwóch `.env`.
Nie przyjmuje flag PASS ani deklaracji użytkownika jako substytutu tych dowodów.
Należy również pozyskać uwierzytelniony zapis operatora wiążący wyjątek z tym
identyfikatorem decyzji. Nie odszyfrowywać sekretów.

Blokada Stage O nie zamraża konfiguracji ani pozostałych procesów; ponowne
stat nie rozwiązuje wszystkich wyścigów. Dlatego nie dodano zapisu, tokenu ani
procedury wznowienia częściowego apply. Testy race/partial dotyczą odrzucenia
odczytu, nie atomowości nieistniejącego apply. Testy nie dowodzą wykrywania
starego Stage K ani zmienionych archiwów/runtime — te obszary pozostają
jawnie nieweryfikowane. Zalecenie: **STOP przed apply**, uzupełnić niezależne
weryfikatory i kontrakt utrwalenia przed kolejnym go/no-go.

Standardowe `90_finalize` i `accepted_stage_o()` pozostają niezmienione.
Przed ewentualnym dodaniem writer należy uzależnić odczyt accepted z
`recovery_provenance` od zgodnej, niezmiennej attestation i odrzucać brak lub
rozbieżność; samo dodanie flagi nie zapewnia tej ochrony. `E_safe=NOT_VERIFIED`,
GPU handoff poza zakresem; produkcja nie została recertyfikowana.


## Implementacja DEV 2026-10-15 — CODE_READY_IN_DEV/PROD_BLOCKED

Zaimplementowano `deploy/stage-o/recover_acceptance_apply.py`. Ta aktualizacja
zastępuje wcześniejsze stwierdzenia o braku writer i niezmienionym odczycie
recovery przez gate. DECISION-1 jest zatwierdzona; osobnej zgody apply nadal brak.
Nie wykonano produkcyjnego apply, wdrożenia accepted, commit/push ani merge.

Rdzeń Python przyjmuje katalog STATE i wstrzyknięty verifier będący zaufanym
kodem. Jest testowany wyłącznie w `tmp_path`; nie jest produkcyjnym adapterem.
Odczytuje osiem oryginałów bez zapisu, odrzuca duplikaty kluczy JSON, symlinki,
nieprawidłowy owner/mode, stan częściowy i niespójności. Używa istniejącego
`executor.lock` z katalogu nadrzędnego, tego samego mechanizmu flock co gate
(blokada wyłączna, nie LOCK_SH). Ponownie sprawdza pliki, inode katalogu i blokady
oraz wywołuje runtime recheck przed zapisem i pomiędzy zapisami.

Attestation zapisuje source SHA, czas, boot ID, fazę `RECOVERED_POST_REBOOT`,
hashe ośmiu oryginałów i 17 plików config, health oraz osobny identyfikator zgody.
Wyjątek env ma status `approved_exception` i `byte_identity=NOT_PROVEN`;
zawiera tylko nazwy env, bez treści ani hashy sekretów. Osobny callback
`authorize` jest wymagany dodatkowo do identyfikatora; CLI nie przyjmuje JSON
PASS ani tokenu umożliwiającego zapis. Historyczne `90_finalize` ma jawnie
`NOT_PASSED`, nie PASS.

Oba pliki powstają przez O_EXCL/O_NOFOLLOW w trybie 0600, z fsync pliku i katalogu
po każdym zapisie. To **dwa uporządkowane trwałe zapisy**, nie atomowa transakcja
obejmująca dwa pliki: accepted jest znacznikiem zakończenia. Nie ma nadpisywania,
usuwania ani automatycznego wznowienia. Błąd, także fsync, pozostawia stan do
ręcznego przeglądu; nie wolno interpretować wyjątku jako dowodu braku zapisu.
Gate ma minimalną dodatkową ścieżkę recovered: weryfikuje bezpieczny odczyt,
hash attestation, związanie tożsamości i hashe oryginałów. Obecność attestation
również wymusza tę ścieżkę, więc usunięcie samych pól provenance nie wystarcza.
Znaczenie historycznego accepted i standardowego finalize pozostaje bez zmian.

**Bramki produkcyjne pozostają niekompletne.** CLI default `--check` wyłącznie
raportuje blokady bez odczytu produkcji; `--apply` zawsze zwraca exit 2 bez zapisu.
Brak aktywnego, zaufanego adaptera źródła Git i obu payloadów, metadanych release,
rollback accepted, klientów względem baseline, efektywnego runtime/model/LoRA,
read-only health/queue/leases, Stage K monitor/daily/weekly/restore i źródeł NAS,
manifestów backupów/env oraz uwierzytelnionej osobnej zgody apply.
Testy sprawdzają kontrakt wyników wstrzykniętego verifier, **nie potwierdzają
rzeczywistej walidacji tych źródeł na produkcji**. flock nie zamraża innych
procesów; potrzebne są jeszcze rzeczywiste bariery mutacji i aktywne rechecks.
Nie wolno podłączyć operatorowego JSON jako verifier ani traktować callbacków
fixture jako uwierzytelnienia. Przed przyszłym apply wymagane code review/CI,
uzupełnienie powyższych bramek i osobna zgoda użytkownika. Status nie jest REVIEW_READY.

Hermetyczne testy obejmują sukces, trwałość/kolejność fsync, odmowę retry,
stan attestation-only, błędy fsync, istniejący accepted, symlinki, ownership/mode,
source SHA, brak smoke, manifest, model, health, Stage K, stary NAS, brak zgody,
lock contention, TOCTOU plików/blokady/katalogu/runtime, duplicate JSON,
provenance i integrację gate. Regresje standardowego finalize nadal odrzucają
zmieniony PID/InvocationID po reboot; recovery zapisuje nowy boot ID bez
przepisywania historycznej tożsamości. E_safe pozostaje NOT_VERIFIED.

Walidacja DEV: `git diff --check` PASS; AST trzech zmienionych/dodanych plików
Python PASS. Wymagane uruchomienie
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/harrypotter/.cache/ai-server-agent-venv/bin/python -m pytest tests/test_stage_o*.py tests/test_stage_e*.py`
zakończyło się **212 passed**, dwa ostrzeżenia deprecation zależności.

## Końcowy hardening DEV — aktywna obserwacja częściowa, PROD_BLOCKED

Ta sekcja aktualizuje powyższy stan implementacji. Nie przeprowadzono w tej
sesji żadnego odczytu ani zapisu produkcyjnego; nie wykonano recertyfikacji.
Dodano `deploy/stage-o/recover_acceptance_observe.py --observe`, osobny program
bez ścieżki apply. Nie jest podłączony jako autorytet do writer. Zawsze zwraca
exit 2 i `PROD_BLOCKED`, także przy zgodnych obserwacjach. Uruchomienie
produkcyjne pozostaje przyszłym działaniem operatora po przeglądzie.

Pokryte kodem aktywne odczyty: osiem oryginałów i ich zagnieżdżona struktura,
czasy i kolejność pod istniejącym executor.lock; dokładny target current;
SHA-256/mode/uid/gid pięciu klientów względem baseline; bajty preload unit;
Gateway/Bridge health i Control Center readiness; Comfy queue oraz Gateway
active/queued/jobs leases równe zero. Odczyty systemd obejmują Gateway,
Bridge, Comfy i timer analizy: ActiveState, InvocationID, NeedDaemonReload,
MainPID usług oraz skonfigurowane i rzeczywiste cwd Gateway/Bridge. Dwa pomiary
porównują boot ID, target current, tożsamości procesów, klientów, preload unit
oraz nazwę/digest pojedynczego rezydentnego modelu p511. Stary PID Comfy jest
wyłącznie historią. Nie sprawdza się jego równości z nowym procesem.

Kontrakty odczytów odpowiadają istniejącym helperom Stage E runtime/idle/
comfy_idle i Stage O Control Center. Celowo nie importuje się gate zawierającego
operacje mutujące. Stałe endpointy loopback nie używają proxy ani przekierowań;
brak zgodnego bind Bridge na loopback kończy się NO_GO, bez odczytu env.
Limit CLI wynosi 30 s łącznie (SIGALRM), HTTP i systemctl po 2 s; odpowiedzi
JSON mają limit 1 MiB i odrzucają duplikaty/NaN. Nie drukuje się payloadów,
stderr ani zawartości plików. Importy wyłączają bytecode; uruchomienie wymaga
`python -I -B -S`. Zgodność dwóch pomiarów nie stanowi dowodu braku zmian
pomiędzy nimi ani blokady ingress.

**Niepokryte aktywną walidacją:** pełne RELEASE/manifest/SHA256SUMS i kompletność
payloadu, porównanie obu źródeł z zaufanym Git, rollback metadata/accepted;
uwierzytelniony digest modelu, LoRA i preload script; oddzielny routing WVC;
Hermes user service; 17 efektywnych unitów/drop-ins względem zaufanej kopii;
świeże Stage K monitor/daily/weekly i nested restore; mount NAS i marker;
manifesty i archiwa PlatformSecrets/PlatformConfig oraz przypięte metadane
rozmiaru/trybu/mtime dwóch env. Obserwowany digest modelu nie dowodzi jego
zgodności z historycznym zaufanym digestem. Każdy z tych braków pozostaje
jawną blokadą, niezależnie od wyników częściowego check. Nie dodano pozornych
testów tych brakujących weryfikatorów. `E_safe` nadal NOT_VERIFIED.

### Kontrakt przyszłej blokady mutacji

Executor.lock obejmuje tylko transakcje Stage O. Root-owned JSON z PASS,
plik lease albo dwa zgodne pomiary nie egzekwują wyłączności. Produkcyjny apply
pozostaje bezwarunkowo wyłączony, dopóki niezależny review nie potwierdzi
następującego mechanizmu przygotowanego przez uprawnionego operatora:

1. Przed obserwacją operator ustanawia i sprawdza rzeczywistą blokadę nowych
   żądań wszystkich ingress (także bezpośrednich lokalnych API), Hermes,
   timera i zewnętrznych narzędzi administracyjnych. Samo zero jobs nie wystarcza.
   Każdy potencjalny mutator musi respektować wyłączność albo mieć odebrane
   możliwości mutacji na czas okna; brak kompletnego pokrycia oznacza NO_GO.
2. Wyłączna dzierżawa musi być utrzymywana przez cały czas, z mechanizmem
   uniemożliwiającym zwolnienie, przejęcie lub wygaśnięcie podczas zapisu.
   Zaufany dowód operatora wiąże source SHA, boot, nonce, właściciela/proces
   i jego generację, zakres ingress/urządzeń i osobną zgodę apply. Root ownership
   jest konieczne, ale nie zastępuje weryfikacji mechanizmu egzekwowania.
3. Po ustanowieniu bariery: executor.lock, pełne walidacje i recheck dowodu
   dzierżawy, bieżącego symlinka (także inode), generacji procesów/boot/urządzeń,
   rezydencji, config i ingress przed pierwszym zapisem, między zapisami oraz
   po obu fsync. Ta sesja nie ustanawia dzierżawy, nie zatrzymuje usług i nie
   dostarcza fikcyjnego adaptera autoryzującego ją.
4. Dzierżawa pozostaje utrzymana aż do niezależnej kontroli końcowego stanu.
   Utrata bariery lub błąd końcowy wymaga ręcznego review bez retry, usuwania
   ani automatycznego zwalniania zabezpieczeń. Dopiero osobna autoryzacja
   operatora może otworzyć normalny ruch.

To wymagania dla przyszłego apply, nie gotowy mechanizm ochrony. Bez skutecznej
bariery żaden recheck nie usuwa wyścigu tuż po ostatnim sprawdzeniu.

Rdzeń DEV sprawdza teraz attestation przed accepted i oba pliki po zapisie;
wywołuje również końcowy runtime recheck pod lock. Accepted zawiera jawne
`acceptance_kind=RECOVERY_RECERTIFICATION` i `historical_finalize=NOT_PASSED`.
Gate recovery wymaga tych pól i dokładnego zakresu wyjątku env; stare accepted
bez recovery nadal korzystają z dotychczasowego kontraktu. Błąd po trwałym
accepted **może pozostawić plik akceptacji**: wyjątek nie oznacza rollback.
Nie wolno wystawić tego rdzenia produkcyjnie bez bariery. Attestation-only,
zmiana attestation między zapisami i ponowna próba są odrzucane.

Testy offline obejmują nowe kontrakty health, błędny klient/preload/model,
puste lub obce residency, unit drift, cwd/current, boot i zmianę generacji,
non-idle, niedozwolony typ licznika, brak pola i odmowę odczytu. Transport
fixture sprawdza redirect/status, duplikaty, NaN, limit rozmiaru, symlink,
owner/mode i timeout całkowity; nie dotyka prawdziwych endpointów/systemd.
Dodatkowe testy writer obejmują błąd tworzenia pliku 1/2, zmianę attestation
między zapisami oraz błąd końcowego recheck po trwałym accepted. Testy callbacków
writer nie dowodzą istnienia produkcyjnej dzierżawy.

Plan: niezależny supervisor review zmian DEV; uzupełnienie brakujących
aktywnych bramek i egzekwowanej wyłączności; ponowne testy i przegląd; dopiero
potem osobna zgoda użytkownika na konkretny apply. Obecny wynik: częściowy
postęp implementacji, **PROD_BLOCKED**, bez merge/deploy/accepted.

Walidacja końcowa DEV: wskazane przez użytkownika polecenie pytest Stage O/E
zakończyło się **252 passed, 2 warnings** (deprecation zależności).
`git diff --check` PASS; AST i compile w pamięci czterech plików Python PASS,
bez zapisu bytecode. Nie wykonano commit/push ani produkcyjnych poleceń.

## Niezależny odbiór nadzorcy — obserwator DEV, 15.10.2026

Codex dodał `deploy/stage-o/recover_acceptance_observe.py` z rzeczywistymi
punktowymi odczytami health, kolejek, klientów, procesów, boot ID, unitów
systemd, preload i rezydencji modelu. Dwa odczyty są porównywane, ale
**nie stanowią aktywnej bariery przed nowym żądaniem**. Interfejs CLI
jest wyłącznie odczytowy, zawsze zwraca `PROD_BLOCKED`; produkcyjny writer
nie został połączony z obserwatorem.

Niezależny przegląd wykrył i poprawił przypięcie Bridge/Control Center:
usługi słuchają na `192.168.1.55:8080`, nie na `127.0.0.1:8080`
(na tym drugim adresie test GET /health nie uzyskał odpowiedzi).
Obserwator ma teraz jawnie przypięte adresy docelowe dla tego hosta;
zmiana adresacji wymaga nowego audytu. Dodano hermetyczne testy właściwych
hostów, portów i ścieżek; nigdy nie wykonują żądań do produkcji.

Niezależne powtórzenie regresji Stage O/E po tej poprawce:
**256 PASS, 0 FAIL, 2 ostrzeżenia deprecacji**; AST PASS,
`git diff --check` PASS.

**NO-GO dla rzeczywistego apply nadal obowiązuje:** nie wdrożono pełnych
aktywnych kontroli source/rollback, Stage K, konfiguracji modelu/adaptera
ani nie ma egzekwowanej izolacji ingress oraz mutacji spoza `executor.lock`.
Zatwierdzony wyjątek `.env` nie obejmuje tych braków. Do czasu osobnej
autoryzacji nie zapisuje się `recovery-attestation.json` ani `accepted.json`
na produkcji; nie wykonuje się merge ani cutover.
