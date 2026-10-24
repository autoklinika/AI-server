# AI Platform — odbiór DEV Hermes /foto → Qwen → RM → ComfyUI → FLUX2 Klein

**Data:** 24.10.2026. **Host:** harrypotter-AI-Series. **Zakres:** audyt rzeczywistego hosta, naprawa CI, regresja CPU, przygotowanie izolowanego GPU DEV.

**PRODUCTION_UNCHANGED=YES. GPU_REUSE_SAFE=NOT_VERIFIED. N1/SHARED=NOT_ADMITTED. FULLCHAIN_REAL_GPU=NOT_TESTED. PRODUCTION_CUTOVER=NOT_AUTHORIZED.**

## A. CI — PASS

- PR #178: https://github.com/autoklinika/AI-server/pull/178 (Draft).
- Run #802 / 40070437512: test systemd odwoływał się do niedostępnego w GitHub Actions /opt/comfyui/venv/bin/python.
- Commit 9102e8a3dc1fb71a05f9702e4cce03eda4a8adef: test sprawdza oryginalną jednostkę po zastąpieniu **tylko** ExecStart executable w tymczasowej kopii na CI; na realnym hoście weryfikuje również niezmodyfikowaną jednostkę i binarium.
- Host: portable systemd-analyze verify PASS, oryginalne systemd-analyze verify PASS, git diff --check PASS.
- Host: 16/16 lokalnych testów Hermes /foto i systemd PASS; pełny pytest exit code 0.
- Run #803 / 40072100934: completed, conclusion success; cały pytest i wszystkie buildy release Stage D/E/F/G/H/I/J/L/M/O PASS.
- **Gate A PASS dla commit 9102e8a; po kolejnych commitach wymagana ponowna weryfikacja CI.**

## B. Audyt read-only hosta — PASS jako audyt, NIE jako odbiór produkcji

- Kernel 7.0.0-39-generic, Ubuntu 26.04.1, MemTotal 32 732 884 992 B (30,49 GiB), MemAvailable około 27 696 721 920 B podczas późniejszego preflight. Swap 8 GiB, niewykorzystany.
- Radeon 890M PCI 0000:c6:00.0 /dev/kfd /dev/dri/renderD128. RTX 5060 Ti wykryty; nvidia-smi P8 2 MiB użytej VRAM podczas odczytu.
- ai-gateway, comfyui, ollama active. Oryginalne comfyui.service nadal Restart=always i autostart, Gateway wymaga ComfyUI.
- Gateway /health OK; RM IDLE, active=0, queued=0, recovery_required=false; Ollama /api/ps pusta; ComfyUI: loaded=0, running=0, pending=0, cleanup_pending=false.
- Produkcyjne ComfyUI nadal utrzymuje deskryptory /dev/kfd i /dev/dri/renderD128 pomimo RM IDLE.
- /dev/kfd i renderD128 mają 0660 root:render; /dev/nvidia0, nvidiactl, nvidia-uvm mają 0666 root:root. Konta harrypotter i ollama należą do render.
- Nie wykryto aktywnych markerów w dwóch sprawdzonych lokalizacjach DEV. Poprzednie dowody awarii zostały zarchiwizowane.
- Nowy skrypt: tools/local_image/comfy_fullchain_readonly_preflight_dev.py. Wynik na serwerze: preflight PASS, errors=[], fullchain_live_gate BLOCKED.
- Surowy JSON i pełny log testów w /srv/ai-data/staging/gpu-dual-route-20261023/ (nie publikować bez redakcji).
- Żadne produkcyjne uprawnienia, usługi, sterowniki, firmware, kernel, GRUB ani limity mocy nie były zmieniane.

## C. Modele i pamięć — stan potwierdzony, inferencja nieprzetestowana

| Składnik | Dane z rzeczywistego hosta | Gate |
|---|---|---|
| Qwen3.6 35B Hermes | qwen3.6:35b-hermes64k obecny; 23 938 333 331 B; 36.0B Q4_K_M; num_ctx=65536 | NOT_TESTED |
| FLUX2 Klein FP8 | 4 070 624 520 B; plik obecny | NOT_TESTED pełny FLUX |
| Qwen 3 4B text encoder | 8 044 982 048 B; plik obecny | NOT_TESTED |
| FLUX2 VAE | 336 213 556 B; plik obecny | PASS tylko wcześniejszy realny VAE |
| Razem 3 pliki FLUX2 | 12 451 820 124 B (~11,60 GiB) na dysku | NOT_TESTED rzeczywisty RAM peak |

