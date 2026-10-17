# Stage N1 — wieloakceleratorowy admission SHARED/EXCLUSIVE (DEV)

Data: 2026-10-17. Gałąź: `feature/gpu-multipool-v1-dev-20261017`, baza `28e3ea2`.
Status: **DEV ONLY; produkcja NOT VERIFIED; brak aktywnej trasy**.

## Zakres i decyzja integracyjna

Dodano wewnętrzny komponent RM `src/ai_bridge/gateway/accelerator_admission.py`
i testy CPU `tests/test_accelerator_admission_n1.py`. Komponent wymaga jawnego
`enabled=True`, polityk urządzeń oraz zaufanego adaptera. Domyślnie jest wyłączony;
SHARED ma dodatkowo domyślnie wyłączoną politykę. Nie ma adaptera produkcyjnego,
przełącznika środowiskowego, nowej usługi ani instancji uruchamianej przez gateway.

Celowo wybrano dopuszczony wariant etapu DEV bez aktywnego route. Obecny
`PriorityScheduler` zwalnia slot po zakończeniu zadania; ten fakt nie dowodzi
bezpieczeństwa GPU. `GPUResidency.evidence_snapshot()` raportuje
`GPU_REUSE_SAFE=NOT_VERIFIED`. Włączenie N1 pod aktualne endpointy bez pełnego
kontraktu wykonania, tożsamości i cleanup byłoby niebezpieczne. Przyszła integracja
musi zastąpić admission wewnątrz tego samego RM, nie uruchamiać drugiego koordynatora.
N1 nie przechwytuje żadnego istniejącego żądania. API/HTTP, N0 i Stage O pozostają
bez zmian. Nie zmieniono konfiguracji wdrożenia, sterowników ani produkcji.

Przejrzano istniejące `scheduler.py`, `resource_leases.py`, `residency.py`,
`app.py`, rejestr N0 i testy B. Odczytano też kontrakt
`vision_residency_evidence.py` w DEV worktree `vision-rm-integration-dev-worktree`.
Wykorzystano zasadę identyfikacji inkarnacji procesu przez PID/starttime,
rozszerzoną o boot ID. Nie skopiowano założeń pojedynczego AMD GPU, odczytów
VRAM ani probe'ów sprzętu. Inne worktree nie były modyfikowane.

## Kontrakt i niezmienniki

- Jedynym katalogiem urządzeń/bindingów jest `AcceleratorRegistry` N0. N1 używa
  `candidates(provider_id, requirements)`, sprawdza węzeł dostawcy, workload class,
  backend, adapter, enabled i limit pamięci. Nie wykonuje autodetekcji.
- `accelerator_id` pozostaje stabilną nazwą konfiguracyjną fizycznej puli;
  resource ID zawiera node ID i accelerator ID. Każdy grant ma losowy lease ID,
  epokę instancji i rosnącą generację urządzenia. Release wymaga dokładnego grantu.
- Claim obejmuje jedno jawnie wskazane urządzenie. Różne urządzenia mogą mieć
  równoległe granty. Atomowe rezerwacje wielu GPU dla jednego zadania (gang
  scheduling) są odroczone; nie są symulowane sekwencją częściowych grantów.
- EXCLUSIVE jest sam. SHARED wymaga limitu N, znanej pojemności, jawnego limitu
  puli, budżetu każdego profilu, deklaracji kompatybilności par (także pary profilu
  z samym sobą) oraz referencji do raportu testów. Suma rezerwacji nie może
  przekroczyć limitu. Same deklaracje nie są dowodem walidacji sprzętowej.
- Niższa liczba priority wygrywa, remisy FIFO. Starszy oczekujący EXCLUSIVE
  powstrzymuje późniejsze SHARED także o wyższym priorytecie. Nie ma preempcji.
  Zablokowana pula nie blokuje przydziałów innych pul. Ścisła kolejność może
  zmniejszać wykorzystanie; nie ma aging ani gwarancji czasu oczekiwania.
