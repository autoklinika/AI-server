# AI Platform — realny test bazowy GPU przez Resource Manager

**Data:** 17.10.2026 (CEST), 22:48. **Host:** Minisforum AI Series, Radeon 890M, Ubuntu 26.04.1, kernel 7.0.0-39-generic.
**Wynik:** GPU + istniejąca ścieżka Gateway/Ollama = PASS. Własny managed GPU worker = BLOCKED/NOT TESTED. SHARED/EXCLUSIVE na prawdziwym GPU = NOT TESTED. GPU_REUSE_SAFE = NOT_VERIFIED.

## Zakres i ograniczenia

Wykonano dwa małe żądania inferencji **przez istniejący Gateway port 11435**, który w produkcji zarządza kolejką zadań Ollama. Nie uruchamiano oddzielnego procesu CUDA/PyTorch, nie modyfikowano sterownika ani konfiguracji usług; model Qwen3.8 27B był już załadowany przez Ollamę. Test miał porównać działanie GPU z rozliczeniem zadania przez obecny RM.

Preflight: brak aktywnych/oczekujących zadań Gateway, brak leasingów, RM `gpu_residency=llm` bez recovery flag, PyTorch ROCm obecny i identyfikuje Radeon 890M. ComfyUI miał otwarty kontekst KFD/DRM, brak aktywnej kolejki i załadowanych modeli. Przed testem GPU busy=0%, ale zajęte ~23.8GB pamięci — NIE oznacza to GPU_REUSE_SAFE.

## Wyniki

| Miara | Przebieg A | Przebieg B |
|---|---:|---:|
| Godzina lokalna | 22:48:06 | 22:48:34 |
| Model | Qwen3.8 27B P511 | Qwen3.8 27B P511 |
| Limit tokenów | 8 | 48, think=false |
| Czas | 3.101 s | 2.277 s |
| Maks. obciążenie GPU | 66% | 46% |
| Gateway active_count w trakcie | >0 | >0 |
| Tokeny wyjściowe | 8 | 2 |
| Done | True | True |
| Niepusta odpowiedź tekstowa | Nie | Tak |
| Gateway active/queued po | 0/0 | 0/0 |
| Stan RM po | llm, nieblokowany | llm, nieblokowany |
| Ocena bazowa | INCONCLUSIVE (limit 8 tokenów) | **PASS** |

Po obu przebiegach brak nowych błędów MES / nieudanych resetów w aktualnym kernel journal. Końcowy status: GPU busy=0%, Gateway 0 aktywnych, 0 oczekujących i 0 leasingów.

Surowe dane oraz skrypt testu pozostały lokalnie w `/srv/ai-data/evaluation/gpu-real-baseline-20261017/` (bez przesyłania danych środowiska do publicznego repo).

## Twarda granica bezpieczeństwa dla następnego pilota

Działający Resource Manager obsługuje w `/resource/leases` profile `llm`, `embeddings`, `media-image`, `media-video`, `external`. Metoda `begin_external_use` dopuszcza obecnie **wyłącznie ComfyUI** i konkretną deklarowaną capability. Nie istnieje zaakceptowany kontrakt dla własnego zewnętrznego workera PyTorch/Vision. Sam lease `external` byłby tylko slotem schedulera, **nie uprawnieniem do wykonania własnego joba GPU**.

**Decyzja testowa:** nie obchodzić tej kontroli przez bezpośrednie uruchomienie PyTorch z boku ani na podstawie `gpu_busy_percent=0`. Przed prawdziwym testem niezależnego nadzorowanego procesu należy w istniejącym RM dodać i zweryfikować w DEV minimalny, jawny tryb dla pilota: binding fizycznej karty, zatwierdzony workload, identyfikator inkarnacji, kontrola procesu, logiczny budget, brak bypassu oraz fail-closed po crash/timeout. Nie ma potrzeby nowego koordynatora ani zmian kernela. Zauważalne ryzyko: lokalne procesy na hoście mogą sięgać bezpośrednio po Ollamę lub ComfyUI (loopback) poza Gateway.

**Status decyzji:** realny baseline PASS; dopuszczenie dowolnego nowego workera GPU nadal NO-GO. N1–N5 pozostają w izolowanych Draft PR. Produkcja i urządzenia bez zmian.