Ważne: rozmiar na dysku nie jest szczytem RAM/VRAM. Projekt jednostki DEV ma MemoryMax=12G. Qwen jest duży i ma num_ctx=65536; rzeczywisty RAM/KV cache, czas i GPU będą mierzone dopiero pod kontrolą RM. Współdzielonej pamięci Radeona nie można budżetować według pozornej ROCm VRAM. Nie uruchamiać Qwen i FLUX2 równocześnie na AMD.

## D. Nowo potwierdzone blokady izolowanej integracji DEV

1. Oryginalny Hermes prompt compiler dopuszcza tylko produkcyjny Gateway loopback :11435.
2. Hermes Resource Queue i media_admission również wymagają :11435; wewnętrzny guard require_external_media_use ma ten adres zakodowany na stałe.
3. Oryginalny generator image oraz image-edit kierują ruch na :8188. Domyślny image text-to-image to 1024×1024.
4. W DEV Gateway włączony physical_router celowo odrzuca requesty z zewnętrznym lease header (gpu_route_lease_not_supported). Łączenie routingu dwóch GPU z tym samym zewnętrznym lease Hermes bez nowego testu jest niedopuszczalne.
5. Potrzebujemy jawnie odizolowanych połączeń DEV Gateway :11656 / ComfyUI :11657 i osobnego output na NVMe, bez przypadkowego fallback na :11435/:8188.
6. Rzeczywisty Qwen musi dokończyć inferencję i zostać wyładowany przed przydziałem ComfyUI. Aktywny proces produkcyjny nadal jest właścicielem KFD; żaden drugi test GPU nie może działać obok niego.

To są bramki do zaadresowania małymi zmianami w kodzie DEV, nie przesłanki do wdrożenia produkcyjnego.

## E. Formalna macierz odbioru

| Wymaganie | Status | Dowód / blokada |
|---|---|---|
| Pełne GitHub CI i buildy release | PASS | #803, commit 9102e8a |
| Lokalna regresja systemd i Hermes | PASS | 16/16; pełny pytest exit 0 |
| Hermes /foto do izolowanego RM HTTP — logika | PASS | Wcześniejsze 11/11; Qwen/Comfy symulowane |
| Qwen rzeczywiście generuje JSON PL generate/edit | NOT_TESTED | Bez realnej inferencji |
| Qwen wyładowany przed startem ComfyUI w jednym lease | NOT_TESTED | Brak połączonego cyklu |
| FLUX2 Klein realne text-to-image PNG | NOT_TESTED | Dotąd tylko VAE |
| Prawdziwy ComfyUI on-demand na AMD / wcześniejszy VAE | PASS | Wcześniejszy DEV GPU + rollback |
| Powtarzalne uruchamianie pełnego FLUX2 | NOT_TESTED | Po pojedynczym pełnym PASS |
| RM lease fail-closed przy odmowie stop | PASS | Test negatywny 24.10 |
| Driver AMD reuse safe / MES / KFD | BLOCKED | GPU_REUSE_SAFE=NOT_VERIFIED |
| AMD system-wide RM-only GPU admission | BLOCKED | Grupy render, deskryptory, bypass |
| NVIDIA system-wide RM-only GPU admission | BLOCKED | NVIDIA device nodes 0666 |
| N1 / SHARED granty dwóch GPU | BLOCKED | Brak odbioru fizycznej izolacji |
| SIGKILL/OOM w aktywnym kernelu ROCm | NOT_TESTED | Wymaga odrębnej autoryzacji |
| Hermes / Telegram realne dostarczanie obrazów | NOT_TESTED | DEV bez realnych odbiorców |
| WVC priorytety podczas live FLUX2 | NOT_TESTED | Nie testowano live |
| Vision przydziały podczas live FLUX2 | NOT_TESTED | Nie testowano live |
| Gateway boot bez ComfyUI | BLOCKED | Produkcyjny Requires=comfyui.service |
| Restart hosta i recovery marker | NOT_TESTED | Wymaga okna serwisowego |
| Niezależny watchdog + rollback historyczne | PASS | Wcześniejsze rzeczywiste rollbacki |
| Docelowy controller systemd on-demand | NOT_TESTED | Unit draft, niezainstalowany |
| Release Candidate / cutover | BLOCKED | B–F nieodebrane |

