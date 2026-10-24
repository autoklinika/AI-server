# RTX 5060 Ti — pierwszy test rzeczywistego modelu AI
Data: 2026-10-23 CEST. Host: harrypotter-AI-Series, Ubuntu 26.04.1, NVIDIA Open 615.71.09.
Boot ID: d05627f7-8703-40d8-bc36-971578675050

## Zakres
Jednorazowe uruchomienie modelu **qwen3:0.6b** (~522.6 MB warstwa wag) w **izolowanej instancji Ollama 0.40.7** na 127.0.0.1:11931, z własnym OLLAMA_MODELS na /srv/ai-data/staging/egpu-ollama-ai-smoke-20261023/models.
Nie używano produkcyjnej usługi Ollama, Knowledge Service, Resource Manager ani produkcyjnych modeli. Nie zmieniano konfiguracji PCIe ani GRUB.
Karta: NVIDIA GeForce RTX 5060 Ti, CUDA backend cuda_v13, GPU compute capability 12.0, PCI BDF 0000:03:00.0. Link Gen3 x4 z Hardware Autonomous Speed Disable po wcześniejszym pilotażu.

## Potwierdzone wyniki
- MODEL_PULL_PASS, SERVER_READY Ollama 0.40.7
- 29/29 warstw modelu załadowano na CUDA0 (NVIDIA GeForce RTX 5060 Ti).
- /api/ps: rozmiar modelu w VRAM = 574 934 220 B (~548.3 MiB), wielkość całkowita = 574 934 220 B, tj. pełne offload GPU.
- Prompt: „Ile wynosi 17 + 25? Odpowiedz tylko liczbą.”
- Odpowiedź: „17 + 25 = 42” (poprawna).
- Wyjście API: done=true, done_reason=stop, eval_count=11, prompt_eval_count=37.
- Czasy raportowane przez API: total_duration=36.658 s, load_duration=18.167 s, prompt_eval_duration=13.597 s, eval_duration=4.891 s. Przy tylko 11 tokenach generowania zmierzone tempo to ~2.25 tok/s. Jest to bardzo krótka próbka z cold start; nie można utożsamiać jej ze stabilnym throughput ani rozstrzygać przyczyny niskiego tempa.
- Bez restartu hosta, Xid=0, AER correctable/nonfatal/fatal=0 na GPU i downstream bridge, PCIe 8 GT/s x4 na obu końcach, Ethernet i Wi-Fi działające.
- Po teście: żądanie wyładowania modelu, SERVER_STOPPED returncode=0, brak procesów Ollama/llama-server ani zajętych /dev/nvidia*, port 11931 zamknięty, produkcyjny ollama.service pozostał inactive.
- Własny katalog modelu ma ~499 MiB i pozostał na NVMe. Nie usuwano wag ani dzienników.

## Dane
attempt.jsonl — zapisane i zsynchronizowane zdarzenia od PREFLIGHT_PASS do END PASS.
response.json — pełna odpowiedź API z czasami.
loaded_models.json — migawka /api/ps potwierdzająca umieszczenie modelu w VRAM.
server.log — log backendu CUDA, m.in. offloaded 29/29 layers to GPU.
pull.log — pobranie modelu.
one_model_smoke.py — skrypt izolowanej próby.

Wniosek: rzeczywista inferencja modelu AI na RTX 5060 Ti zakończyła się powodzeniem w badanej konfiguracji Gen3 + HA. To nie dowodzi stabilności 24/7 ani należytej wydajności. Konfiguracja Gen3 + HA pozostaje tymczasowa do restartu systemu.
