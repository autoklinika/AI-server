# Vision PCB — wyniki benchmarków i analiz modeli (stan 17.10.2026)

## Metodologia i pochodzenie wyników

Zbiory VisA: `PCB2/calibration` = 1101 zdjęć (1001 poprawnych, 100 wadliwych), `PCB3/holdout` = 1106 (1006+100), `PCB4/challenge` = 1105 (1005+100). Łącznie **3312 zdjęć**. Zbiór PCB1 wykorzystywano do uczenia tam, gdzie architektura wymagała treningu; nie wchodził do 3312 zdjęć testowych RADIO.

RADIO: oryginalny zero-shot AnomalyVFM na enkoderze RADIO, wejście 768×768, mapy float32 768×768, GPU Radeon 890M ROCm 7.14.1, **3312/3312 inferencji GPU PASS w 138/138 partiach**, bez nowego treningu i zmian produkcyjnych. Mediana pilotażowa na małych próbach ok. 3,06 s/zdjęcie, nie traktować jej jako gwarantowanego SLA.

Pierwotny scorer CPU miał stan `BLOCKED`: maski VisA zawierają identyfikatory 0–7, a nie tylko binarne 0 i 1. Poprawna maska `0=tło, >0=defekt`. Oddzielny scorer `eval_mask_union_v1` wykonał poprawioną ocenę CPU **PASS** bez modyfikowania historycznego przebiegu, checkpointu lub surowych predykcji. Pixel AUROC/AP dla map skalowanych do 256×256.

## Pełne wyniki RADIO

| Metryka | PCB2 calibration | PCB3 holdout | PCB4 challenge |
|---|---:|---:|---:|
| Liczba zdjęć | 1101 | 1106 | 1105 |
| Image AUROC | 0.838332 | 0.866352 | 0.979458 |
| Image AP | 0.547748 | 0.681669 | 0.930813 |
| TP / FP | 50 / 50 | 21 / 0 | 40 / 0 |
| FN | 50 | 79 | 60 |
| Pixel AUROC 256 | 0.973115 | 0.921679 | 0.983753 |
| Pixel AP 256 | 0.222320 | 0.024419 | 0.398423 |
| Przybliżony AU-PRO 256 | 0.926620 | 0.773232 | 0.913491 |

Próg Image Score: **0.5160471796989442**, ustalony **wyłącznie** na 1001 poprawnych PCB2 dla docelowego FPR 5%. AUROC ocenia ranking, a nie skuteczność detekcji przy tym progu. Recall na PCB3 = **21%**, PCB4 = **40%**, zatem obecnie **FAIL** jako autonomiczny produkcyjny detektor nieznanych ECU.

### Test progów (wybór na samych poprawnych PCB2)

| Budżet FPR na PCB2 | Próg | PCB2 TP/FP | PCB3 TP/FP | PCB4 TP/FP |
|---:|---:|---:|---:|---:|
| 1% | 0.539360 | 37/10 | 16/0 | 30/0 |
| 2% | 0.531673 | 40/20 | 17/0 | 33/0 |
| 5% | 0.516047 | 50/50 | 21/0 | 40/0 |
| 10% | 0.497944 | 59/100 | 32/2 | 50/0 |
| 20% | 0.478200 | 67/200 | 73/90 | 68/2 |
| 30% | 0.463346 | 78/300 | 97/922 | 88/14 |
| 50% | 0.446539 | 89/500 | 100/1006 | 97/248 |

Dodatkowy **eksploracyjny** eksperyment używający również pozytywnych etykiet PCB2: progi spełniające 90% i 95% recall na PCB2 dały na PCB3 odpowiednio 100/100 TP i **1006 FP**, a na PCB4 99/100 TP i 410 FP lub 707 FP. Te progi **nie są dopuszczone do produkcji**.

Mediana score (poprawne / defekt): PCB2 0.44654 / 0.51648; PCB3 0.47033 / 0.48811; PCB4 0.44220 / 0.49715. Przesunięcie rozkładów tłumaczy niestabilność wspólnej kalibracji.

### Lokalizacja i rodzaje uszkodzeń

W 300/300 masek średnia punktacja w obszarze defektu była wyższa niż na tle, ale najwyżej punktowany piksel znalazł się **w rzeczywistym defekcie** tylko w 55/100 PCB2, 21/100 PCB3 i 70/100 PCB4. Mediana precision w 1% pikseli o najwyższych wynikach: 19.59% / 4.12% / 51.37%.