**Werdykt: Gate A PASS; Gate B/C i Release Candidate BLOCKED.**

## F. Plan jednego zatwierdzanego okna GPU — jeszcze NIE URUCHAMIAĆ

1. Minimalny opt-in endpoint routing w odizolowanych procesach DEV; testy negatywne 11435/8188 i brak Telegram, bez zmian produkcji.
2. Sprawdzenie jednego RM lease przez Qwen, warunków physical_router, poprawności odpowiedzi JSON i jawnego wyładowania modeli.
3. Przygotowanie zasobów na NVMe i budżetu pamięci fizycznej. Nie podnosić limitów tylko na podstawie rozmiarów plików.
4. Oprzeć operator-only uruchomienie na istniejących, sprawdzonych mechanizmach maintenance-20261023: wyłączny lock, root-only scoped systemd, osobny watchdog rollback, snapshot, preflight, recovery marker.
5. Tuż przed przerwaniem produkcji: potwierdzić Gateway RM IDLE, brak zadań i modeli, poprawne PCI, RTX idle, brak innego właściciela GPU po stop.
6. Jeden realny cykl: oryginalny Hermes worker → realny Qwen PL → ten sam RM → systemd ComfyUI na AMD → FLUX2 Klein 256×256, 4 kroki, lokalny PNG/SHA256. Bez Telegram. Bounded timeout i pamięć.
7. Sprawdzić osobno: job done, models unloaded, PID/cgroup gone, driver state/E_safe. Błąd → zachować marker i dowody, niezależny rollback, bez automatycznego ponownego grantu.
8. Dopiero po pierwszym PASS: kontrolowany reuse, negatywne scenariusze, WVC/Vision i formalne odbiory izolacji. RC i cutover wymagają osobnej decyzji.

## G. Izolowane źródła DEV przygotowane do dalszego spięcia

- Narzędzie: tools/local_image/prepare_comfy_fullchain_isolated_dev.py (--check / --prepare).
- Na serwerze wykonano --check oraz --prepare: DEV_SNAPSHOT_SOURCE_STATIC_PASS i DEV_SNAPSHOT_PREPARED_NO_EXECUTION.
- Początkowy snapshot DEV bez przechwytywania dostarczania znajduje się w /srv/ai-data/staging/comfy-fullchain-dev-20261024; **nie uruchamiać tej wersji**.
- Historyczny snapshot z capture: /srv/ai-data/staging/comfy-fullchain-dev-20261024-captured; **nie uruchamiać go** — pierwotne ścieżki fallback/lock nie były jeszcze całkowicie odseparowane.
- Aktualny snapshot: /srv/ai-data/staging/comfy-fullchain-dev-20261024-guarded. Manifest SHA256 obejmuje oryginalne pliki i kopie, a audyt porównuje również resztę pakietu ai_bridge z bieżącym worktree.
- Klient RM/Qwen/media admission wskazuje 127.0.0.1:11656, generatory 127.0.0.1:11657; output/input/jobs/lock/Hermes inbound mieszczą się wyłącznie w staging. Domyślne text-to-image 256×256.
- Kopie _send i _notify zapisują komunikaty wyłącznie do JSONL i wymagają targetu telegram:DEV_UNROUTABLE_NO_SEND. Oryginalna binarka CLI Hermesa jest dodatkowo wyłączona w snapshot. Fallbacki generatora, kompilatora i pomocniczego klienta kierują na snapshot, nie do /usr/local.
- tools/local_image/fullchain_gpu_window_preflight_dev.py --check wykonał na rzeczywistym serwerze audyt read-only: **PASS**, problems=[]; brak ingerencji w systemd/GPU.
- Testy izolacji snapshot/HTTP/negatywne preflight wykonano w CPU-only. Wszystkie scenariusze odmowy nieautoryzowanej komunikacji oraz modyfikacji źródła i markera przeszły.
- **To wciąż nie jest dopuszczony runner rzeczywistego GPU.** Przed live Qwen/FLUX2 trzeba odebrać limit pamięci, niezależny watchdog, bezpieczne wyładowanie Ollama podczas rollbacku i warunki sterownika. Nie uruchamiać snapshotu jako testu GPU.
- Nie zmieniono portów produkcji, ani nie wykonywano nowego zadania GPU.

