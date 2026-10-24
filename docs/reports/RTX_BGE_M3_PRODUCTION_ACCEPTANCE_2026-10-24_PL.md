# AI Platform — migracja produkcyjnego BGE-M3 na RTX 5060 Ti

**Data:** 2026-10-24 (CEST)  
**Host:** `harrypotter-AI-Series`, Ubuntu 26.04  
**Wynik wdrożenia:** **RTX_BGE_PRODUCTION_CUTOVER_PASS**  
**Wynik niezależnego odczytu po wdrożeniu:** **PASS** (18:59 CEST)  
**Zakres:** wyłącznie fizyczne wykonanie embeddingów BGE-M3 na RTX; bez wymiany modelu, bez przełączania dużych LLM ani przebudowy Resource Managera.

## 1. Decyzja i stan przed migracją

- Produkcyjny model embeddingowy Knowledge Service pozostaje **BGE-M3**, 1024 wymiary, cosine, indeks `knowledge_dense_bge_m3_1024_v1`, profil `dense-bge-m3-1024-cosine-v1`. Nazwa modelu, geometria wektora i format indeksu nie uległy zmianie.
- BGE-M3 był obsługiwany przez współdzieloną Ollamę z Radeonem 890M, co powodowało rywalizację o ten sam runtime z dużym Qwenem.
- Dla RTX 5060 Ti (ASUS, 16 GB, NVIDIA Open 615.71.09) powołano **odrębną lokalną instancję Ollamy**. Nie przełączano globalnie `ollama.service` na CUDA, bo Qwen 27B nie mieści się w 16 GB VRAM.
- Jeden istniejący Gateway / Resource Manager, jeden scheduler i kolejka `gateway_max_concurrency=1`; żądania małego modelu nie omijają przydziału RM.

Wcześniejsze dowody DEV: 23.10 test dwóch różnych małych modeli (`qwen3:0.6b` + `bge-m3:latest`) na jednym RTX zakończył się `PASS`, przy 1441 MiB zajętej VRAM. Test fizycznego routingu AMD (Qwen 0.6B) + RTX (BGE-M3), z jednym schedulerem DEV, również `PASS`. **Te próby nie stanowiły wdrożenia produkcyjnego ani dopuszczenia N1.**

## 2. Produkcyjna architektura po zmianie

```text
Knowledge Service / RAG
  -> EmbeddingProvider (embedding-local, model bge-m3)
  -> Gateway + istniejący RM (:11435), jedna kolejka
  -> tylko /api/embed, /api/embeddings i /v1/embeddings,
     tylko model bge-m3 / bge-m3:latest
  -> Ollama RTX (:11436, CUDA device 0)
  -> NVIDIA RTX 5060 Ti 16 GB

Qwen3.8 27B / WVC / Hermes
  -> ten sam Gateway + RM (:11435)
  -> dotychczasowa Ollama (:11434)
  -> Radeon 890M / pamięć współdzielona

ComfyUI i Vision RADIO: bez zmian, dotychczasowy tor Radeon.
```

Dodatkowa usługa: `ollama-rtx-small.service`, `active/enabled`, tylko loopback. Magazyn modeli ma oddzielną kopię **wyłącznie BGE-M3**, bez usuwania oryginału ze współdzielonej Ollamy. Konfiguracja RTX: `OLLAMA_VULKAN=0`, `CUDA_VISIBLE_DEVICES=0`, `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=10m`. Model może być wyładowany z GPU w spoczynku: **4 MiB w `nvidia-smi` przy bezczynności nie oznacza, że usługa jest wyłączona**.

Fizyczne endpointy:
- `127.0.0.1:11434` — istniejąca Ollama / duże LLM, bez zmian;
- `127.0.0.1:11435` — istniejący Gateway / RM;
- `127.0.0.1:11436` — nowa Ollama CUDA, aktualnie tylko `bge-m3:latest`.

## 3. Instalacja, odbiór i dowody

Operator uruchomił:
```bash
sudo bash /srv/ai-data/staging/rtx-small-migration-20261024/apply-rtx-bge.sh apply
```

