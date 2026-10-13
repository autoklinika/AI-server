# Vision PCB Benchmark V1 — specyfikacja i wykonywalny scorer

**Status:** benchmark offline + testy kontraktowe; **NIE są wykonane pomiary prawdziwych modeli**. Fixture to dane syntetyczne do testów kodu, nie wyniki jakości PCB. Jest to osobny pakiet w repo `AI-server`, bez zmian produkcyjnego modelu ani usługi VENTUNO.

## Zakres i porównywalność

- **7 kandydatów:** MiniCPM-V 4.7 35B-A3B, MiniCPM-V 4.7 1B, MiniCPM-V 4.6, Qwen3-VL 8B, PatchCore, YOLO, WinCLIP.
- **B1 (zero-shot/bez adaptacji):** VLM i WinCLIP; YOLO jedynie gotowy checkpoint jawnie oznaczony domeną, jeśli dostępny. PatchCore wymaga uczenia reprezentacji na poprawnych PCB — nie podszywa się pod zero-shot.
- **B2 (po specjalizacji):** PatchCore/YOLO/VLM według osobnych receptur, tylko po weryfikacji licencji danych; WinCLIP zachowujemy jako niezmieniony punkt odniesienia.
- **B3 (uogólnienie):** całkowicie nowe rodziny PCB i nowe źródła zdjęć, bez wycieku z treningu lub kalibracji.
- Wszystkie modele otrzymują te same oryginalne obrazy i w razie użycia kafelkowania jawnie wskazaną politykę kafelkowania. Zabronione jest przepuszczanie referencyjnego zdjęcia tego samego DUT do trybu bez wzorca.
- Mierzymy **image AUROC, image AP, recall i FPR przy progu z kalibracji**; detektory udostępniające regiony dodatkowo **region recall, precision, FP/PCB, mean-best-IoU**. Brak obszarów w VLM raportowany jest jako **N/A**, nie sztuczne 0.0. Metryka AUPRO jest **nieobliczana** przez scorer boxów; wymaga oddzielnego silnika masek (np. Anomalib).
- Nie tworzymy jednej zbiorczej „punktacji”, która premiowałaby model niemający lokalizacji albo mieszała AUROC z szybkością. **Osobne tablice wyników** według zadania, datasetu i warunku testowego.

## Manifest i ochrona przed data leakage

Każdy rekord `ground_truth.jsonl` ma pola:

```json
{"sample_id":"my-01", "dataset":"visa-pcb1", "family":"PCB1", "specimen_id":"physical-board-01", "source_id":"original-image-01", "split":"holdout", "label":"anomaly", "sha256":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "image_path":"relative/to/image.png", "regions":[{"class":"corrosion", "box":[0.1,0.2,0.4,0.5]}]}
```

`box=[x1,y1,x2,y2]` we **współrzędnych [0,1]** względem **oryginału**, nie kafelka. `sha256` jest sumą oryginalnego pliku. `source_id` identyfikuje wspólne źródło cropów/augmentacji. `specimen_id` identyfikuje **fizyczną płytkę**. Ta sama płytka, źródło albo identyczny obraz nie mogą wystąpić w różnych splitach. `challenge` wymaga rodzin niewystępujących w żadnym innym splicie. `--check-files` sprawdza pliki, hash oraz brak path traversal.

Splity: `train` (niepunktowany), `calibration` (progi), `holdout` (wewnątrzdomenowy), `challenge` (inne rodziny PCB). Przy porównaniu różnych datasetów wymagamy dodatkowo porównywalności etykiet i protokołu. Przed formalnym benchmarkiem należy udokumentować mapowanie masek/poligonów na bbox, wielkość prób i zależności między zdjęciami.

Każdy rekord `predictions.jsonl` ma:

```json
{"sample_id":"my-01", "model_id":"winclip", "image_score":0.83, "localization_mode":"boxes", "regions":[{"box":[0.1,0.2,0.4,0.5], "score":0.94}]}
```

`image_score` i `regions[*].score` muszą mieć zakres [0,1]. Punktacja wymaga **kompletnych** predykcji dokładnie jednego splitu i modelu. Dla modeli bez uzasadnionej lokalizacji: `"localization_mode":"none", "regions":[]`. Nie wolno konwertować swobodnych tekstowych opisów na „dokładne regiony” bez niezależnego algorytmu.

## Uruchomienie scorer-a (stdlib, Python >=3.11)

```bash
python3 -m unittest discover -s benchmarks/vision_pcb_v1/tests -v
python3 benchmarks/vision_pcb_v1/benchmark.py catalog
python3 benchmarks/vision_pcb_v1/benchmark.py validate \
  --ground-truth benchmarks/vision_pcb_v1/fixtures/ground_truth.jsonl
python3 benchmarks/vision_pcb_v1/benchmark.py calibrate \
  --ground-truth benchmarks/vision_pcb_v1/fixtures/ground_truth.jsonl \
  --predictions benchmarks/vision_pcb_v1/fixtures/winclip_calibration.jsonl \
  --output /tmp/vision_fixture_thresholds.json --max-fpr 0.05
python3 benchmarks/vision_pcb_v1/benchmark.py score \
  --ground-truth benchmarks/vision_pcb_v1/fixtures/ground_truth.jsonl \
  --predictions benchmarks/vision_pcb_v1/fixtures/winclip_holdout.jsonl \
  --thresholds /tmp/vision_fixture_thresholds.json \
  --calibration-predictions benchmarks/vision_pcb_v1/fixtures/winclip_calibration.jsonl \
  --split holdout \
  --output /tmp/vision_fixture_holdout.json
```