Przy oryginalnym progu: PCB3 — brakujące elementy 0/20, wygięcia 1/20, rysy 4/25, nadtopienia 17/43. PCB4 — brakujące 7/33, nieprawidłowe położenie 1/13, przypalenia 7/8. Zbiory mogą zawierać etykiety wielokrotne.

### Niezależne potwierdzenie

5/5 testów jednostkowych analizy progowania PASS. 3312 rekordy inferencji zweryfikowane, 300 masek i mapy użyte do analiz lokalizacji sprawdzone SHA. Image AUROC/AP policzone ponownie przez sklearn — zgodność z poprawionym raportem do 1e-12. Status pierwotnego scorera `BLOCKED` pozostaje historycznie niezmieniony.

## Porównanie z pozostałymi modelami

Pełne benchmarki na tych samych dwóch rodzinach VisA:

| Model | PCB3 Image AUROC / AP | PCB4 Image AUROC / AP | PCB3 Pixel AUROC / AP | PCB4 Pixel AUROC / AP |
|---|---|---|---|---|
| **RADIO** | **0.8664 / 0.6817** | **0.9795 / 0.9308** | **0.9217 / 0.0244** | **0.9838 / 0.3984** |
| AnomalyCLIP | 0.6444 / 0.2794 | 0.9401 / 0.7716 | 0.8858 / 0.0145 | 0.9646 / 0.2199 |
| WinCLIP | 0.5895 / 0.1683 | 0.8631 / 0.5018 | 0.7593 / 0.0020 | 0.9354 / 0.0445 |

PatchCore B3: **przerwany przez użytkownika przy 3020/3312**, PCB3 0.4023 Image AUROC (1106), PCB4 0.5198 (obcięte 813/1105). Dane PCB4 nie w pełni porównywalne. Przy dostępnej częściowej ocenie PatchCore uzyskał słabą skuteczność i wysoki koszt obliczeniowy.

### Pilotaże na 32 zdjęciach: ostrożna interpretacja

PCB2 8 normalnych + 8 uszkodzonych; PCB3 i PCB4 po 4 normalne + 4 uszkodzone. Mały, nielosowy zbiór, testy statystycznie niestabilne. Nie mieszać ich metryk z pełnym benchmarkiem.

| Model | PCB2 Image AUROC | PCB3 Image AUROC | PCB4 Image AUROC | Mediana inferencji |
|---|---:|---:|---:|---:|
| RADIO | 0.8594 | 1.0000 | 1.0000 | 3.063 s |
| AnomalyVFM DINOv3 | 0.5781 | 0.7500 | 1.0000 | 1.835 s |
| GeneralAD | 0.5156 | 0.0000 | 0.3750 | 0.072 s |

DINOv3: oficjalny checkpoint autora, wejście 768, ViT-L/16 DoRA, 32/32 GPU PASS, jakościowo słabszy od RADIO na tej małej próbie. GeneralAD: **inny budżet i tryb** — ViT-S/14 DINOv2, wejście 392, 96 poprawnych PCB1 na trening, jedna krótka epoka, potem 32/32 inferencji PASS; test wykazał słabą jakość tej konfiguracji, **nie jest rozstrzygającą oceną pełnej architektury GeneralAD**. Mały pilotaż MiniCPM-V 4.7 1B oraz Qwen3-VL 8B: decyzje tekstowe nie rozpoznały żadnego z 4 przykładów uszkodzeń na PCB2 (0/4), lecz nie wykonano pełnego AUROC/AP ani benchmarku detekcji dla tych modeli.

## Wniosek

Na podstawie obecnych pomiarów wybrano **AnomalyVFM RADIO do późniejszej specjalizacji**, nie do wdrożenia. Dalsza praca powinna skupić się na danych i kalibracji dla nowych ECU, zwiększaniu recall bez dużego FPR i lokalizacji brakujących drobnych elementów.

**Dane źródłowe:** lokalne raporty `/srv/ai-data/evaluation/vision-pcb-envs/anomalyvfm-radio-full-20261016/eval_mask_union_v1/RESULTS_PL.md` oraz `.../posthoc_analysis_20261017/RESULTS.json`, raport pilotażu DINOv3 i GeneralAD z 17.10.2026 (ich dedykowane katalogi usunięto po zabezpieczeniu liczb w niniejszej dokumentacji). Nie przeniesiono wielogigabajtowych obrazów ani map na GitHub.