- Jeden event loop serializuje przejścia synchroniczne. Weryfikacja async blokuje
  daną pulę. Zmiana ownership podczas weryfikacji unieważnia wynik. Adapter nie
  może wywoływać komponentu rekurencyjnie ani uruchamiać pracy w `can_start`.
- `can_start(device, claim, active)` musi zweryfikować tożsamość nowego procesu,
  wszystkich aktywnych właścicieli oraz ich izolację. Typowane pola PID/boot ID/
  birth_ticks/scope same nie są takim dowodem. Nieznane dane blokują pulę.
- Grant trafia do append-only journal i przechodzi flush/fsync przed dostarczeniem.
  Journal jest trwałym znacznikiem ownership, nigdy nie jest automatycznie usuwany.
  Błąd zapisu blokuje wszystkie pule i zachowuje przypięte granty w pamięci.
  Plik jest blokowany przez `flock`; drugi komponent z tym samym plikiem nie startuje.
- Każdy start, nawet z pustym lub uszkodzonym journal, zaczyna BLOCKED. Nie ma
  odtwarzania stanu SAFE z pliku. Adapter recovery dostaje pełny journal, jego
  hash, świeże nonce, epokę i urządzenie. Musi odrzucić niepełne/nieznane dane
  i dowieść bezpieczeństwa wszystkich poprzednich właścicieli.
- Release przekazuje adapterowi dokładny grant i pozostałych właścicieli. Wyjątek,
  cancellation, wynik inny niż dokładne `True` lub błąd persistence zachowuje
  ownership i BLOCKED. Wcześniej zablokowana pula po release wymaga oddzielnego
  recovery bez aktywnych grantów.
- Cancel/timeout kolejki usuwa tylko oczekiwanie. Cancel grantu, zgłoszony crash
  lub częściowy startup zachowuje ownership i blokuje pulę. Nie ma automatycznego
  bezpiecznego wygaśnięcia TTL. Integrator musi zgłaszać crash przez `cancel`;
  nie dodano monitora procesów. Ciche zniknięcie workera nie usuwa jego grantu.
- Żadne job completed, model unloaded, wolna VRAM, puste `/api/ps`, GPU busy=0
  ani fence counters nie są wejściem autoryzującym reuse. Nie ma resetu GPU.

API wewnętrzne: konstrukcja w event loop → `recover(accelerator_id)` przez
zaufany adapter → `submit(Claim)` → `await wait(request_id, timeout=...)` →
wykonanie poza komponentem → `await release(grant)` po weryfikacji cleanup.
`cancel`, `snapshot`, `close` służą obsłudze błędów i diagnostyce DEV. `close`
nie oznacza bezpiecznego zwolnienia GPU. Duplikaty request ID są odrzucane;
limit 4096 rekordów/128 oczekujących domyślnie ogranicza pamięć instancji.

## Testy i wyniki

W worktree uruchomiono interpreter istniejącego venv, z `PYTHONPATH=src`, aby
importować kod tego worktree. Bez rzeczywistych GPU, probe'ów `/proc`/`/sys`,
root, systemctl, driver access ani nowych zależności.

```sh
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest \
  tests/test_accelerator_admission_n1.py \
  tests/test_gateway_scheduler.py tests/test_gateway_resource_leases.py \
  tests/test_stage_n0_accelerators.py tests/test_gpu_residency.py \
  tests/test_resource_evidence_b_dev.py \
  tests/test_stage_o_reboot_recovery_minimal.py \
  tests/test_stage_o_rollback_compat.py tests/test_stage_o_default_model.py
```