Wynik z terminala operatora (kolejność kluczowych gate'ów):
```text
RM_IDLE_PASS
RTX_BGE_MODELSTORE_PASS
RTX_BGE_TAG_PASS
RTX_BGE_REAL_1024_EMBED_PASS
RTX_GPU_INFERENCE_PASS vram_mib=816
RM_IDLE_PASS
PRODUCTION_RM_RTX_ROUTE_PASS
RTX_BGE_RM_VECTOR_MATCH_PASS 0.0
RTX_BGE_PRODUCTION_CUTOVER_PASS
```

- BGE-M3 wykonał rzeczywiste embeddingi o wymiarze **1024** na RTX. Podczas próby `nvidia-smi` raportował **816 MiB** użytej pamięci całej karty; jest to pomiar GPU w czasie inferencji, nie stały footprint.
- Żądanie bezpośrednio na RTX i identyczne żądanie przez produkcyjny RM dały **maksymalną różnicę współrzędnych 0.0**. Jest to test **zgodności ścieżek RTX-direct vs RM→RTX**, **nie** benchmark jakości RAG ani porównanie wektorów Radeon↔RTX.
- Potwierdzono nagłówek zadania Gateway (`X-AI-Gateway-Job-Id`) — żądanie obsłużył RM, a nie niezarządzany bezpośredni bypass.
- Podczas restartu Gateway `curl` raz zgłosił `(7) Failed to connect`; następna próba zakończyła się sukcesem. Końcowy gate, weryfikacja tras i bieżące `/health` są poprawne; przejściowy komunikat nie oznacza awarii wdrożenia.

Niezależna kontrola po wdrożeniu (24.10, 18:59 CEST):

| Element | Odczyt |
|---|---|
| `ollama.service` | active |
| `ollama-rtx-small.service` | active, enabled |
| `ai-gateway.service`, `ai-bridge.service` | active |
| `comfyui.service`, `ai-platform-radio.service` | active |
| `/health` Gateway | `status=ok`, `ollama=ok` |
| `/status` Gateway | `rtx_embedding_route={"enabled":true,"model":"bge-m3"}` |
| Zadania RM / oczekujące / lease | `0 / 0 / 0` |
| Legacy `gpu_residency` | `llm`, `recovery_required=false` |
| Marker DIRTY | nieobecny |
| Ollama RTX `/api/tags` | wyłącznie `bge-m3:latest` |
| RTX przy bezczynności (18:59) | 4 MiB, model wyładowany |
| Stage O symlink | nadal `/opt/ai-platform/releases/stage-o-28e3ea214660` |

**Zmiana kodu uruchomieniowego:** oryginalny release Stage O pozostał niezmieniony. Kopia aktywnego wcześniej overlay Vision RADIO została uzupełniona o dokładne przekierowanie tylko BGE-M3 i włączona jednym usuwalnym drop-inem:
- `/opt/ai-platform/gateway-overlays/rtx-bge-m3-20261024/src`
- `/etc/systemd/system/ai-gateway.service.d/zz-rtx-bge-m3.conf`
- `AI_BRIDGE_GATEWAY_RTX_EMBED_URL=http://127.0.0.1:11436`
- `PYTHONPATH=/opt/ai-platform/gateway-overlays/rtx-bge-m3-20261024/src`.

## 4. Testy przygotowawcze i odtwarzalność

Na izolowanej kopii Gateway przeprowadzono testy `RTX_EMBED_RM_INTEGRATION_PASS` dla:
- trzech endpointów embeddingów BGE-M3 kierowanych na `:11436`;
- innych modeli i `/api/generate` kierowanych nadal na `:11434`;
- działającej kolejki RM z nagłówkami job ID;
- konfiguracji bez przekierowania (fallback);
- obecności włączonego Vision RADIO.

Artefakty na hoście:
- `/srv/ai-data/staging/rtx-small-migration-20261024/prepare_overlay.py`
- `/srv/ai-data/staging/rtx-small-migration-20261024/test_gateway_route.py`
- `/srv/ai-data/staging/rtx-small-migration-20261024/apply-rtx-bge.sh`
- `/var/lib/ai-platform-rtx-bge-20261024/`: `tags.json`, `direct.json`, `rm.json`, `rm-headers.txt`, `rm-status.json` (katalog serwisowy, dostęp administracyjny).

Weryfikowalne SHA-256:
- `apply-rtx-bge.sh` — `5bc4ccfc2f0affa8362d0bee24ec077a4c43069299631a72664535bd2ef212b1`
- produkcyjny overlay `gateway/app.py` — `bd6d1c5f92d649c471df4d697b7fe16fb91930acc9d74aee514a925e84ffecac`
- produkcyjny overlay `settings.py` — `179bf7d7f4124ad8c68a4d9591e3b2c0e1d22427b19fbe561905c0a1048ddad8`
- `test_gateway_route.py` — `cfb5d7095b4ef22e83efef30b3d2af88b997d802637c7711dfac7f9114346ad0`.

## 5. Granice akceptacji i ryzyka pozostawione bez zmian

1. `GPU_REUSE_SAFE=NOT_VERIFIED`, globalna izolacja urządzeń GPU i `N1_GRANTS=NOT_ADMITTED` **nie zostały zamienione na PASS**. Host nadal może dopuszczać lokalne wejścia do Ollamy / GPU poza RM; ochrona dotyczy zarządzanej ścieżki Gateway. Nie wdrożono osobnego globalnego schedulera ani dwóch niezależnych kolejek.
2. Nie przeprowadzono pełnego testu Knowledge Service→Qdrant→RAG na produkcyjnym korpusie **po** migracji; nie wykonano nowego porównawczego benchmarku wydajności i retrievalu Radeon/RTX. Nie deklarować tych pomiarów jako PASS.
3. Nie wykonano produkcyjnego rollbacku; procedura jest przygotowana i dostępna, ale **rollback po wdrożeniu = NOT_EXECUTED**. Zasady poniżej.
4. `main` repo nadal bazuje na wcześniej zatwierdzonym overlay Vision RADIO. Fizyczny routing BGE-M3 istnieje na hoście w osobnym overlay i drop-inie. Przy przyszłym redeploy z `main` trzeba świadomie przenieść tę wąską poprawkę, inaczej zniknie; nie mylić raportu stanu z wdrożeniem zmian kodu do `main`.

## 6. Małe modele: decyzja z 24.10.2026

| Model | Rola / stan | Decyzja |
|---|---|---|
| **BGE-M3 (~567M)** | rzeczywiste produkcyjne embeddingi Knowledge Service | **RTX w produkcji — PASS** |
| **GLiNER2.5-Decide 340M** | kandydat benchmarkowy, lokalny cache, CPU | **NIE wybrano do produkcji** |
| **GLiNER2.5-multi-Decide 287M** | model testowy w cache | **bez wdrożenia** |
| **GLiNER2.5-small** | lekki wariant testowy w cache | **bez wdrożenia** |
| **Whisper Small** | cache, bez aktywnej usługi | **bez zmian** |
| **Clef (~27B)** | model referencyjny/benchmarkowy | **nie jako lekki router produkcyjny** |
| **AnomalyVFM RADIO** | odrębny executor Vision na AMD | **bez zmian** |

Benchmark routerów z 03.10, 51 przypadków: GLiNER2.5-Decide 340M osiągnął **80,39% route accuracy, 45,10% tool exact, 564 ms średnio**; Clef odpowiednio **94,12%, 88,24%, 5626 ms**. GLiNER jest szybki, lecz jego błędy tool selection dyskwalifikują **automatyczne** wdrożenie na podstawie tych wyników. **Nie ma produkcyjnego wyboru lekkiego routera.** Następny krok: osobny benchmark małych modeli na RTX, bez zmian produkcyjnej trasy.

## 7. Odsyłacze

- [Runbook: RTX małe modele / rollback](../runbooks/RTX_BGE_M3_OPERATIONS_2026-10-24_PL.md)
- [Stage J2 — wybór BGE-M3](AI_PLATFORM_STAGE_J2_KNOWLEDGE_EMBEDDING_BASELINE_2026-09-23_PL.md)
- [Router System One vs GLiNER](AI_PLATFORM_ROUTER_SYSTEMONE_BENCHMARK_2026-10-03.md)
- [RM ComfyUI — osobny tor Radeon](RM_COMFY_MINIMAL_REAL_RADEON_2026-10-24_PL.md)
- [GPU recovery](../runbooks/GPU_RESIDENCY_RECOVERY.md)
