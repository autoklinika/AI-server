# AI Platform — odbiór po restarcie PASS

**COMFYUI_POST_REBOOT_ACCEPTANCE_PASS**, 20.10.2026. Host uruchomiony o **17:49:47 CEST**; nowy boot ID `2fd517ae-b459-4c09-b995-609f820c0c2d`. Konfiguracja autostartu i rzeczywiste działanie po restarcie zostały odebrane.

## Rzeczywista kolejność startu

| Usługa / sprawdzenie | Gotowość (CEST) | Potwierdzenie |
|---|---|---|
| ComfyUI | 17:50:07 | enabled, ExecStartPost: COMFYUI_READY=PASS, kod 0 |
| Gateway/RM | 17:50:07, po ComfyUI | Requires/After=comfyui.service; zdrowe API |
| Hermes | 17:50:08 | ExecStartPre: gotowy Gateway, kod 0 |

Kolejność potwierdzono także licznikami monotonicznymi systemd. Nie uruchamiano ręcznie żadnej z tych usług po tym restarcie. ComfyUI ma PID 3284, Gateway 4211, Hermes 4356, nadzorca RADIO 2067, Ollama 3292. Wszystkie sprawdzane usługi są active i mają NRestarts=0. Oba menedżery systemd zgłosiły zero jednostek failed. Telegram, Discord i lokalne API Hermes są connected.

Gateway health i Platform API health: HTTP 200 / ready. AI Bridge i PostgreSQL: ok. Control Center oraz API benchmarków: HTTP 200. Nadzorca RADIO i obserwator GPU uruchomiły się automatycznie; przed testem nie było jednostek roboczych RADIO, markerów awarii ani załadowanych modeli.

## Rzeczywisty cykl GPU po restarcie

Test 17:51:12–17:52:08 CEST zakończył się **PRODUCTION_GPU_CYCLE_PASS**, w 56,198 s całej procedury. Wykorzystano odebrany wcześniej scenariusz i istniejący produkcyjny Gateway/RM.

| Etap | Wynik | Czas |
|---|---|---:|
| Ollama przed Vision | Qwen 27B, GPU_HANDOFF_OK; rezydencja GPU potwierdzona | 12.939 s |
| Vision RADIO | inferencja GPU, oczekiwany SHA256 mapy i potwierdzone zakończenie workera | 7.087 s ładowania i inferencji |
| ComfyUI | FLUX.2 Klein, poprawny PNG 512×512 | 18.480 s |
| Ollama po ComfyUI | ponowne załadowanie Qwena i GPU_HANDOFF_OK | 7.907 s |

Wygenerowany PNG ma SHA256 `044e387e93e0ed63c35365c38ee85c775dd19f05b1cc6af25fc1fe7f4d89fee8`, zgodny z obydwoma wcześniejszymi testami. Wszystkie PID-y czterech silników/nadzorcy zachowano w trakcie cyklu. Nie restartowano usług ani sterownika. Nie wykryto dopasowań błędów GPU ani przy kontroli dziennika bieżącego bootu przed testem, ani w oknie testu.

Końcowy niezależny odczyt: **RM=IDLE**, active=queued=leases=0, admission_blocked=false, recovery_required=false. Ollama i ComfyUI zgłaszają brak załadowanych modeli; ComfyUI bez kolejki i cleanup_pending. Rezerwa alokatora 35 651 584 B mieści się w dotychczasowym limicie 67 108 864 B. Nie ma markerów residency.blocked ani managed-worker.dirty. Komunikatory pozostają połączone.

## Stage K

Bieżąca kontrola odczytowa o 17:51:16 CEST: **PASS**, issues=[]. GlobalNAS CIFS i marker są prawidłowe; ostatnia udana kopia ma 3,504 h. Wszystkie trzy timery backupu/monitora są aktywne, następna kopia daily 21.10 o 02:30 CEST. Ustawienia ponowień on-failure / 5 min / maksymalnie trzy próby przetrwały restart. Nie uruchamiano nowego backupu ani ręcznych powiadomień; ten odczyt nie nadpisuje historycznego pliku monitora.

## Zakres i dowody

Odbiór autostartu, kolejności gotowości i jednego pełnego cyklu GPU po restarcie jest **zakończony**. RADIO nadal używa przypiętego obrazu kalibracyjnego. Globalne GPU_REUSE_SAFE=NOT_VERIFIED i N1=NOT_ADMITTED pozostają niezmienione; nie jest to test jakości PCB ani długotrwałej stabilności.

[Pełne dowody: boot, usługi, API, Stage K, cykl GPU i stan końcowy](COMFYUI_POST_REBOOT_ACCEPTANCE_2026-10-20.json). Przejściowy odczyt Platform API health w trakcie testu zawiera jedną testową rezerwację; końcowy stan live_after potwierdza zera.

Wynik z poprzedniego bootu pozostaje w [raporcie instalacji](COMFYUI_BOOT_CONFIG_ACCEPTANCE_2026-10-20_PL.md). Kod i raporty są zapisane lokalnie; publikacja do GitHub pozostaje wstrzymana do osobnej zgody użytkownika po wcześniejszym odrzuceniu push przez automatyczną kontrolę.