CLI kończy działanie z exit=2 przy niepoprawnym datasecie, duplikatach, leakage, niekompletnych predykcjach, zmianie wersji GT między kalibracją a pomiarem oraz próbie nadpisania artefaktu. Progi image-classification pochodzą **wyłącznie** z kalibracji; próg regionów (domyślnie 0.5) i IoU (domyślnie 0.3) są jawnie wpisane do raportu. Dobór ich wartości dla produkcji trzeba zamrozić na zbiorze kalibracyjnym.

## Kryteria techniczne do rozpoczęcia rzeczywistych pomiarów

1. Skontrolowane licencje i pochodzenie zbiorów (patrz `datasets.json`), manifest z SHA-256 obrazów, maskami i groupingiem, identyczny preprocessing.
2. Każdy adapter inferencji (wykonawca osobnego joba) publikuje zapisane predykcje w wyżej opisanym kontrakcie, checkpoint/revision, seed, quantization, wersję kodu i zależności, parametry kafelkowania, czas, peak RAM/VRAM i ewentualne błędy. **Scorer celowo nie uruchamia modeli/GPU**.
3. Heavy jobs wyłącznie przez Resource Manager AI Platform, na izolowanym środowisku/zasobach; nie przez bezpośrednie wywołania produkcyjnego Ollama. Kiedy stabilność GPU jest niepotwierdzona, pracujemy jedynie offline.
4. Dla B3: poza VisA kontrolnie testy na zdjęciach Sony A6100 z nieznanych, fizycznych PCB. Konieczna ręczna ocena false negatives i false positives przez technika.
5. Własna maskowa ewaluacja AUPRO, pełen benchmark latencji i integracja katalogu GUI AI Platform — osobne zadania; **nie są jeszcze dostarczone przez V1**.

## Bramka akceptacyjna

Nie ma automatycznej promocji modelu. Benchmark V1 zatwierdza jedynie poprawność harnessu offline; wybór produkcyjnego modelu wymaga rzeczywistych wyników B1–B3, odrębnego raportu jakości i decyzji właściciela platformy.

**Wymaganie V1.1:** polecenie `score` wymaga również `--calibration-predictions`: sprawdza jego hash i niezależnie przelicza próg. Bez tego dowód kalibracji nie jest kompletny.

## Status DATA-01 i WinCLIP (2026-10-13)

- Zestaw VisA PCB1–PCB4 pobrano na NVMe; SHA256 tar potwierdzono z hashem referencyjnym.
- `fetch_visa.py` umożliwia wznawianie pobierania z kontrolą segmentów i oficjalnego SHA-256.
- `prepare_visa.py` tworzy cztery zamrożone manifesty cross-family z prawdziwych obrazów i masek. Dla importu wymagane `Pillow==12.1.1`, poza głównym scorerem.
- Smoke i pilotaż WinCLIP CPU działają we własnym venv; szczegóły i wyniki **nieprodukcyjne** w `PILOT_WINCLIP_2026-10-13.md`.
- Dane, predykcje i wyniki liczbowe pozostają tylko na NVMe, nie w publicznym GH.
- Uwaga: `specimen_id` w VisA jest proxy obrazu, nie potwierdzonym fizycznym PCB.

## MODEL-01 CPU smoke + tile pilot (2026-10-13)

WinCLIP CPU and MiniCPM-V 4.7 1B CPU passed real-image smoke tests. MiniCPM is not yet calibrated or defect-type validated. A paired high-resolution WinCLIP tile pilot has completed, with different outcomes and separate thresholds for the two preprocessing modes; details in `MODEL_01_CPU_AND_TILING_2026-10-13.md` and `B1_WINCLIP_TILING_PILOT_2026-10-13.md`. No full benchmark or model promotion.

## Full B1: wznawialny scorer i pixel maps (2026-10-13)

Uruchomiono eksperymentalny przebieg wszystkich trzech splitów pełnego fold0 (3312 obrazów); dziennik B1 zapisuje osobno SHA oryginału, image score i mapę 256x256, pozwalając wznowić zadanie bez ponownej inferencji zapisanych obrazów. Nie ukończono pełnego folda, dlatego wynik jest wciąż wstępny. Szczegóły: `B1_FULL_CPU_RUNBOOK_2026-10-13.md` oraz `B1_CHECKPOINT_240_AND_ERROR_REVIEW_2026-10-13.md`. `pixel_eval_256.py` obsługuje pixel AUROC/AP i **przybliżony** AU-PRO256, ale pełny raport wymaga wszystkich obrazów. Zadania są CPU-only z limitem obciążenia, ponieważ RM nie ma jeszcze natywnego profilu zewnętrznych zadań CPU.

## GPU hardware validation (2026-10-13)

Radeon 890M gfx1150, **official ROCm 7.14.1 / PyTorch 2.12.0**, isolated on NVMe, passed matrix/conv smoke; WinCLIP GPU returned scores matching CPU over 50 images (max delta 1.17e-6) with ~3.33x median warm inference speedup. Started a **separate** GPU B1 fold0 journal (24 images per calibration/holdout/challenge) without mixing CPU records. Full GPU B1 is still open. Short manual maintenance leases are NOT a formal provider-specific Vision GPU admission route; no unattended extended GPU workload before an approved Resource Manager integration. Full evidence and security constraints in `GPU_ROCM714_WINCLIP_2026-10-13.md`.
