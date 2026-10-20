# Produkcyjny cykl GPU — Ollama → Vision RADIO → ComfyUI → Ollama

**PRODUCTION_GPU_CYCLE_PASS**, 20.10.2026, 13:59:52–14:00:44 CEST. Jeden rzeczywisty cykl zakończony w 52,2 s na działającym produkcyjnym Gateway. Test wykonał użytkownik UID 1000 przez istniejący Resource Manager; sudo nie było potrzebne.

## Wyniki

| Etap | Rzeczywiste wykonanie | Czas |
|---|---|---:|
| Ollama przed Vision | Produkcyjny Qwen 27B, odpowiedź `GPU_HANDOFF_OK`, 5 tokenów | 8,112 s |
| Vision RADIO | GPU inference, obraz `visa-pcb2-normal-0000`, mapa 768×768 zgodna z wcześniejszym SHA256 | 7,235 s ładowania i inferencji |
| ComfyUI | FLUX.2 Klein 4B FP8, 4 kroki, seed 20261020, poprawny PNG 512×512 | 18,502 s |
| Ollama po ComfyUI | Ponowne załadowanie Qwena, odpowiedź `GPU_HANDOFF_OK`, 5 tokenów | 9,708 s |

Obie odpowiedzi wykonał `qwen3.8:27b-p4-64k-gpu-p511`, z kontekstem 2048 ustawionym tylko dla żądań testowych. `/api/ps` potwierdziło model i `size_vram=17278089296` B. Przed Vision istniejący RM wyładował Ollamę. RADIO zwróciło score 0,43257656693458557 i hash mapy `95d773a6aed28e0e19a3b7973a6c78542ae85c668104a36dfc70405bbd0af187`; zakończenie workera i sprzątanie potwierdził produkcyjny nadzorca.

ComfyUI zgłosiło trzy załadowane modele i dodatnią rezerwację pamięci GPU podczas wykonania; historia zadania zakończyła się `success/completed=true`. Wygenerowany plik sprawdzono dekoderem Pillow: PNG, 512×512. SHA256: `044e387e93e0ed63c35365c38ee85c775dd19f05b1cc6af25fc1fe7f4d89fee8`.

## Stan po teście

- RM: IDLE, active=0, queued=0, leases=0, admission_blocked=false, recovery_required=false.
- Ollama: brak załadowanych modeli. ComfyUI: loaded_models=0, queue_running=0, queue_pending=0, cleanup_pending=false.
- Alokator ComfyUI po sprzątaniu: 32 MiB, poniżej istniejącego limitu 64 MiB. Pozostał dotychczasowy bezczynny kontekst KFD ComfyUI PID 267058.
- Gateway PID 299020, nadzorca RADIO PID 298901, ComfyUI PID 267058 i Ollama PID 260833 pozostały niezmienione. Nie restartowano usług ani sterownika; host nie był restartowany.
- Brak nowych dopasowań błędów AMDGPU/MES/ring timeout w dzienniku jądra od kursora pobranego przed testem do końcowego odczytu. Brak produkcyjnego markera blokady GPU i jednostek roboczych ai-radio.
- Dodatkowy odczyt po cyklu: `/health`, `/status`, `/control/`, `/api/v1/benchmarks`, `/api/tags`: HTTP 200. Vision nadal `execution_available=true`.

Wykorzystano trzy kolejne zwykłe rezerwacje istniejącego RM: `llm`, `vision-inspection`, `media-image`. Ostatnia obejmowała generowanie ComfyUI i powrót do Ollamy. Przydział był wyłączny, kolejka pozostała pusta; nie uruchamiano drugiego Gateway/RM ani nowego schedulera. Źródła produkcyjnego overlay sprawdzono przed testem z manifestem 239 plików. Test nie zmienia ustawień produkcyjnych, uprawnień ani markerów poza zwykłym lifecycle RM.

## Zakres odbioru i artefakty

Praktyczny odbiór tego jednego cyklu oraz generowanie ComfyUI: **PASS**. Globalne `GPU_REUSE_SAFE=NOT_VERIFIED` i N1=`NOT_ADMITTED` pozostają zgodne z produkcyjną polityką; pojedynczy test nie nadaje zgody dla wszystkich przyszłych zadań. To test integracji, bez pomiaru jakości detekcji PCB ani długotrwałej stabilności. RADIO nadal obsługuje przypięty obraz kalibracyjny.

- [Pełny wynik i obserwacje runtime](GPU_PRODUCTION_CYCLE_2026-10-20.json).
- [Log wykonania](GPU_PRODUCTION_CYCLE_2026-10-20.log).
- [Wygenerowany obraz testowy](assets/GPU_PRODUCTION_CYCLE_2026-10-20.png).
- [Jednorazowy scenariusz odbioru](../../tools/accept_production_gpu_cycle.py).

Etap integracji i praktycznego odbioru współdzielenia GPU jest zakończony w opisanym zakresie. Kolejny etap funkcjonalny to przyjmowanie własnych obrazów ze stanowiska Vision, gdy stanowisko będzie gotowe.
