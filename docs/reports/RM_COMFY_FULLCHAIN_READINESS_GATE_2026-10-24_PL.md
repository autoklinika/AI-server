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

Nigdy nie traktować zielonego CI, testu CPU, ani realnego VAE jako potwierdzenia pełnego FLUX2 i bezpieczeństwa sterownika.
