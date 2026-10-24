# AI Platform — benchmark lekkich routerów na RTX 5060 Ti — 2026-10-24

**Stan:** DEV benchmark / real NVIDIA CUDA PASS; **żaden model nie został wdrożony do produkcji**.

## Cel

Wybrać kandydata do szybkiego routingu AI Platform: `knowledge_rag`, `graphify`, `telemetry`, `vision`, `reasoning`, `tool`. Pomiar ma obejmować również zestaw narzędzi (`knowledge.search`, `graphify.query`, `telemetry.read`, `vision.analyze`, `agent.ers`), PL/EN, opóźnienia i VRAM.

Dane: **51 istniejących rzeczywistych przypadków**, zamrożony `golden.v1.jsonl`, SHA-256 `1f829de1eacdd8e19905e28f2d086161f94fd93c691bee586d6171976d0f8edf`. Rozkład tras: **41 knowledge_rag / 10 pozostałych**. Języki: 41 PL, 8 EN, 2 dwujęzyczne. Trzeba uwzględniać macro-F1 i poprawny wybór narzędzi, gdyż stała odpowiedź `knowledge_rag` zapewnia już 80,39% route accuracy, ale macro-F1 tylko 0,149.

## Metoda

- Rzeczywisty **GeForce RTX 5060 Ti 16 GB**, CUDA, sterownik 615.71.09. Lokalne izolowane `ollama serve` na `127.0.0.1:11682`, osobny katalog modeli na NVMe. Port DEV zamknięty po teście; zero dodatkowych usług systemd.
- Jedna aktywna rezerwacja istniejącego produkcyjnego RM (external lease `workload=llm`) na czas każdego przebiegu, heartbeat co 9 s. Pobieranie modeli bez rezerwacji. Żadnej zmiany w Gateway, Qwen, BGE-M3, ComfyUI, Vision RADIO ani istniejącej Ollamie.
- Ten sam prompt klasyfikacyjny co w testach CPU z 21.10: tylko pole `question`, bez kontekstu/wyników gold, bez fine-tuningu. Ollama `/api/chat`, `temperature=0`, `think=false`, `num_ctx=2048`, `num_predict=128`, odpowiedź w JSON z dwoma polami (`route`, `selected_tools`) i schematem wymuszającym dozwolone etykiety.
- Trzy najlepsze modele uruchomiono na **wszystkich 51 przypadkach**. Dwa słabe modele odrzucono po **pilotażu 12 przykładów**, zawierającym 8 przypadków spoza dominującej klasy oraz 4 z `knowledge_rag`.
- Agregacja wykonana zamrożonym kanonicznym scorerem AI Platform używanym także w poprzednim benchmarku; zapisane raw predictions, podziały i błędy. Faza rozruchu/cold load wpływa na maksymalne i p95 opóźnienia; dla częstego routingu bardziej reprezentatywna jest mediana warm.

## Pełny benchmark GPU (51 przypadków)

| Model / GPU | Trafność trasy | Macro-F1 | Właściwy zestaw narzędzi | Recall narzędzi | Zbędne narzędzia (FPR) | p50 | p95 | GPU peak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Granite 4 1B** | **47/51 = 92,16%** | **0,8803** | **42/51 = 82,35%** | 86,27% | **0%** | 234 ms | 2314 ms | 3518 MiB |
| Granite 4 3B (Q4) | 43/51 = 84,31% | 0,7975 | 41/51 = 80,39% | **95,10%** | 11,76% | **159 ms** | **224 ms** | **2398 MiB** |
| Qwen3.5 2B | 43/51 = 84,31% | 0,7467 | 38/51 = 74,51% | 77,45% | 3,92% | 209 ms | 253 ms | 3038 MiB |

Dla `Granite4:1b`: **40/41** poprawnych tras PL, **6/8** EN i **1/2** dwujęzycznych; wszystkie 10 tras nie-`knowledge_rag` rozpoznane poprawnie. Główne 4 błędy trasy: błędny wybór `reasoning` zamiast `knowledge_rag`. Typowy błąd wyboru narzędzi to **pomijanie pomocniczego `knowledge.search`** przy `graphify` lub `vision`, bez przypadków zbędnego uruchomienia narzędzia. Ograniczenie: najmniejsze klasy mają zaledwie 1–3 przypadki.

**Granite 4 3B** jest lżejszy w pamięci i szybszy w medianie od 1B głównie ze względu na różne warianty wag udostępniane jako domyślne tagi (3B: Q4_K_M, 1B: większy wariant BF16), a nie dzięki mniejszej liczbie parametrów. Zyskuje tool recall kosztem 11,76% false positives.

