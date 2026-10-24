# AI Platform — Granite 4 1B: nowe przypadki i dobór narzędzi (RTX, DEV)

**Data:** 2026-10-24 (CEST)  
**Status:** **DEV wykonany, produkcja bez zmian; gate do automatycznego routingu = NOT_READY.**  
**Kandydat:** `granite4:1b`, NVIDIA GeForce RTX 5060 Ti 16 GB, Ollama CUDA.

## Cel i dane

Po potwierdzeniu powtarzalności 3 × 51 i współrezydencji z BGE-M3 wykonano osobny test doboru narzędzi na **48 nowo napisanych scenariuszach**: po 8 pytań dla `knowledge_rag`, `graphify`, `vision`, `telemetry`, `reasoning`, `tool`; 33 PL i 15 EN. Są to ręcznie oznaczone scenariusze polityk, **a nie niezależnie zweryfikowane historyczne przypadki z produkcji**. Pytania nie powtarzają literalnie pytań wcześniejszego goldena (SHA-256 `1f829de1...`). Dane testowe przechowywane tylko na NVMe, bez publikowania surowych zadań.

Zamrożona nowa paczka: `/srv/ai-data/evaluation/router-granite-validation-20261024/new-48-policy-challenge.jsonl`, SHA-256 `e6fee1d8a8998918d042b0278cfbf989b7de66ec8a4bd939a606a5f6c7abc571`.

Benchmark uruchamiano w **osobnej, tymczasowej instancji Ollamy** na `127.0.0.1:11682` (wariant dwuetapowy: `:11684`), z jedną rezerwacją istniejącego RM, heartbeat i zwolnieniem lease po każdym przebiegu. Żadna usługa produkcyjna nie była restartowana ani rekonfigurowana.

## Wyniki

| Wariant | Trafność tras | Macro-F1 | Poprawny zestaw narzędzi | Zbędne narzędzia | Niezamówione wywołania agenta |
|---|---:|---:|---:|---:|---:|
| Bazowy prompt, jeden krok | **45/48 (93,75%)** | **0,9386** | 37/48 (77,08%) | 3 | 0 |
| Wcześniejszy `contract_v1`, jeden krok | **45/48 (93,75%)** | 0,9373 | 40/48 (83,33%) | 3 | 0 |
| **Dwa kroki: trasa + ocena potrzeb danych** | **45/48 (93,75%)** | **0,9386** | **45/48 (93,75%)** | **3** | **0** |

Dwuetapowe podejście:
1. Granite wybiera trasę według zamrożonego promptu bazowego.
2. Z kontraktu wynika obowiązkowe narzędzie główne dla danej trasy. **Tylko dla Graphify i Vision** wykonuje się drugie krótkie zapytanie Granite z dwoma niezależnymi polami boolean: `knowledge_search` oraz `telemetry_read`. Model odpowiada na podstawie treści żądania i wybranej trasy, **bez dostępu do etykiet oczekiwanych**. Test: 17 dodatkowych odpowiedzi klasyfikacyjnych na 48 żądań.

Dwuetapowy wariant: p50 ok. **238,8 ms**, p95 ok. **431,2 ms** (odczyty w lokalnym DEV, obejmują kolejny krok tam, gdzie był potrzebny), najwyższa obserwowana zajętość RTX **3518 MiB**. Brak błędów kontraktu wynikowego.

**Słabość główna została zawężona:** dzięki rozdzieleniu klasyfikacji trasy od decyzji o dodatkowych danych, poprawny zestaw narzędzi wzrósł z 37 do 45. Pozostałe trzy pomyłki wynikają z **błędnego wyboru trasy głównej**, a nie z niedoboru dodatkowych narzędzi:
- `NEW-K05` — błędnie uruchomiony tor grafowy przy pytaniu o dokumentację;
- `NEW-T06` — błędnie wybrany tor wiedzy zamiast odczytu aktualnego stanu;
- `NEW-R07` — błędnie wybrany tor wiedzy przy problemie rozwiązywalnym z danych wejściowych.

Wszystkie trzy niepotrzebne narzędzia były odczytowe lub analityczne; **nie odnotowano samowolnej delegacji do ERS**. To nadal nie uprawnia do uruchamiania narzędzi bez dalszej walidacji.

## Gate i decyzja

Przed testem założono: co najmniej 90% trafności tras, 90% dokładności narzędzi, Macro-F1 co najmniej 0,90, co najmniej 6/8 trafnych tras w każdej klasie, brak błędów kontraktu oraz **zero zbędnych narzędzi**.

Dwuetapowy wariant spełnił wszystkie prócz ostatniego warunku: **3 zbędne narzędzia**. Formalny gate: **NOT_READY**. Nie uruchamiano go w produkcyjnym routingu ani nie zmieniano wag modelu.

**Rekomendacja:** zachować Granite 4 1B jako kandydat i dwuetapową selekcję narzędzi jako wariant DEV. Kolejnym etapem nie powinno być już rozbudowywanie promptu na tych samych 48 przypadkach, lecz niezależna recenzja etykiet, nowe przypadki dotyczące błędów tras oraz kontrolowany **shadow mode** (decyzje logowane, **bez wykonywania narzędzi**). Konieczne jest oddzielenie niepewności klasyfikacji od autoryzacji wykonania i jawne potwierdzanie delegacji do agenta. Żaden z wyników nie dowodzi OS-level izolacji GPU ani przyznania N1: `GPU_REUSE_SAFE=NOT_VERIFIED`, `N1=NOT_ADMITTED`.

## Końcowy stan produkcji i artefakty

Po testach: `ollama`, `ollama-rtx-small`, `ai-gateway`, `ai-bridge`, `comfyui`, `ai-platform-radio` **active**; Gateway health **ok**, RM `active=0`, `queued=0`, `leases=0`, `recovery_required=false`; BGE-M3 nadal skierowane na RTX; proces DEV zamknięty i porty DEV wolne; RTX idle 4 MiB; w sprawdzonym fragmencie logu kernela nie odnotowano dopasowanych błędów Xid/AER.

Artefakty lokalne: `/srv/ai-data/evaluation/router-granite-validation-20261024/`. Raporty wynikowe:
- `novel-run/FINAL_NEW48_ANALYSIS.json`, SHA-256 `f7104795ac9f65e60c409af8b0ffceaadb9083d0c3ae5896ec1a60edcb626`;
- `novel-v1-run/FINAL_NEW48_ANALYSIS.json`, SHA-256 `6eb1a5fd9d3847306c3141032566f031511d22250dfef25f908b48726a460be9`;
- `novel-two-pass-run/FINAL_NEW48_ANALYSIS.json`, SHA-256 `b212a18a6015871d66db901a6f083fa4955a2e6c89853794d1d5ecbbb3a0d00e`.

Powiązanie: [Benchmark 51-case](ROUTER_RTX_DECISION_BENCHMARK_2026-10-24_PL.md) oraz [poprzednia walidacja Granite/BGE](ROUTER_GRANITE1B_RTX_BGE_VALIDATION_2026-10-24_PL.md).
