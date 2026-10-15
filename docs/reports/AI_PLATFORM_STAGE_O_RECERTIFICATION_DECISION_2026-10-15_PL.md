# AI Platform — Stage O: jednorazowa recertyfikacja, protokół decyzji

Data audytu: 2026-10-15 (CEST). Status: **AUDYT ODCZYTOWY ZAKOŃCZONY; AKCEPTACJA NIEZAPISANA.**
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

## Aktualizacja DEV — osobna autoryzacja wyjątku, bez zgody na apply

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
