# AnomalyVFM RADIO — pełna ocena CPU po korekcie binarizacji masek
Data: 2026-10-17. **Inferencja GPU: 3312/3312, 138/138 partii PASS.** Pierwotny, zamrożony scorer zakończył się BLOCKED; nie modyfikowano tego przebiegu.
Problem: oryginalne maski VisA zawierają identyfikatory klas 0–7, nie tylko 0/1. Poprawna binarizacja: `0 = tło; >0 = defekt`. Wszystkie 300 masek PCB2/3/4 mają dodatnie piksele, również po resize 256x256.
Ocenę przeprowadzono odrębnym scorerem w `eval_mask_union_v1`, bez ponownej inferencji i bez zmiany plików źródłowych, checkpointu lub progów.

| Metryka | PCB2 calibration 1101 | PCB3 holdout 1106 | PCB4 challenge 1105 |
|---|---:|---:|---:|
| Image AUROC | 0.838332 | 0.866352 | 0.979458 |
| Image AP | 0.547748 | 0.681669 | 0.930813 |
| TP / FP | 50 / 50 | 21 / 0 | 40 / 0 |
| FN | 50 | 79 | 60 |
| Pixel AUROC 256 | 0.973115 | 0.921679 | 0.983753 |
| Pixel AP 256 | 0.222320 | 0.024419 | 0.398423 |
| Przybliżony AU-PRO256 | 0.926620 | 0.773232 | 0.913491 |

Próg image score = `0.5160471796989442`, ustalony tylko z 1001 poprawnych PCB2 przy docelowym FPR 5%. PCB3 i PCB4 nie służyły do strojenia. AUROC jest niezależny od progu, natomiast recall przy tym progu jest niski: 21% PCB3, 40% PCB4. Zero FP na PCB3/PCB4 **nie oznacza**, że model rozpoznaje wszystkie defekty.

Źródła dowodowe: `../run/inference_complete.json`, `calibration.json`, `holdout.json`, `challenge.json`, `provenance.json`. Zamrożony pierwotny przebieg pozostaje BLOCKED, a te raporty mają status PASS jako **oddzielny post-hoc scorer**, nie zastępują pierwotnego `complete.json`.
**Wniosek:** AnomalyVFM jest obiecujący (szczególnie jako model rankingowy i lokalizujący), ale próg decyzyjny i niezależne kryteria wysokiego recall muszą być opracowane na kalibracji przed decyzją produkcyjną.