## H. Naprawa kolejności Qwen → ComfyUI przed testem GPU (DEV)

Audyt zidentyfikował błąd kolejności: wcześniejszy OnDemandComfyLifecycle najpierw startował proces ComfyUI, a dopiero potem GPUResidency.enter_media czyścił rezydentne modele Ollama. Przy rezydentnym Qwen na AMD mogłoby dojść do przejściowego współdzielenia urządzenia.

- W trybie on-demand najpierw zapisujemy trwały recovery marker, a następnie wyładowujemy modele Ollamy, odpytując /api/ps aż do pustej listy. **Dopiero po tym** kontroler może wystartować ComfyUI. Rezerwacja RM pozostaje aktywna cały czas.
- Po starcie następuje ponowne sprawdzenie i ewentualne wyładowanie nowej rezydencji, a następnie walidacja stanu ComfyUI.
- Błąd lub timeout wyładowania oznacza fail-closed: **brak startu ComfyUI, RM zablokowany, recovery marker zachowany**.
- Test CPU z realnie zasymulowanym rezydentnym Qwen wymaga pustej Ollamy **już w callbacku controller.start**. Osobny test wstrzykuje HTTP 503 na wyładowaniu i weryfikuje brak startu oraz zachowanie globalnej blokady.
- **Nie jest to potwierdzenie fizycznej izolacji ani GPU_REUSE_SAFE.** Zewnętrzny bypass do urządzeń wciąż pozostaje do wyeliminowania przed produkcją.

Nigdy nie traktować zielonego CI, testu CPU, ani realnego VAE jako potwierdzenia pełnego FLUX2 i bezpieczeństwa sterownika.


## I. Nowy CPU-only HTTP E2E całego kodu /foto

Plik testów: tests/test_hermes_foto_fullchain_http_isolated_dev.py.

W odizolowanych katalogach tymczasowych użyto **rzeczywistego źródłowego workera /foto, kompilatora promptu, generatora obrazu uruchomionego jako oddzielny proces, klienta Resource Managera i nagłówków przydziału**. Uruchomiono rzeczywisty loopback HTTP do izolowanego Gateway na 11656 oraz API emulatora ComfyUI na 11657. Transport upstream Qwen zwrócił deterministyczną odpowiedź, a emulator ComfyUI wygenerował *syntetyczny plik PNG przez CPU*, nie przez FLUX2 ani AMD. Test potwierdził, że po poprawnej sekwencji RM wrócił do IDLE, aktywnych/oczekujących zadań było zero, marker nie pozostał, a komunikat został zapisany wyłącznie w lokalnym capture.

Negatywny scenariusz nieprawidłowego JSON Qwen odmówił dalszej generacji, nie uruchomił kontrolera ComfyUI, zwolnił rezerwację i zachował wyłącznie lokalny komunikat błędu. Potwierdzono również prawidłowe usunięcie nagłówka autoryzacji RM przed upstream Ollama — nie jest to błąd routingu; kontrolę lease wykonuje Gateway.

**Wynik: 2/2 PASS (w pełni CPU + mock modeli). FULLCHAIN_REAL_INFERENCE=NOT_TESTED.**

## J. Osobna bramka bezpiecznego rollbacku po Qwen

Wcześniejszy niezależny rollback VAE był testowany przy pustej Ollamie. Nie wolno automatycznie uznać go za bezpieczny po pełnej inferencji Qwen 35B: Qwen może pozostać rezydentny albo nadal wykonywać zadanie, gdy DEV ComfyUI już nie odpowiada.

