# Vision PCB — retencja AnomalyVFM RADIO i runbook wznowienia

**Data zamknięcia etapu:** 17.10.2026.
**Status:** model wybrany, benchmarki zakończone, rozwój zamrożony do ukończenia stanowiska Vision.
**Serwer:** AI Platform, dane eksperymentalne na dysku NVMe `/srv/ai-data`.

## Gdzie są zachowane rzeczywiste artefakty?

| Zasób | Ścieżka na serwerze | Uwagi |
|---|---|---|
| Model AnomalyVFM RADIO | `/srv/ai-data/evaluation/vision-pcb-envs/anomalyvfm-radio-pilot-20261016/hf_cache/models--MaticFuc--anomalyvfm_radio/snapshots/17654e763c8fae5ae1c44e2ec421a427783d6196/model.safetensors` | Oryginał, nie nadpisywać |
| Runtime Python/ROCm | `/srv/ai-data/evaluation/vision-pcb-envs/anomalyvfm-radio-rocm714-py311` | Python 3.11, PyTorch 2.12.0+rocm7.14.1 |
| Mały pilot i lock | `/srv/ai-data/evaluation/vision-pcb-envs/anomalyvfm-radio-pilot-20261016` | Oryginalna konfiguracja i raporty |
| Pełny benchmark | `/srv/ai-data/evaluation/vision-pcb-envs/anomalyvfm-radio-full-20261016` | Pełne predykcje, mapy, provenance, wyniki |
| Zamrożone rekordy | `.../anomalyvfm-radio-full-20261016/run` | 3312 rekordów i 3312 map, status inferencji PASS |
| Poprawiona ewaluacja | `.../anomalyvfm-radio-full-20261016/eval_mask_union_v1` | Osobny scorer PASS |
| Progi i analiza błędów | `.../anomalyvfm-radio-full-20261016/posthoc_analysis_20261017` | Rozkłady, metryki, case'y |
| VisA | `/srv/ai-data/evaluation/vision-pcb-datasets/visa-20220922` | Archiwum, rozpakowane zdjęcia i maski, manifesty |
| Ogólny benchmark i Resource Manager | `/srv/ai-data/evaluation/vision-pcb-benchmark-v1-worktree/benchmarks/vision_pcb_v1` | Kod wspólny, guard, scorer i testy |

Dane binarne i obrazy pozostają **wyłącznie lokalnie**, nie umieszczać wielogigabajtowych checkpointów ani zdjęć w GitHub.

## Pin modelu

- Repozytorium checkpointu: `MaticFuc/anomalyvfm_radio`.
- Revision: `17654e763c8fae5ae1c44e2ec421a427783d6196`.
- SHA-256: `50a219ba436ed656ad3c0405f9e81df8ad00b2e715c98be66d7e2edb62a83a37`.
- Rozmiar: **1 421 491 228 bajtów**.
- Manifest VisA fold0 SHA-256: `f206fb2139e705ca8e0945287a69d896e4cdd3578ded9b52853f4658bde0ee2a`.
- Zamrożony benchmark source/baseline zawiera **54 SHA plików źródłowych**. Po translacji dawnej nazwy wirtualnego środowiska na `anomalyvfm-radio-rocm714-py311` zgodność: **54/54 PASS**.
- Historyczne porównanie wymaga dokładnie **5 JSON WinCLIP + 5 JSON AnomalyCLIP**, niezmiennych SHA **10/10 PASS**.
- Oryginalny pełny przebieg inferencji `INFER_PASS`, 3312/3312 zdjęć, 138/138 partii; oryginalny scorer ma `BLOCKED` przez maski wieloklasowe, poprawiony scorer `PASS`. **Nie zmieniać historycznego statusu.**

## Artefakty kontrolne zachowane na NVMe

| Nazwa | Funkcja | SHA-256 |
|---|---|---|
| `SELECTED_MODEL_20261017.json` | Wybrany model, 54 źródła, 10 raportów, lokalizacje | `534aa250e1eccd519935d7ba29025deec91ffd78a58d610d661bd171b271c593` |
| `CLEANUP_AUDIT_20261017.json` | Ścieżki usuniętych modeli i pozostawione wyjątki | `af4fc2d0c330938965a160ea2e1e829326ee819282c1dc5a233078fcd63fcd41` |
| `posthoc_analysis_20261017/RESULTS.json` | Pełne 3312-score, testy FPR i lokalizacji | `a5cd4e35ac33977cf862b1a98ff75ba8eea2453161633d65b53211cfdd2e7f5a` |
| `posthoc_analysis_20261017/RESULTS_PL.md` | Zestawienie wyniku testów | `4dd1a2ee015908eed2aaaa69d46d9345e7535a832b343a4e103fc7f15e960047` |
| `STAN_RADIO_DO_WZNOWIENIA_20261017.md` | Historyczny stan końcowy z NVMe | `8947d27e8b9701a755a30ab98c55f4c34408a8cb71229c3608f7bbdb8c94043e` |
| `POST_CLEANUP_TESTS_20261017.log` | 36 testów ogólnego benchmarku PASS | Lokalny wynik w katalogu RADIO |

