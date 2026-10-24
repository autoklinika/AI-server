# ComfyUI + istniejący Resource Manager — minimalna integracja, 24.10.2026

**Zakres:** bez nowego schedulera, drugiego ComfyUI, osobnego kontrolera GPU, nowych usług systemd lub zmian w produkcji podczas testów.

## Co już jest w main

Ścieżka /foto korzysta z istniejącego globalnego RM:
Hermes worker → acquire_resource(media-image) → zarezerwowany ticket →
media_admission(image-generation|image-edit) → generator ComfyUI →
DELETE .../uses/{id} → zwolnienie lease.
Generatory mają require_external_media_use(...) i przed wykonaniem żądania sprawdzają istniejący token RM. RM ma jeden slot.

## Jedyna poprawka

W dwóch istniejących generatorach ComfyUI parametr CLIPLoader.device zmieniono z
default na **cpu** dla tekstowego encodera qwen_3_4b.safetensors.
Sam **FLUX2 Klein 4B FP8 i VAE pozostają w ścieżce AMD Radeon 890M**.
Powód: pierwsza rzeczywista próba CLIPLoader.device=default zakończyła się błędem Tritona
"2 active drivers ([HIPDriver, CudaDriver])". Użycie encodera na CPU rozwiązało konflikt.

## Testy fizyczne na realnym AI Platform

- 24.10.2026, standalone FLUX2, 256×256, 4 kroki, rzeczywisty Radeon 890M:
  Flux2-Klein_00069_.png, 105008 B, ComfyUI 57,29 s — **PASS**.
  SHA256: a3e665eb75178df531b94e0bc07d8323450e8abc058316ae2be8fac337374464.
- Kolejny rzeczywisty test oryginalnego Hermes /foto worker z istniejącym
  Gateway/RM i ComfyUI: Flux2-Klein_00071_.png, 256×256, 105437 B,
  render 53,995 s — **PASS**.
- Ten sam globalny RM: przy aktywnym zadaniu drugi niższy priorytet otrzymał
  queued; po heartbeat dotrwał do aktywnego przydziału; potem zwolniono lease — **PASS**.
- Drugi render zaraz po zwolnieniu: Flux2-Klein_00072_.png,
  256×256, 105437 B, render 53,922 s — **PASS**, bez restartu ComfyUI.
- Końcowy RM: IDLE, active=0, queued=0, recovery_required=false.
  Produkcyjne Gateway, Ollama, ComfyUI i eGPU pozostawały aktywne.
- Przeprowadzono na prawdziwych modelach FLUX2. **Kompilator Qwen 35B był
  zastąpiony neutralną odpowiedzią testową**, dlatego pełne Qwen35→FLUX2 E2E
  nadal **NOT_TESTED**. Brak wysyłki Telegram (lokalny capture).
- GPU_REUSE_SAFE=NOT_VERIFIED w sensie pełnego odbioru sterownika i
  przełączania Ollama/ComfyUI; dwa rzeczywiste rendery nie stanowią takiego odbioru.

Surowe logi (tylko na NVMe):
/srv/ai-data/staging/gpu-dual-route-20261023/minimal-foto-real-20261024-r2/.
Wcześniejsza sonda kolejki bez heartbeat wygasła po TTL — oczekiwane zabezpieczenie RM,
nie defekt generatora.

## Ważne ograniczenie

Ta integracja chroni **zarządzaną ścieżkę /foto i generatorów**. Bezpośrednie
lokalne wywołania HTTP ComfyUI :8188/prompt poza RM pozostają możliwe;
nie twierdzimy, że zablokowano wszystkie inne wejścia do ComfyUI.

**Zmiany są w gałęzi DEV, nie w aktywnym obrazie release /opt/ai-platform/current.**
Instalacja aktualizacji wymaga osobnego operatorowego cutover i rollbacku
dwóch plików z obecnego wdrożenia. Starszy rozbudowany PR #178 pozostaje
odrębnym eksperymentem, nie warunkiem tej poprawki.
