# B1 WinCLIP — checkpoint i przegląd błędów (2026-10-13)

**Status: NONFINAL CHECKPOINT**, wyniki podane dla 240 wybranych wcześniej ukończonych obrazów. To nie są wyniki pełnego B1 ani podstawy do decyzji produkcyjnej.

## Reproducibility

- Źródło: VisA_20220922.tar SHA256 2eb8690c803ab37de0324772964100169ec8ba1fa3f7e94291c9ca673f40f362.
- Podstawowy fold0: calibration PCB2, holdout PCB3, challenge PCB4.
- Punkt kontrolny wzięty z zapisanych, integralnych rekordów pełnego przebiegu (odczyt pełnych SHA256 map oraz oryginałów).
- Dobór **40 normal i 40 anomaly na split**, deterministyczny po rosnącym sample_id z już ukończonych rekordów. **Nielosowy, zależny od kolejności katalogu**; nie wolno wnioskować o populacyjnej skuteczności.
- Ogółem 240 obrazów; 80 calibration, 80 holdout, 80 challenge. Progowy target FPR 0.05 wyłącznie ze zbioru 40 normalnych w calibration.
- Próg kalibracyjny: 0.42093813419342047.
- Zamrożone manifesty, predykcje, progi i raporty: NVMe AI Platform, katalog b1_checkpoint_20261013_n240. Do GitHub tylko tekstowe podsumowanie.

## Image-level results

| Metryka | PCB3 holdout | PCB4 challenge |
|---|---:|---:|
| AUROC | 0.51875 | 0.91750 |
| Average Precision | 0.601305 | 0.912051 |
| Recall | 14/40 = 0.35 | 34/40 = 0.85 |
| FPR | 14/40 = 0.35 | 8/40 = 0.20 |
| False negatives | 26 | 6 |

Odczyt: występuje duża zmienność jakości między rodzinami. Użycie jednej wartości 0.42094 jako uniwersalnego progu na dowolnym ECU byłoby nieuzasadnione. Bezpośrednie eksperymenty na niezmontowanych i zmontowanych PCB to różne zadania, których nie należy mieszać.

## Ręczna inspekcja czterech przykładów

Zdjęcia i maski oryginalne pozostają na NVMe; ocena wizualna nie stanowi niezależnego potwierdzenia elektrycznej usterki.

1. **False positive:** visa-pcb3-normal-0020, score 0.43106 > threshold. W obrazie widać moduł czujnikowy z dwoma elementami optycznymi ustawionymi na końcu płytki; na podstawie zdjęcia nie widać oczywistego złamania czy przewodu. Powód alarmu modelu pozostaje nieznany.
2. **False negative:** visa-pcb3-anomaly-001, score 0.39892 < threshold; oficjalna etykieta *bent*. Widoczny dolny czarny element optyczny jest wygięty/wyprowadzony pod kątem i nachodzi na dolną część płytki zamiast pozostawać w osi pierwotnego montażu. Model pominął odchylenie geometryczne.
3. **False positive:** visa-pcb4-normal-0026, score 0.43989 > threshold. Na zdjęciu widoczne elementy przetwornicy oraz mikro-USB, bez ewidentnego błędu; model może reagować na wygląd innego wariantu PCB, ale nie jest to udowodniona przyczyna.
4. **False negative:** visa-pcb4-anomaly-037, score 0.41629 < threshold; oficjalna etykieta *extra,dirt*. Wyraźnie widać dodatkowy drut lub metalową część leżącą ukośnie przy wejściu IN+ i obszarze złącza USB. Model nie wykrył tej anomalii przy analizie całego obrazu.

Te przykłady pokazują, że same obrazy poprawne/niepoprawne to za mało: model musi podać dowód w postaci lokalizacji i rodzaju uszkodzenia, a w przypadku niepewności poprawnie odmówić rozstrzygnięcia.

## Pozostałe bramki

1. Wszystkie 3312 oceniane obrazy folderu fold0 muszą uzyskać predykcje i zapisane mapy.
2. Scorer wymaga kompletnych plików (nie akceptuje brakujących wierszy). Wstępny 240-obrazo-wy checkpoint nie zastępuje pełnego scoringu.
3. Pixel AUROC/AP i przybliżony AUPRO 256×256 (nie oficjalna metryka pełnej rozdzielczości).
4. Ocena MiniCPM i PatchCore w osobnych, możliwych do porównania zadaniach; nie wolno wytworzyć fikcyjnego prawdopodobieństwa z tekstu MiniCPM.
5. Brak merge do main i brak model promotion bez decyzji właściciela.