Zanim wolno uruchomić okno GPU z Qwen, rollback musi:
1. Potwierdzić zatrzymanie DEV Gateway/worker, brak otwartego portu 11656, oraz stan exact systemd unit, PID, boot i cgroup DEV ComfyUI.
2. Zaakceptować wyłącznie pusty inventory Ollama albo bezpiecznie i jawnie wyładować zatwierdzony model Qwen, sprawdzając ponownie /api/ps. Jakikolwiek inny rezydentny model lub timeout → fail-closed.
3. Zweryfikować brak pozostałych deskryptorów AMD /dev/kfd i renderD128 przed przywróceniem produkcyjnego ComfyUI. Sam brak modelu w /api/ps nie jest dowodem bezpieczeństwa sterownika.
4. Przy braku dowodów nie uruchamiać kolejnego właściciela GPU i zachować marker, watchdog oraz logi. Dalsze odzyskiwanie wymaga operatora.
5. Dopiero po potwierdzonym bezpiecznym powrocie uruchomić oryginalne ComfyUI/Gateway, smoke-testować dostępność i zakończyć okno.

**Rollback dla live-Qwen/full-FLUX2 = NOT_READY. Nie uruchamiać operator-only testu, dopóki nie zostanie przetestowana taka procedura.**


## K. Walidacja rollbacku read-only i poprawka przenośności CI

- Moduł tools/local_image/fullchain_rollback_gate_dev.py weryfikuje jedynie predykaty fizycznego procesu: DEV unit inactive, MainPID=0, pusty cgroup, potwierdzony koniec identyfikacji workera, zamknięte porty DEV 11656/11657, ścisły JSON /api/ps Ollama i brak właścicieli AMD. Sam moduł **nie zatrzymuje, nie uruchamia i nie przywraca żadnych usług**.
- Wynik syntetyczny, gdy wszystkie obserwacje są poprawne: restore_prerequisites=PASS, ale gpu_reuse_safe=NOT_VERIFIED i permission_to_start_production_comfy=false. Predykat nigdy nie przyznaje prawa do produkcyjnego grant GPU.
- Wynik rzeczywistego read-only wywołania na działającym serwerze bez sudo: **BLOCKED**, ponieważ nie istnieje jeszcze dowód zakończenia przyszłego workera i odczyt właścicieli urządzeń przez zwykłe konto nie może poświadczyć pełnej listy PID. Oczekiwane zachowanie fail-closed.
- 23 testy CPU-only klasyfikacji rollbacku: PASS; symulowana rezydencja Qwen wymaga jawnego unload, nieznany model (np. WVC) jest odrzucany, błędy i niekompletne obserwacje nie dają prawa do restore.
- To **kontrakt zabezpieczeń**, nie ukończony skrypt watchdog/rollback. Konieczna pozostaje kontrolowana implementacja rozładowania Qwen, odzyskania PID/cgroup i bramka sterownika GPU, przed oknem serwisowym z pełnym FLUX2.

GitHub Actions run #808 po commicie 0f8fd36 zakończył się **failure** (3 niepowodzenia mimo lokalnej regresji PASS):
1. Dwa testy HTTP worker miały host-only /home/harrypotter/AI-server/.venv/bin/python zamiast przenośnego sys.executable.
2. Starszy test lost wakeup Comfy cleanup z timeout=0,6 s wykazał podatność na opóźnienie asyncio w GitHub Actions. Powiększono **wyłącznie budżet czasu testu** do 3,0 s, bez zmian runtime; drugi test sprawdzający dokładną zależność czasową pozostaje niezmieniony.

Lokalne testy ukierunkowane po poprawce (26 PASS). Zaliczenie Gate A dla najnowszego commita wymaga nowego **GitHub CI SUCCESS** oraz pełnych release builds, nie wolno polegać na wcześniejszym #807.

**Aktualny Gate B/C: BLOCKED — brak realnej inferencji Qwen i FLUX2 oraz bezpiecznego zatwierdzonego okna GPU.**


Uzupełnienie po CI #809 (commit f6dcded): wszystkie nowe testy fullchain i guard przeszły, ale jeden starszy test test_empty_torch_allocator_is_not_proof_of_comfy_unload[False-1] przekroczył 50 ms podczas **poprawnego wejścia** w stan media na obciążonym runnerze. Poprawiono wyłącznie test: przed enter_media stosuje limit 1,0 s, a przed oczekiwanym błędem cleanup ponownie 0,05 s. Obie odmiany testu lokalnie PASS. Wymagana ponowna pełna weryfikacja GitHub CI.


## L. Read-only badanie rozmiaru wag FLUX2 i minimalnego budżetu pamięci

