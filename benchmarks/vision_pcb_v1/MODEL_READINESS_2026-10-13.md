# Vision PCB — MODEL-01 / warunki inferencji (2026-10-13)

## Rozstrzygnięcia zweryfikowane na hoście

| Element | Status |
|---|---|
| VisA archiwum, hash oficjalny | PASS |
| 4 manifesty cross-family, check-files | PASS |
| CPU WinCLIP w izolowanej venv Python3.11 | PASS |
| PyTorch 2.10.0+cpu / torchvision 0.25.0+cpu | PASS |
| Anomalib 2.7.0 / OpenCLIP 2.24.0 | PASS |
| Checkpoint ViT-B-16-plus-240 laion400m_e31 | pobrany, SHA256 zweryfikowany, kopia na NVMe |
| WinCLIP smoke 2 obrazy | PASS |
| WinCLIP B1 pilot 48 inferencji i kalibracja/scoring | PASS, eksperymentalny |
| Docelowy pełny B1 dla 7 kandydatów | NIEZREALIZOWANY |
| Licencja wag/produkcja komercyjna | audyt otwarty |
| Dostępne GPU | AMD Radeon 890M przez Vulkan; PyTorch GPU bez weryfikacji |
| Pozostałe modele VLM, PatchCore, YOLO | NIEZAINSTALOWANE |

Produkcja AI Platform pozostaje na Qwen3.8 z dotychczasowymi adapterami. Żadne usługi nie zostały zatrzymane ani przełączone. Nie wprowadzono zmian GPU.

## Następne kroki

1. Zaprojektować stabilny adapter predykcji WinCLIP dla pełnego zbioru i politykę kafelkowania zdjęć wysokiej rozdzielczości (aktualnie CLIP 240×240).
2. Sprawdzić dostępność niezależnego backendu AMD i Resource Manager AI Platform, zanim uruchomimy masowe inferencje.
3. Następnie przygotować PatchCore i MiniCPM-V, z rozdzieleniem kosztu pamięci i metryk.
4. Zrealizować pełne B1/B2/B3 oraz ręczny przegląd pominiętych defektów.
