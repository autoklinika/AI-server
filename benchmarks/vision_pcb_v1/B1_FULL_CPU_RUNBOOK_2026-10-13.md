# Vision PCB — pełny B1, przebieg WinCLIP/CPU (2026-10-13)

**Status: uruchomiony i wznawialny, NIEUKOŃCZONY.** Dotychczasowe wyniki z 48 obrazów i małych testów kafelkowania pozostają pilotami, a nie oceną produkcyjną.

## Dane

- VisA archiwum SHA-256: 2eb8690c803ab37de0324772964100169ec8ba1fa3f7e94291c9ca673f40f362.
- Fold 0: train PCB1 (1004 normal), calibration PCB2 (1101), holdout PCB3 (1106), challenge PCB4 (1105). Łącznie **3312 zdjęć ocenianych**; 1004 poprawne PCB1 nieużyte przez zero-shot WinCLIP.
- Źródło GT: /srv/ai-data/evaluation/vision-pcb-datasets/visa-20220922/manifests/fold_0.jsonl.
- Model ViT-B-16-plus-240/laion400m_e31, checkpoint SHA256: 8fb26589b9a8bab2e7a683d280e48df89b8e742f3a82132707282620b36facba. Zero-shot, bez referencyjnego obrazu tego samego PCB.
- Stałe preprocessing_mode=global, prompt printed circuit board, CPU PyTorch/Anomalib/OpenCLIP, brak GPU.

## Zasoby, wyłączenia

- Tylko CPU, nice +15, maks. 2 wątki na proces, limit loadavg poniżej 12. Uruchomienia w ograniczonych porcjach (--max-new, --time-budget).
- **Nie ma formalnego zewnętrznego profilu CPU w produkcyjnym Gateway Resource Manager** (external lease obejmuje głównie Ollama i ComfyUI). Nie rezerwujemy fikcyjnego workload GPU ani nie twierdzimy, że zadania CPU są objęte pełnym admission control.
- Zadania pozostają eksperymentalne, ograniczone, z kontrolą obciążenia. Przed ciągłym harmonogramem należy stworzyć CPU admission class lub inny zatwierdzony mechanizm.
- Nie zmieniamy produkcyjnego Qwen3.8, WVC, runtime Ollama ani konfiguracji GPU.

## Odporność na przerwanie

Skrypty b1_journal.py i winclip_b1_resume.py:
- Każdy obraz ma identyfikator, SHA256 oryginału, score, czas i mapę anomalii 256×256 z osobnym SHA256.
- Wynik obrazu zapisywany atomowo na NVMe pod nazwą SHA256 identyfikatora, a wznowienie liczy tylko brakujące.
- Zamrożony config.json zawiera hash GT, checkpoint, wersje frameworków, split, tryb preprocessingu.
- Blokada fcntl.flock wyklucza równoległy zapis do tego samego splitu.
- Odczyty sprawdzają poprawność wpisów i hash map. Przerwane lub zmodyfikowane rekordy blokują dalsze prace.
- predictions.jsonl powstaje **tylko po zakończeniu wszystkich obrazów splitu**, zanim scorer może wykonać finalną ocenę.
- Program kończy porcję po max-new, limicie czasu lub obciążenia hosta. Brak automatycznej promocji.

## Ewaluacja finalna

Po dostarczeniu wszystkich trzech kompletnych splitów:
1. Benchmark validate --check-files i kontrola kompletności.
2. Kalibracja wyłącznie na poprawnych obrazach calibration; zamrożenie progu dla target FPR=5% (na tej próbce, bez gwarancji dla nowej domeny).
3. Benchmark score: holdout/challenge; image AUROC, AP, recall, FPR.
4. pixel_eval_256.py: pixel AUROC, pixel AP, **przybliżony AU-PRO@FPR<=0.3** na mapach 256×256; nie jest to pełnorozdzielczy AUPRO.
5. Ręczna ocena false positives/false negatives i powtórzenie dla kolejnego folda.
6. WinCLIP tiled i PatchCore pod tym samym protokołem; MiniCPM osobny tor, bez wymyślonych prawdopodobieństw z tekstu.

**Uwaga:** w VisA specimen_id jest proxy obrazu; false_alarms_per_pcb ze starego skorera należy odczytywać jako false alarms per image, nie na potwierdzonej fizycznej płytce.