**Ważne:** powyższe sumy dotyczą oryginalnych **lokalnych** plików. Na GitHub znajdują się oddzielne, czytelne raporty oraz wybrane kopie dowodów, nie surowe dane obrazowe.

## Zakres sprzątania

Usunięto 58 jawnie wskazanych ścieżek (modele, środowiska, cache, eksperymentalne wyniki, dedykowany kod i logi) oraz usunięto duże katalogi wyników WinCLIP/AnomalyCLIP, pozostawiając tylko 10 przypiętych małych plików wynikowych. W zbiorze VisA pozostawiono archiwum źródłowe, rozpakowane zdjęcia, maski i manifesty; usunięto jedynie modelowe wyniki i pliki tymczasowe. **Odzyskano 30 732 140 544 bajty (ok. 30,7 GB, ~28,6 GiB)** według różnicy użycia systemu plików.

Po operacji pozostałe katalogi w `vision-pcb-envs`: `anomalyvfm-cache`, `anomalyvfm-radio-full-20261016`, `anomalyvfm-radio-pilot-20261016`, `anomalyvfm-radio-rocm714-py311`, `rocm714-test` oraz `anomalyclip-b2-results-20261015` (**wyłącznie 5 małych plików dowodowych**). Analogicznie dla katalogu `b1_full_winclip_gpu_fold0` pozostaje tylko 5 JSON dowodowych.

### Czego nie usuwać

- oryginalnego `model.safetensors` i jego `weights_lock.json`;
- oryginalnego pełnego `run` z mapami i `inference_complete.json`;
- `eval_mask_union_v1`, `posthoc_analysis_20261017`, archiwalnych raportów i ich SHA;
- `VisA_20220922.tar`, `extracted` i `manifests`;
- `ai-vision-gpu-observer`, Resource Manager, guard i wspólnych narzędzi benchmarku;
- **innych projektów**: WVC, ECU Platform, Qwen automotive, Hermes/Ollama, ComfyUI i serwisów produkcyjnych.

Nie usuwać standardowych modułów `anomalib` tylko dlatego, że biblioteka zawiera klasy innych detektorów — mogą być importowane pośrednio. Nie usuwać danych historycznych Git bez osobnego audytu.

## Jak bezpiecznie wznowić prace

**Nie uruchamiać historycznych skryptów wprost** — zapisują nieistniejącą już ścieżkę `patchcore-b3-rocm714-py311`. Nie tworzyć symlinku do tej nazwy w celu obejścia historycznej walidacji ani nie przepisywać starego baseline SHA. To stary, **zamrożony eksperyment**.

1. Ukończyć stanowisko Vision i protokół fotografowania.
2. Zweryfikować po SHA checkpoint, manifest, status 3312/3312 i pliki źródłowe z `SELECTED_MODEL_20261017.json` (uwzględniając translację starego prefixu środowiska).
3. Na oddzielnej, nowej wersji operatora wskazać istniejący runtime `anomalyvfm-radio-rocm714-py311`; nadać mu nowy digest i oddzielny katalog `run`.
4. Na realnym GPU sprawdzić *idle preflight* Gateway / Ollama / ComfyUI, zerowe lease, `recovery_required=false`, brak aktywnych modeli. Korzystać z istniejącego Resource Manager/guarda; zachować wyłączność zasobu i test zwolnienia rezerwacji. Nie dodawać koordynatora.
5. Zrobić pojedynczy smoke GPU i kontrolę mapy, czasu oraz pamięci. Dopiero po PASS wykonać mały test na **nowych** danych Vision, bez dotykania zamrożonego benchmarku.
6. Ewentualne szkolenie LoRA/DoRA prowadzić w całkowicie odrębnym katalogu z własnym dataset lineage i osobną wersją adaptera.
7. Bez ślepego testu i akceptacji jakości **nie wdrażać modelu do produkcji**.

## Dowody pomyślnej kontroli końcowej

- Oryginalne wagi SHA PASS; 54/54 źródła PASS; 10/10 dokumentów porównawczych PASS.
- 3312/3312 rekordów i map obecnych; 36/36 testów wspólnego benchmarku PASS w zachowanym Pythonie 3.11.
- Import RADIO PASS, PyTorch 2.12.0+ROCm7.14.1.
- AI Gateway, AI Bridge i ai-vision-gpu-observer aktywne.
- Jedyny aktywny wpis `models.json`: `anomalyvfm-radio`, `production=false`, `active_for_new_benchmarks=false`.

**Stan:** bez zmian w produkcji i bez automatycznego wznawiania pracy.