Wynik końcowy: **142 passed**, w tym **58 nowych testów N1**, 84 regresyjne.
Jedno istniejące ostrzeżenie Starlette/FastAPI dotyczące httpx TestClient.
Pokrycie: SHARED2/N, EXCLUSIVE drain, priority/FIFO, dwa urządzenia, pamięć,
bindingi, opt-in, nieznana tożsamość/backend/pamięć, błędne wejścia, duplikaty,
ABA, restart/dirty/recovery, crash/partial startup, cancel kolejki i grantu,
race dostarczenia i release, concurrent submit, awarie verify i persistence.
To symulacje kontraktu, nie testy akceptacyjne sterownika ani power-loss.

## NOT VERIFIED i dokładne bramki produkcyjne

1. **Tożsamość sprzętu:** potwierdzić mapowanie fizycznego urządzenia na stabilny
   accelerator ID (w tym reboot i zmiany enumeracji); wykluczyć aliasy jednej
   karty jako dwóch pul. Obecny rejestr tego sprzętowo nie dowodzi. Jedyną obecną
   kartą jest Radeon 890M; W7900 i Intel Arc nie są zainstalowane i nie zostały
   aktywowane. N0 `local-primary` nadal ma unknown backend/memory i N1 je odrzuca.
2. **Zaufany adapter:** zaimplementować i niezależnie zweryfikować dowód
   device+boot+process incarnation+lease generation, całego drzewa procesów,
   zakazu dalszych submitów, zakończenia pracy i cleanup oraz izolacji pozostałych
   właścicieli. Fail-closed na braki i timeout. Nie implementowano takiego adaptera;
   `True` w testowym adapterze jest wyłącznie syntetycznym oraklem. Nie wystarczy
   ogólny odczyt fences, również na stabilnym sterowniku 7.0.0-39.
3. **Pamięć i kompatybilność:** dla konkretnej karty/backendu/wersji runtime
   wykonać osobno zatwierdzone testy profili i par przy N=2 i docelowym N, z
   zapasem pamięci hosta/unified memory, szczytami alokacji i awariami. Ustalić
   rzeczywiste egzekwowanie budżetów; N1 tylko księguje rezerwacje, nie ogranicza
   alokatora. Powiązać raporty z wersjami profili/adapterów.
4. **Jeden RM:** zaprojektować integrację na granicy istniejącego schedulera,
   przekazanie inkarnacji workera przed grantem, claimów i cleanup przy wszystkich
   endpointach. Zweryfikować brak bypassu, bez zmiany HTTP shapes. Nie wolno
   uruchomić legacy i N1 jako niezależnych właścicieli tych samych GPU.
5. **Persistence/recovery:** wybrać jeden chroniony plik i jego lifecycle; testy
   SIGKILL/power-loss, uszkodzeń, dysku pełnego, niekompletnego fsync i zmiany
   konfiguracji. `flock` nie chroni przed uruchomieniem koordynatora z inną ścieżką
   ani podmianą inode przez administratora. Brak journal compaction/retencji;
   journal rośnie między restartami. Zdefiniować bezpieczną rotację i audyt recovery.
6. **Eksploatacja:** dodać kontrolowany monitor crash, terminy weryfikacji,
   ograniczone audytowalne recovery i obsługę limitu request records. Dziś adapter
   może wisieć; pula pozostaje zablokowana do cancellation. Brak distributed
   admission, remote GPU, gang scheduling i automatycznej migracji workera.
7. **Akceptacja:** ponownie przejść N0/O/B i pełne testy gateway po integracji;
   przetestować rollback i domyślnie wyłączony deployment. Dopiero potem osobna
   decyzja o aktywacji konkretnej karty i profili. Nie wykonywać resetu GPU.

Następny krok: review kontraktu adaptera i mapowania fizycznej puli, następnie
implementacja adaptera w izolowanym DEV i plan akceptacji bez indukowania resetów.
Ten etap nie upoważnia do zmian `/opt/ai-platform`, `/etc`, usług produkcyjnych,
kernela lub konfiguracji hosta. Nie wykonano push ani merge. Plik wejściowy
`CODEX_TASK_GPU_MULTI_POOL.md` pozostaje poza commitem.