Nowy skrypt tools/local_image/fullchain_flux2_memory_preflight_dev.py czyta wyłącznie nagłówki safetensors (bez torch, bez dotykania KFD/ROCm, bez uruchomienia modeli). Na realnym serwerze potwierdzono strukturę tensorów:

| Model | Liczba tensorów | Rozmiar wag |
|---|---:|---:|
| FLUX2 Klein 4B FP8 | 309 | 3,791 GiB |
| Qwen 3 4B text encoder BF16 | 398 | 7,492 GiB |
| FLUX2 VAE FP32 | 251 | 0,313 GiB |
| **Suma wag** | **958** | **11,597 GiB** |

To jest **dolna granica**: nie obejmuje allocatorów PyTorch/HIP, activations, VAE scratch, cgroup page cache, hosta ani ewentualnych kopii/konwersji wag. Pole MemTotal hosta wynosi 31 965 708 kB (~30,49 GiB); MemAvailable w czasie audytu ~25,79 GiB, zmienne.

Obecny profil draft ComfyUI DEV ma **MemoryMax=12G**. Weryfikator porównuje dolną granicę z cgroup MemoryMax plus **screening margin 2 GiB** (nie jest to zmierzony maksymalny narzut modelu). Wynik na hoście: **cgroup_screen=INSUFFICIENT, host_screen=PASS, exit code 4**. Ten wynik oznacza **BLOCKED dla obecnego limitu**, nie błąd modelu. Przed rzeczywistym startem konieczny osobny przegląd limitów i brak innych właścicieli pamięci. Nie ustawiono nowego MemoryMax ani MemoryHigh.

Testy CPU parsera safetensors, offsetów, symlinków, formatów MemoryMax i budżetu odmowy: PASS. Każda poprawna analiza nadal ustawia fullchain_gpu_authorized=false i gpu_reuse_safe=NOT_VERIFIED.

## M. Kontrolowany, wąski proces unload Qwen po inferencji — DEV, nie wdrożony

Moduł tools/local_image/fullchain_qwen_drain_dev.py przygotowuje pojedynczą funkcję odbiorową do użycia **wyłącznie wewnątrz przyszłego root-owned, operator-authorized recovery runnera**. Zwykłe CLI pozwala wyłącznie na --check (GET /api/ps, bez wyładowywania). Na hoście: NO_QWEN_RESIDENT, unload_executed=false.

Przed możliwym unlodem moduł wymaga jednocześnie:
- istniejącego zaufanego recovery marker i uzbrojonego niezależnego watchdog;
- potwierdzonego zakończenia workera Hermes (pełna tożsamość), zatrzymanego DEV Gateway/ComfyUI, zamkniętych portów 11656/11657, pustego DEV cgroup;
- produkcyjnych ComfyUI i Gateway wyłączonych na czas maintenance oraz działającej Ollamy;
- ścisłego inventory /api/ps. Dopuszczony **tylko** qwen3.6:35b-hermes64k, inne aliasy, WVC i pozostałe modele prowadzą do BLOCKED;
- potwierdzenia, że każdy proces trzymający AMD (jeśli jest) należy do /system.slice/ollama.service, odrzucenia obcych PID i niepełnej telemetrii.

Jeśli Qwen jest rezydentny, przekazany zaufany callback wysyła pojedyncze unload modelu, następnie odczytuje /api/ps co najmniej dwukrotnie, z limitem czasu, oraz oczekuje na potwierdzenie braku deskryptorów AMD. Nie wysyła poleceń do innych modeli, nie wyłącza i nie uruchamia jednostek systemd, nigdy nie usuwa markera. W każdym wyniku status driver E_safe i GPU_REUSE_SAFE pozostaje NOT_VERIFIED.

Testy CPU **29/29 PASS** obejmują pozytywny mock, 11 niezależnych blokad precondition, modele obce/WVC, innego właściciela GPU, brak enumeracji PID, wiszące deskryptory i timeout. **Nie przeprowadzono rzeczywistego wyładowania Qwen.**

**Nadal BLOCKED:** nie ma jeszcze zatwierdzonego i przetestowanego niezależnego operatorowego runnera/rollbacku po pełnym FLUX2 ani rzeczywistego odbioru budżetu pamięci. Sama funkcja callback oraz zielone testy CPU nie są przyzwoleniem na test GPU.
