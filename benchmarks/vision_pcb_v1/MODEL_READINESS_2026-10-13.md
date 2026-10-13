# Vision PCB — gotowość do pierwszego przebiegu modeli (2026-10-13)

Odczyty na harrypotter-AI-Series (read-only).

| Obszar | Status |
|---|---|
| Scorer offline | 12/12 testów PASS, syntetyczny manifest 14 próbek PASS |
| Modele MiniCPM, Qwen3-VL, WinCLIP, PatchCore, YOLO | Żaden kandydat nie został zainstalowany na hosta w wykrytych runtime |
| Biblioteki Python | Brak torch, anomalib, ultralytics, transformers w Pythonie systemowym |
| Sprzęt | Radeon 890M/880M PCI 1002:150e; /dev/dri/renderD128; Vulkan 1.4 |
| Pamięć widoczna w systemie | 30 GiB RAM (nie zakładać dostępnych 96 GB UMA) |
| NVMe | /srv/ai-data, około 3.4 TB wolnego |
| Produkcja | ai-gateway i ollama aktywne |
| VisA | HTTP 200, Range 206 dla 1 MiB; pełnego archiwum nie pobrano |

## Warunki pierwszej realnej ewaluacji
- Dane na NVMe, licencja i manifest obrazów z SHA-256.
- Środowisko Python w izolacji; test backendu AMD przed instalacją pakietów GPU.
- Resource Manager musi dopuścić obciążenie. Nie uruchamiać ciężkich procesów przez produkcyjny Ollama.
- Raporty powinny zapisywać wersję checkpointu, seed, preprocessing, policy kafelkowania, warunki sprzętowe i runtime.
- W B1 sprawdzamy nieadaptowane modele (PatchCore poza zero-shot), potem B2 i B3.
- Nie wprowadzać żadnych zmian w dotychczasowym modelu bazowym Qwen3.8 i adapterach WVC/automotive.

**Nie ma wyników jakości z realnych obrazów PCB.**
