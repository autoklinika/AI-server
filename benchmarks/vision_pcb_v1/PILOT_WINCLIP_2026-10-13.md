# WinCLIP — realny pilotaż B1 (2026-10-13)

**Status: PILOT PASS (end-to-end scorer), NIE BENCHMARK PRODUKCYJNY.**

## Środowisko i pochodzenie

- AI Platform, izolowane środowisko CPU Python 3.11, **bez konfiguracji GPU ani produkcyjnej Ollamy**.
- PyTorch 2.10.0+cpu, torchvision 0.25.0+cpu, anomalib 2.7.0, open-clip-torch 2.24.0.
- WinCLIP: `ViT-B-16-plus-240 / laion400m_e31`, `k_shot=0`, prompt `printed circuit board`.
- Źródłowy checkpoint OpenCLIP/LAION: `vit_b_16_plus_240-laion400m_e31-8fb26589.pt`.
- **SHA256 checkpointu:** `8fb26589b9a8bab2e7a683d280e48df89b8e742f3a82132707282620b36facba`.
- Kopia wag na NVMe została zweryfikowana bajtowo; wdrożenie komercyjne wymaga osobnej kontroli licencji wag.
- Źródło obrazów: VisA `VisA_20220922.tar`, **SHA256:** `2eb8690c803ab37de0324772964100169ec8ba1fa3f7e94291c9ca673f40f362`.
- Manifest bazowy: `fold_0`, rodzinami: PCB1=train, PCB2=calibration, PCB3=holdout, PCB4=challenge.
- Pilot: pseudolosowe losowanie przy stałym `seed=20261013`; po osiem pozytywnych i osiem negatywnych w każdej z trzech ocenianych części. Łącznie **48 inferencji**, plus 8 normalnych w train nieużytych przez WinCLIP.
- Próg dobrany **wyłącznie na normalnych próbkach kalibracyjnych**: `0.42440235614776617` dla `target_fpr=0.05`. W ośmiu normalnych próbkach kalibracyjnych zero false positives; nie jest to estymacja populacyjnego FPR.

## Rzeczywiste wyniki (N=16 na zbiór!)

| Wskaźnik | PCB3 holdout | PCB4 challenge |
|---|---:|---:|
| AUROC | 0.453125 | 0.78125 |
| Average Precision | 0.619272 | 0.858333 |
| Recall | 2/8 = 25.0% | 7/8 = 87.5% |
| False Positive Rate | 1/8 = 12.5% | 3/8 = 37.5% |
| Precision | 2/3 = 66.7% | 7/10 = 70.0% |
| Uśredniona latencja CPU | 2.75 s/obraz | 2.75 s/obraz |

- Kalibracja: 16 obrazów, 43.67 s; holdout: 16 obrazów, 43.94 s; challenge: 16 obrazów, 43.95 s; **2 wątki CPU**, `nice +15`.
- Lokalizacja: **N/A**, pilot dostarczył tylko image_score, nie udaje niezmierzonych boksów czy masek.
- Kategoria „false alarms per PCB” generowana przez ogólny scorer to w VisA **false alarms per obraz**, bo nie ma identyfikatorów fizycznych egzemplarzy.
- Brak treningu lub LoRA; model używa CLIP przetwarzającego obraz w 240×240, co może uniemożliwiać wykrywanie mikrouszkodzeń przy analizie całej fotografii.

## Interpretacja i następna bramka

1. Dwa obrazy smoke pozwoliły sprawdzić forward pass (normal score `0.4110`, anomaly `0.4423`), a pilot potwierdził `calibrate -> score` na prawdziwych zdjęciach.
2. Wyraźna zmienność między rodzinami: wyniki nie są miarodajnym rankingiem, ale identyfikują ryzyko przenoszenia progu na nową konstrukcję.
3. **Nie promować WinCLIP do produkcji na podstawie 48 próbek.**
4. Pełny B1 wymaga wszystkich obrazów ocenianych, zarejestrowanej polityki skalowania/kafelkowania, oceny pixel AUPRO i porównania wszystkich kandydatów.
5. Dane obrazu, predykcje, progi, metadane i pełne raporty przechowywane **tylko na NVMe AI Platform**; do repo trafia jedynie techniczna synteza.
6. Pilotaż nie ingerował w produkcyjne usługi/adaptery ani w repo Vision.

Runbook: `winclip_cpu_pilot.py` (isolated venv), następnie `benchmark.py calibrate` i `benchmark.py score` z jawnie wymaganym plikiem predykcji kalibracyjnych.
