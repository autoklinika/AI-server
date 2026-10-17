# AnomalyVFM RADIO — 16-zdjęciowy pilotaż PCB2, 2026-10-16

**16/16 próbek GPU PASS**. Bez zmian produkcji. Mapy 768 × 768 zapisane wraz z SHA-256.

## Porównanie rankingowe na dokładnie tych samych 16 zdjęciach
| Model | AUROC (eksploracyjne) | AP (eksploracyjne) |
|---|---:|---:|
| AnomalyVFM RADIO | 0.8594 | 0.8137 |
| WinCLIP B1 | 0.7812 | 0.7872 |
| AnomalyCLIP B2 | 0.6875 | 0.8022 |

**To nie są wyniki niezależnego benchmarku!** Próbki pochodzą z PCB2/calibration, nie PCB3/holdout ani PCB4/challenge. Tylko 8 normalnych i 8 defektów, wybranych nielosowo.
Mediana inferencji GPU 3.06 s; maksymalna rezerwacja pamięci PyTorch 2.29 GiB, RSS 3.73 GiB.

## Zgodność map anomalii z maskami
Pixel AUROC (agregat 16 obrazów): 0.9949; pixel AP: 0.2130.
Liczba defektów z wyższą średnią punktacją wewnątrz maski: 8/8.
Te wartości są eksploracyjne; na tak małym zbiorze i po przeskalowaniu maski nie dowodzą jakości lokalizacji dla nowych PCB.

## Ocena

Warunek przejścia do większego benchmarku: wyniki na niezależnym PCB3/PCB4, stabilność bez awarii MES, fałszywe alarmy po progu z 1001 normalnych PCB2 i pixel AUROC / AU-PRO.

## Artefakty
Model RADIO checkpoint pinned i SHA w weights_lock.json; każdy worker pod istniejącym guardem. Wszystkie 16 map oraz rekordy w records/. Pełne metryki w pilot_16_exploratory.json.
# AnomalyVFM RADIO — pilot PCB3 i PCB4 (16 zdjęć)

**Ukończono 16/16 niezależnych zdjęć (PCB3 holdout oraz PCB4 challenge).**

| Zbiór | Model | AUROC, n=8* | AP, n=8* |
|---|---|---:|---:|
| PCB3 | AnomalyVFM RADIO | 1.0000 | 1.0000 |
| PCB3 | WinCLIP B1 | 0.6875 | 0.8125 |
| PCB3 | AnomalyCLIP B2 | 0.8750 | 0.9167 |
| PCB4 | AnomalyVFM RADIO | 1.0000 | 1.0000 |
| PCB4 | WinCLIP B1 | 0.8750 | 0.9167 |
| PCB4 | AnomalyCLIP B2 | 1.0000 | 1.0000 |

*Tylko 4 poprawne i 4 uszkodzone zdjęcia na rodzinę, wybrane kolejno. To NIE są pełne benchmarki ani stabilne estymacje jakości.*

| Zbiór | Pixel AUROC (n=8) | Pixel AP | Defekt mocniejszy niż tło | Mediana GPU |
|---|---:|---:|---:|---:|
| PCB3 | 0.9714 | 0.0703 | 4/4 | 3.06 s |
| PCB4 | 0.9962 | 0.7688 | 4/4 | 3.06 s |

Model testowany w oryginalnej, nieprzetrenowanej konfiguracji zero-shot z obrazem 768x768.
Pełny próg decyzji wymaga kalibracji tylko na PCB2 (1001 normalnych zdjęć).
Szczegóły map, próbek i SHA w `pilot_crossfamily_16_exploratory.json`.
