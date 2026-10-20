# ComfyUI — konfiguracja autostartu wdrożona, cykl GPU PASS

20.10.2026, instalacja odebrana o 17:45 CEST, test 17:46:42–17:47:32 CEST. **COMFYUI_BOOT_CONFIG_PASS** i **PRODUCTION_GPU_CYCLE_PASS**. Odbiór po restarcie był przy zapisie tego raportu PENDING; następnie przeszedł **PASS o 17:52 CEST** — [raport końcowy](COMFYUI_POST_REBOOT_ACCEPTANCE_2026-10-20_PL.md).

## Wdrożona konfiguracja

Operator uruchomił pakiet z manifestem `a77e1a8245583f80467f995674ee6929b25dba04123724938b6432ee1288d1da`. Wynik: recovery_performed=true; pierwotne dowody zachowane. Niezależny odczyt potwierdził zgodność wszystkich zainstalowanych plików z manifestem.

- ComfyUI: enabled, active, PID 9093. Sprawdzenie API w ExecStartPost zakończyło się kodem 0 o 17:45:35 CEST.
- Gateway: active, PID 9263, Requires/After=comfyui.service. Zachowane są zależności od Ollamy i nadzorcy RADIO.
- Hermes: active, PID 9278. ExecStartPre potwierdził zdrowy Gateway o 17:45:36 CEST. Telegram, Discord i API połączone.
- Nadzorca RADIO PID 2076 i Ollama PID 3340 pozostały uruchomione. NRestarts=0 w odczytanych jednostkach.
- Preload Ollamy i timer analizy: disabled/inactive.
- Oba menedżery systemd zgłaszają zero jednostek failed. Marker residency.blocked oraz managed-worker.dirty nie występują.

## Rzeczywisty cykl po instalacji

Wykorzystano istniejący `tools/accept_production_gpu_cycle.py`, bez zmian kodu. Jednorazowo wybrano osobną ścieżkę raportu, aby zachować wcześniejszy wynik. Rezerwacje i przełączenia obsłużył produkcyjny Gateway/RM. Czas całej procedury: 49,869 s.

| Etap | Wynik | Czas |
|---|---|---:|
| Ollama przed Vision | Qwen 27B, GPU_HANDOFF_OK, potwierdzona rezydencja GPU | 4.883 s |
| RADIO | rzeczywista inferencja GPU, mapa zgodna z odebranym SHA256 | 7.011 s ładowania i inferencji |
| ComfyUI | FLUX.2 Klein, zweryfikowany PNG 512×512 | 18.809 s |
| Ollama po ComfyUI | Qwen ponownie załadowany, GPU_HANDOFF_OK | 8.975 s |

Obraz ComfyUI ma SHA256 `044e387e93e0ed63c35365c38ee85c775dd19f05b1cc6af25fc1fe7f4d89fee8`, zgodny z wcześniejszym odebranym testem. RADIO zwróciło score 0.43257656693458557 i oczekiwaną mapę 768×768. Worker zakończył się ze sprzątaniem potwierdzonym przez nadzorcę.

Po cyklu: active=queued=leases=0, RM=IDLE, admission_blocked=false, recovery_required=false. Oba runtime'y zgłaszają zero modeli; ComfyUI nie ma kolejki ani cleanup_pending. Alokator ComfyUI: 35 651 584 B, poniżej istniejącego limitu 67 108 864 B. Usługi zachowały te same PID-y przez cały test. Nie restartowano usług, hosta ani sterownika w trakcie cyklu; nie wykryto dopasowań błędów GPU w sprawdzonym oknie dziennika.

## Granice odbioru i następny krok

Ten historyczny wynik potwierdził wdrożenie konfiguracji i działanie trzech silników przed kolejnym restartem, w boot ID `074cd2c7-3a21-4347-b99b-fbe012d0a4e5`. Późniejszy odbiór na nowym boot ID potwierdził start usług, gotowość API, komunikatory, RM, GPU i Stage K; jego dowody zawiera raport końcowy wskazany wyżej.

Globalne GPU_REUSE_SAFE pozostaje NOT_VERIFIED, N1 NOT_ADMITTED. RADIO nadal obsługuje przypięty obraz kalibracyjny. Te ustawienia nie są zmieniane przez autostart ani pojedynczy test.

[Wynik operatora, pełny cykl i niezależny odczyt usług](COMFYUI_BOOT_CONFIG_ACCEPTANCE_2026-10-20.json).

Kod i raporty są zapisane w lokalnych commitach. Publikacja do GitHub pozostaje wstrzymana po odrzuceniu push przez automatyczną kontrolę; użytkownik nie udzielił jeszcze osobnej zgody na publikację.
