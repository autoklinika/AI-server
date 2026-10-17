# AnomalyVFM RADIO — analiza wyników 3312 zdjęć (17.10.2026)

**Tryb:** wyłącznie CPU/read-only dla danych źródłowych; bez nowej inferencji GPU, treningu ani modyfikacji produkcji.
**Wejścia:** zamrożony baseline, pełny sealed INFER_PASS, dokładnie 3312 zapisanych predykcji, maski 300 defektów z kontrolą SHA-256.
**Polityka:** progi wybrane wyłącznie na 1001 normalnych zdjęciach PCB2; ocena na PCB3/PCB4 bez dostrajania. Predykcja: score > threshold.

## Wpływ budżetu FPR na wykrywanie

| Budżet FPR na PCB2 | Próg | PCB2 TP/FP | PCB3 TP/FP | PCB4 TP/FP |
|---:|---:|---:|---:|---:|
| 1% | 0.539360 | 37/10 | 16/0 | 30/0 |
| 2% | 0.531673 | 40/20 | 17/0 | 33/0 |
| 5% | 0.516047 | 50/50 | 21/0 | 40/0 |
| 10% | 0.497944 | 59/100 | 32/2 | 50/0 |
| 20% | 0.478200 | 67/200 | 73/90 | 68/2 |
| 30% | 0.463346 | 78/300 | 97/922 | 88/14 |
| 50% | 0.446539 | 89/500 | 100/1006 | 97/248 |

## Diagnostyka progów zapewniających 90–95% recall NA PCB2

Wariant eksploracyjny uwzględnia 100 defektów PCB2 przy wyborze progu. Nie jest to zwalidowany próg produkcyjny.

| Cel recall PCB2 | Próg | PCB2 TP/FP | PCB3 TP/FP | PCB4 TP/FP |
|---:|---:|---:|---:|---:|
| 90% | 0.443568 | 90/541 | 100/1006 | 99/410 |
| 95% | 0.438934 | 95/613 | 100/1006 | 99/707 |

## Lokalizacja na oryginalnych maskach (>0) i mapach 256

| Zbiór | Obrazów z defektem | Średnia w masce > tło | Pik maksimum w masce | Mediana precision w top 1% pikseli |
|---|---:|---:|---:|---:|
| calibration | 100 | 100 | 55 | 19.59% |
| holdout | 100 | 100 | 21 | 4.12% |
| challenge | 100 | 100 | 70 | 51.37% |

## Porównanie metryk zamrożonych pełnych testów

| Model | PCB3 image AUROC/AP | PCB4 image AUROC/AP | PCB3 Pixel AUROC/AP | PCB4 Pixel AUROC/AP |
|---|---|---|---|---|
| B1_WinCLIP | 0.5895 / 0.1683 | 0.8631 / 0.5018 | 0.7593 / 0.0020 | 0.9354 / 0.0445 |
| B2_AnomalyCLIP | 0.6444 / 0.2794 | 0.9401 / 0.7716 | 0.8858 / 0.0145 | 0.9646 / 0.2199 |
| AnomalyVFM RADIO | 0.8664 / 0.6817 | 0.9795 / 0.9308 | 0.9217 / 0.0244 | 0.9838 / 0.3984 |

## Zastrzeżenia
- Dane VisA PCB2, PCB3 i PCB4 są różnymi rodzinami: wynik zależy od przenoszenia rozkładu punktacji i nie jest miarą osiągów na Sony A6100 / rzeczywistych ECU.
- Pixel AUROC bywa wysoki przy bardzo rzadkich defektach; sprawdzaj Pixel AP i lokalizację, nie sam AUROC.
- Żaden próg nie został wybrany na PCB3/PCB4. Oglądanie wyników tych zbiorów może zanieczyścić przyszłe badanie, dlatego kolejna walidacja wymaga nowego niezależnego zestawu.
- Porównanie między modelami ma identyczne zbiory, ale nieidentyczne surowe skale score i inne faktyczne FPR, więc liczby TP/FP porównywać łącznie, nie bez warunków.
- Oryginalny scorer nadal BLOCKED; niezależna poprawiona ocena CPU i ten raport nie zmieniają jego statusu.
- Wybrane przypadki i metryki per-label zapisano w JSON. Zasady progów 90–95% pochodzą z wykorzystaniem pozytywnych etykiet PCB2, tylko eksploracyjnie.
