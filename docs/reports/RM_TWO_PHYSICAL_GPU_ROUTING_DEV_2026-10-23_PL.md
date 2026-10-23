# AI Platform — dwa fizyczne GPU i małe modele: etap DEV, 23.10.2026

**Wynik: PHYSICAL_GPU_BINDING_PASS, RTX_TWO_MODELS_PASS, DEV_RM_ROUTING_PASS.**
**Produkcja NIENARUSZONA. REAL_N1_GPU_GRANT=NOT_ADMITTED. GPU_REUSE_SAFE=NOT_VERIFIED.**

## Konfiguracja sprzętowa potwierdzona na serwerze

- RTX 5060 Ti 16 GB: CUDA0, PCI 0000:03:00.0, sterownik NVIDIA Open 615.71.09,
  USB4 TBGAA/JHL9480, PCIe Gen3 x4 8 GT/s; fabryczny limit mocy 180 W.
- Wbudowany AMD Radeon 890M: Vulkan GPU1, RADV STRIX1, PCI 0000:c6:00.0,
  /dev/dri/renderD128. NVIDIA ma /dev/dri/renderD129.
- Serwer harrypotter-AI-Series; kernel 7.0.0-39-generic, Ollama 0.40.7.
- Vulkan zgłasza ~111 GiB pamięci AMD, mimo że host posiada tylko ~30 GiB RAM.
  Tego nie można wykorzystywać do automatycznego budżetowania dużych modeli.

## Rzeczywiste testy na GPU

| Próba | Dowód | Wynik |
|---|---|---|
| Qwen3 0.6B na Radeon 890M | Ollama: using device Vulkan0 AMD Radeon 890M, PCI c6:00.0 | PASS |
| Qwen3 0.6B na RTX | Ollama: using device CUDA0 NVIDIA RTX 5060 Ti, PCI 03:00.0 | PASS |
| Pierwsza próba przypinania RTX | CPU fallback wykryty i odrzucony | INCOMPLETE (archiwum) |
| Dwa warianty tego samego Qwen | Wspólne wagi, /api/ps jeden runner | NIE JEST DOWODEM 2 MODELI |
| Dwa różne modele na RTX | Qwen3 0.6B + BGE-M3 jednocześnie w /api/ps | PASS |
| Ich VRAM i dwa równoległe requesty | 1441 MiB, poprawny tekst i embedding 1024 | PASS |
| Zamknięcie testów | P8, 2 MiB VRAM, Gen3 x4, RM IDLE | PASS |

Dowody znajdują się na NVMe w
/srv/ai-data/staging/gpu-dual-route-20261023/
(między innymi: amd-result.json, rtx-result.json, rtx-attempt1-result.json,
rtx-distinct-models-result.json; oryginalne logi silników).

## Przejście przez jeden istniejący Resource Manager — rzeczywisty test DEV

W stagingowym worktree dodano opcjonalny moduł
src/ai_bridge/gateway/physical_ollama_routing.py.
W trybie DEV Gateway nadal używa tylko jednego PriorityScheduler:
- Konfiguracja to ścisłe model -> amd albo rtx, z dwoma odrębnymi,
  lokalnymi URL 127.0.0.1:PORT dla fizycznie przypiętych serwerów.
- Nie ma nowego koordynatora, schedulera ani domyślnej aktywacji funkcji.
- Brak modelu lub błędny JSON => 422 zamiast niejawnego fallbacku.
- Nie akceptuje adresu z nagłówka klienta, zewnętrznego hosta, URL z
  auth, path, query lub fragmentem. Lease zewnętrzny => 409.
- Tryb DEV wymaga istniejącej jednej kolejki, max_concurrency=1
  i wyłączonego RADIO; nie deklaruje autoryzacji SHARED/N1.

**Rzeczywisty DEV Gateway/RM + dwa niezależne serwery Ollama: PASS.**
Krótki jednorazowy test wystartował lokalnie:
- Radeon 890M Vulkan: 127.0.0.1:11646, Qwen3 0.6B;
- RTX 5060 Ti CUDA: 127.0.0.1:11647, BGE-M3.
Żądanie do /api/generate => AMD, odpowiedź 4+6=10, job 1.
Żądanie do /api/embed => RTX, 1024 wymiary, job 2.
Nieznany model został odrzucony. Oba logi potwierdziły właściwy backend
i fizyczny PCI BDF. Jedna kolejka RM wróciła do active=0, queued=0.
Dowód /srv/ai-data/staging/gpu-dual-route-20261023/dev-routing-e2e/result.json.

Testy jednostkowe nowego routingu: 25/25 PASS.
Wybrane regresje Gateway, scheduler, lease, akceleratory: PASS.
Log: /srv/ai-data/staging/gpu-dual-route-20261023/rm-routing-regression-final.log.

Po wszystkich próbach: NVIDIA Xid=0, PCIe AER=0 na czterech urządzeniach,
brak dopasowanych błędów AMDGPU/MES w badanym oknie; bez osieroconych
testowych portów; produkcyjna Ollama i Gateway pozostały niezmienione,
RM IDLE, recovery_required=false, RTX P8, 2 MiB VRAM.

## Ważna granica bezpieczeństwa przed produkcją

**Nie uruchamiano multi-GPU w produkcyjnym Gateway.**
N1/N3 nie wydaje prawdziwych grantów GPU, a pozytywny dowód driver E_safe
nadal nie istnieje. Sama zmienna CUDA_VISIBLE_DEVICES czy
GGML_VK_VISIBLE_DEVICES nie uniemożliwia innym procesom obejścia RM przez
/dev/kfd, /dev/dri lub /dev/nvidia*. Obecny scheduler ma jeden slot;
przesyła zadania na dwa GPU, ale nie zatwierdza jednoczesnych grantów SHARED.
Dwa modele na RTX uruchomiono równolegle przez izolowaną Ollamę,
a nie przez nowy produkcyjny RM.

Przed cutover należy: zatwierdzić root-owned profile/cgroup i tożsamość
fizycznych serwerów oraz brak CPU fallback, budżet RAM (szczególnie 890M),
blokadę bypassu portów i device nodes, obsługę awarii i recovery,
zgodność z ComfyUI/Vision i testy negatywne. Weryfikacja modelu
Qwen3.8 27B dla Hermes na Radeon 890M będzie osobnym testem RAM.
Dopiero później uruchomienie Telegram/Hermes i kontrolowany rollback
do poprzedniego release.

Żadnych zmian w firmware, BIOS, GRUB, sterowniku NVIDIA, PCIe Gen3+HA,
fabrycznym limicie mocy, produkcyjnych usługach ani domyślnych ustawieniach RM.
