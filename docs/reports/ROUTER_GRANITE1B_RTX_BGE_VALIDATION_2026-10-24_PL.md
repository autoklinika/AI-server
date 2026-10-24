# AI Platform — Granite 4 1B: powtarzalność, kalibracja i współrezydencja RTX z BGE-M3

**Data:** 24.10.2026 (CEST)  
**Status:** testy DEV zakończone; produkcja niezmieniona.  
**Wynik:** powtarzalność **PASS**, współrezydencja RTX **PASS**, nowa polityka routingu **NIEODBIERANA do produkcji**.

## Kontekst i ograniczony cel

Kontynuacja [benchmarku routerów RTX](ROUTER_RTX_DECISION_BENCHMARK_2026-10-24_PL.md). Kandydat `granite4:1b` (Granite 4 1B) jest testowany jako lekki router AI Platform. W produkcji nie działa żaden zaakceptowany nowy model routera. Istniejące BGE-M3 służy Knowledge Service do embeddingów.

Trzy zadania: (1) powtórzyć pełny 51-case benchmark, (2) sprawdzić zasadę wymagającą `knowledge.search` i prompt doprecyzowujący wielonarzędziowe `graphify`/`vision`, (3) wykonać fizyczny test obu modeli na RTX 5060 Ti bez naruszania produkcji.

Dane i kontrakt: `golden.v1.jsonl` 51 przypadków, SHA-256 `1f829de1eacdd8e19905e28f2d086161f94fd93c691bee586d6171976d0f8edf`; 23 DEV, 15 holdout, 13 challenge; klasy silnie niezrównoważone (41/51 = knowledge_rag). Baza promptu SHA-256 `6bfa9cc63276f6ecb0ab3442f92c0ade574ec6fea63c70c14c19d73978474c76`, tag modelu Granite 4 1B manifest SHA-256 `668a2ebb71598d50631bf064c1a6e52534c0671d811d3a423aa7faa2f317360d`. Identyczny runtime CUDA/Ollama, temperatura 0, `num_ctx=2048`, `num_predict=128`, zero fine-tuningu.

## 1. Powtarzalność pełnego benchmarku

Wykonano trzy niezależne przebiegi pełnych 51 przypadków na rzeczywistym RTX (przy każdej próbie osobny proces DEV Ollama, model zwolniony i RM lease zwolniony). We wszystkich trzech **51/51 przypadków wygenerowano identyczną trasę i identyczny zestaw narzędzi** — sprawdzono predykcje per ID, nie tylko agregaty.

| Metryka | Wynik we wszystkich trzech przebiegach |
|---|---:|
| Route accuracy | 47/51 = **92,16%** |
| Tool exact | 42/51 = **82,35%** |
| Macro-F1 | **0,8803** |
| False positive rate narzędzi | **0%** |
| GPU peak | **3518 MiB** |

To dowód powtarzalności **w tej konfiguracji i na tych danych**, nie ogólna gwarancja deterministyczności modelu.

## 2. Kalibracja wyboru knowledge.search

Zmiany dotyczyły **wyłącznie tekstu promptu i analizy predykcji w DEV**. Nie zmieniano wag modelu ani plików produkcyjnych. Dwa nowe warianty zawierały ogólne zasady: `knowledge_rag` wymaga `knowledge.search`; dla `graphify` i `vision` dodatkowe `knowledge.search` wybierać tylko, gdy potrzebne są źródłowe fakty; `reasoning` nie może zastępować retrieval brakujących faktów.

**Wybór promptu nastąpił wyłącznie na 23 przypadkach DEV.** Oba warianty uzyskały takie same wyniki; według uprzednio ustalonej kolejności wybrano `contract_v1`.

| Test | Trasy | Dokładny zestaw narzędzi | FPR narzędzi |
|---|---:|---:|---:|
| Prompt bazowy — DEV 23 | 22/23 | 20/23 | 0% |
| `contract_v1` — DEV 23 | **23/23** | **22/23** | 0% |
| `contract_v1` — odłożone holdout+challenge 28 | **26/28** | **23/28** | **7,14%** |

Złączenie predykcji DEV+odłożonych (ten sam `contract_v1` na wszystkich 51 przypadkach), ocenione **oryginalnym scorerem AI Platform**, dało: **49/51 tras = 96,08%, 45/51 kompletów narzędzi = 88,24%, tool FPR 3,92%, macro-F1 0,7959**.

**Uwaga decyzyjna:** lepsza średnia accuracy i tool exact **nie oznaczają bezwarunkowej poprawy**. Macro-F1 obniżył się względem bazowego 0,8803 do 0,7959, a dwa przypadki na odłożonym zbiorze wybrały niepotrzebne narzędzie. Przykłady regresji: `ERS-GOLD-0029` (knowledge_rag -> telemetry) i `ERS-GOLD-0050` (reasoning -> knowledge_rag). Dobry wynik na DEV nie przeszedł konserwatywnego gate na odłożonych danych.