## Pilotaż 12 przypadków (nie porównywać jako pełny benchmark)

| Model | Trafność trasy | Tool exact | p50 | Peak GPU |
|---|---:|---:|---:|---:|
| Granite 4 1B | 11/12 | 8/12 | 199 ms | 3518 MiB |
| Granite 4 3B | 10/12 | 9/12 | 183 ms | 2398 MiB |
| Qwen3.5 2B | 9/12 | 8/12 | 203 ms | 3036 MiB |
| Granite 4 350M | 2/12 | 3/12 | 72 ms | 952 MiB |
| FunctionGemma 270M | 1/12 | 1/12 | 152 ms | 476 MiB |

FunctionGemma wygenerował też wielokrotne duplikaty tego samego narzędzia — format listy nie nadaje się do podłączenia bez walidacji. To test modelu **bez specyficznego fine-tuningu** w schemacie klasyfikacji, nie test jego pełnego natywnego API function-calling.

## Historyczne punkty odniesienia (CPU / inne API i kwantyzacje)

Wcześniejszy benchmark 51 przypadków:
- Clef ~27B / System One: route 94,12%, macro-F1 0,877, tool exact 88,24%, średnio 5626 ms;
- GLiNER2.5-Decide 340M / CPU: route 80,39%, macro-F1 0,723, tool exact 45,10%, średnio 564 ms;
- Qwen3.5-2B / CPU BF16 (21.10): route 82,35%, tool exact 72,55%.

**Nie jest to bezpośredni, bitowo równoważny ranking opóźnień**: różne runtime, prompt/system format, Ollama JSON schema w GPU vs wcześniejszy Transformers CPU/System One. Wnioski jakościowe są mocnymi przesłankami, ale nie wystarczają do automatycznej akceptacji produkcyjnej.

## Decyzja etapu i następny test

**Kandydat numer 1: Granite 4 1B.** Wygrywa na naszym 51-case golden w trafności tras, macro-F1, tool exact i braku niepotrzebnych narzędzi wśród nowych małych modeli. **Granite 4 3B: alternatywa** dla niższej latencji/VRAM i wyższego tool recall, jednak większy koszt fałszywych wywołań.

**Nie wdrażać jeszcze.** Kolejny krok to wąska kalibracja wyboru dodatkowego `knowledge.search` na prawdziwych przypadkach, niezależny zestaw testów ochronnych i DEV end-to-end przez zintegrowany RM. Po wyborze test współdzielenia RTX z BGE-M3 oraz pomiar cold start i powtarzalności. GLiNER2.5 multi-Decide i inne warianty pozostają na liście testowej, ale **nie mają dziś odebranego przebiegu GPU**.

## Odbiór serwera i granice bezpieczeństwa

Każdy zakończony przebieg miał `MODEL_UNLOADED`, `RM_LEASE_RELEASED` i `BENCHMARK_CLEAN_PASS`. Po testach wszystkie produkcyjne usługi `ollama`, `ollama-rtx-small`, `ai-gateway`, `ai-bridge`, `comfyui`, `ai-platform-radio` były `active`; RM `active=0`, `queued=0`, `leases=0`, `recovery_required=false`, BGE-M3 nadal na RTX, a `nvidia-smi` idle 4 MiB. Log DEV zawiera `library=CUDA`, `name=CUDA0`, `NVIDIA GeForce RTX 5060 Ti` z fizycznym PCI `0000:03:00.0`. W obserwowanym oknie logu kernela nie wyszukano dopasowanych Xid/AER. Nie jest to długotrwały test stabilności.

**Ważne:** lease w istniejącym RM koordynował próbę, jednak DEV Ollama była oddzielnym procesem, bez pełnej blokady fizycznego dostępu OS. `GPU_REUSE_SAFE=NOT_VERIFIED` i `N1=NOT_ADMITTED` nie zmieniły się. Nie dopisywać PASS dla globalnej izolacji GPU, produkcyjnego routera ani współrezydencji dwóch modeli na RTX.

Artefakty tylko na hoście (bez zrzucania surowych danych ECU do publicznego repo):
- `/srv/ai-data/evaluation/router-rtx-20261024/benchmark.py` SHA-256 `4e593f9648773ea4a4cb786a0d300ecfa508c02b8b903fa9a34e90837eb2f766`.
- `/srv/ai-data/evaluation/router-rtx-20261024/score.py` SHA-256 `2e073e9bf02ce773d90b26cae7d666d3eca190413326b1c52f1ec6aec7abebbc`.
- W tym samym katalogu: `*-full.json`, `*.score.json`, `*-pilot.json`, logi uruchomień, osobny store modeli.
