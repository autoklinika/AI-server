# B1 — WinCLIP: pilot porównania global vs tile640 (2026-10-13)

**Status: PILOT TECHNICZNY PASS / nie służy do rankingu modeli.**

## Protokół

- Jednoznacznie wybrana podpróba z istniejącego pilota VisA fold_0, 14 obrazów w manifeście: train=2 normal, calibration=2 normal+2 anomaly, holdout=2+2, challenge=2+2. Inferencja tylko na 12 obrazach splitów calibration/holdout/challenge.
- Ten sam checkpoint WinCLIP `ViT-B-16-plus-240/laion400m_e31`, prompt `printed circuit board`, CPU PyTorch 2.10, Anomalib 2.7, **2 wątki**.
- Wariant global: skala całego obrazu do modelowego wejścia 240×240 przez jego transformację.
- Wariant tiled: ten sam global image score + 6 kafelków 640×640 z nakładaniem 25% (dla każdej z dwunastu próbek); wynik obrazu = MAX(global, kafelki).
- Kafelków nie interpretujemy jako maski regionów. `localization_mode: none`.
- **Osobne progi z poprawnych obrazów calibration**, ustawione na FPR <= 5% w tej malutkiej próbce.
- Dla obu trybów pełna walidacja plików, hash, kompletność predykcji i dowód kalibracji: PASS.
- Wyniki dla N=4 obrazów na każdy split są **niestabilne statystycznie**.

## Metryki z rzeczywistej inferencji

| Metryka | holdout/global (PCB3) | holdout/tiled (PCB3) | challenge/global (PCB4) | challenge/tiled (PCB4) |
|---|---:|---:|---:|---:|
| AUROC | 0.25 | 0.75 | 1.00 | 0.75 |
| AP | 0.50 | 0.8333 | 1.00 | 0.8333 |
| Recall | 0.50 | 0.00 | 1.00 | 1.00 |
| FPR | 1.00 | 0.00 | 0.50 | 0.50 |
| TP | 1 | 0 | 2 | 2 |
| FP | 2 | 0 | 1 | 1 |
| FN | 1 | 2 | 0 | 0 |

Próg global=0.41071057; próg tiled=0.51234448. Progi nie mogą być porównywane wprost, ponieważ score po agregacji maksimum zmienia rozkład. Wynik tiled dla normalnego obrazu calibration osiągnął 0.51234, przewyższając wyniki obu uszkodzonych obrazów tej części. To pokazuje ryzyko false positives i niestabilności kalibracji. Liczba 2 poprawnych obrazów użytych do ustawienia progu nie pozwala oszacować FPR=5% w populacji.

**Nie przyznajemy PASS/FAIL dla jakości anomalii na podstawie tych wyników.** Powinniśmy ocenić full B1 na co najmniej jednym kompletnym foldzie i porównać m.in. max, top-k, obszary heatmap oraz odpowiednie progi.

## Artifacts

Wszystkie obrazy, predykcje, raporty, niezależne thresholdy, lista tile rectangles i metadane eksperymentu są wyłącznie na dysku NVMe AI Platform:
`/srv/ai-data/evaluation/vision-pcb-datasets/visa-20220922/paired_tile_640_p2`.

Repo GitHub zawiera wersjonowane skrypty oraz ten raport bez obrazów i niezmienionych datasetów.

## Następne pomiary

- Pełne splitowe dane VisA, porównanie bez przecieku.
- Pixel AUPRO i mapy anomalii (oddzielny silnik, obecnie N/A).
- Warianty agregacji (w tym top-k i ocena regionów), kalibrowane na poprawnych danych.
- Osobny raport jakościowy opisów MiniCPM z ręcznym zaznaczaniem niepopartych twierdzeń.