**Bezpieczny wariant do dalszej pracy (OFFLINE, NIE WDROŻONY):** reguła kontraktu „jeżeli model wybrał `knowledge_rag` i nie podał `knowledge.search`, dopisz ten wymagany tool” zastosowana do zapisanych wyjść bazowych. Naprawiła jeden przypadek, nie dodała zbędnych narzędzi i zachowała wszystkie trasy:
- 47/51 = 92,16% route accuracy; 43/51 = 84,31% tool exact; 0% FPR; macro-F1 0,8803.
- To tylko **offline replay** reguły; nie był to nowy benchmark GPU tej kompozycji. Nie rozszerzać reguły automatycznie na każdą trasę `graphify` lub `vision`, bo nie każdy przypadek wymaga RAG.

**Wniosek:** pozostawić bazowy Granite 4 1B z minimalnym, jawnie weryfikowanym kontraktem jako **kandydata DEV**, nie włączać `contract_v1` produkcyjnie tylko ze względu na accuracy. Kolejny test powinien użyć nowych niezależnych próbek rzadkich klas i negatywnych przykładów niepotrzebnych narzędzi; 28 już wykorzystanych holdout/challenge nie traktować ponownie jako nietkniętych.

## 3. Współrezydencja Granite + produkcyjny BGE-M3 na RTX

Test fizyczny na NVIDIA GeForce RTX 5060 Ti, CUDA, jeden **globalny RM lease** `external` w istniejącym Gateway; heartbeat i zwolnienie ticketu. BGE-M3 wykonywał żądania `/api/embed` **przez produkcyjny Gateway `127.0.0.1:11435`** z nagłówkiem `X-AI-Resource-Lease`. Granite 4 1B wykonywał żądania w niezależnej, krótkotrwałej Ollamie DEV `127.0.0.1:11683`, uruchomionej tylko na czas testu.

| Obserwacja | Wynik |
|---|---|
| BGE-M3 jako jedyny model w RTX | **858 MiB** |
| Oba modele równocześnie rezydentne w VRAM | **4371 MiB** |
| Inferencja Granite z BGE rezydentnym | **PASS** |
| Kolejny embedding BGE przez RM z Granite rezydentnym | **PASS** |
| Maks. różnica między dwoma wektorami BGE, 1024D | **0,0** |
| Wyładowanie Granite przy pozostawieniu BGE | **PASS** |
| Następnie wyładowanie BGE; RM lease released | **PASS** |
| Końcowy RTX idle | **4 MiB** |

Po zakończeniu usługi `ollama`, `ollama-rtx-small`, `ai-gateway`, `ai-bridge`, `comfyui` i `ai-platform-radio` były **active**. Gateway `/health` miał status `ok`, RM: active=0, queued=0, leases=0, recovery_required=false; produkcyjna trasa `rtx_embedding_route` nadal wskazywała BGE-M3; port DEV `11683` zamknięty. W przeglądanym oknie kernela nie znaleziono dopasowanych błędów Xid, PCIe AER ani restartu amdgpu.

**Granica dowodu:** model Granite został uruchomiony w procesie DEV z własnym dostępem CUDA, a rezerwacja RM była kooperacyjna, nie wymuszona przez globalną politykę urządzeń systemowych. Wykonano **naprzemienne żądania z jednoczesną rezydencją modeli**, nie jednoczesne obliczenia dwóch inference jobs. `GPU_REUSE_SAFE=NOT_VERIFIED`, `N1=NOT_ADMITTED` i brak globalnego blokowania bypassów nadal obowiązują.

## Stan oraz artefakty

- **PASS:** powtarzalność 3×51, fakt fizycznej współrezydencji, realna inferencja dwóch modeli, kontrolowane zwolnienie GPU i lease, niezmieniony status produkcji.
- **NOT ACCEPTED:** `contract_v1` jako produkcyjny prompt routera (regresja na odłożonym zbiorze), produkcyjny router, niezależne równoległe przydzielanie dwóch GPU, OS-wide izolacja, długotrwała stabilność.
- **Rekomendacja:** Granite 4 1B nadal najlepszym kandydatem. Zachować bazowy prompt jako punkt odniesienia, testować minimalny wymagany `knowledge.search` guard i walidację rzadkich klas na **nowych** danych.

Artefakty na hoście (bez publikowania całych zapytań ECU): `/srv/ai-data/evaluation/router-granite-validation-20261024/` — `runner.log`, trzy `base-repeat-*`, dwa `contract_v*-dev`, `contract_v1-blind-locked`, `RESULT.json`, `granite4-1b-calibrated-full.score.json`, `granite4-1b-invariant-offline.score.json`, `COEXISTENCE_RESULT.json`, `coexistence.log`, pliki testów.

SHA-256:
- `run_validation.py` — `3ef055985c9a7befd8b9e6091a6e8f5ac54b287e964d0ac5ffadd45216018b0b`
- `coexistence.py` — `abc5a4e90ad26718f29a1a5a952a37ce6bd37f9b0d6756f42ce27cac2522f8eb`
- `RESULT.json` — `49bccafdfa9160f86c33850ec3a5a192247e0b15f2ad2d6616072b64152bf4f2`
- `COEXISTENCE_RESULT.json` — `bae678cf3754d85da044e3e0c5b37d34a891536971799ec8ee90258255b1e6d9`
