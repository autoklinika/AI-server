# AI Platform — uruchamianie prawdziwego ComfyUI na żądanie, DEV — wynik negatywny

**23.10.2026, host harrypotter-AI-Series — status BLOCKED, nie zaakceptowano GPU on-demand.**

## Warunki testu

Po zaliczeniu 434 testów CPU/ASGI dotychczasowej implementacji ComfyUI
on-demand w istniejącym RM podjęto próbę uruchomienia oryginalnego
ComfyUI z jego produkcyjnego katalogu i venv, lecz w **oddzielnym,
tymczasowym systemd --user**, z przeznaczonym wyłącznie dla DEV:
- adresem 127.0.0.1:11657;
- katalogiem danych, modeli, wejścia i wyników na NVMe w staging;
- opcjami --cpu, --disable-all-custom-nodes, --disable-auto-launch;
- cgroup MemoryMax=4G, MemorySwapMax=0, RuntimeMaxSec=120s,
  Restart=no, CPUQuota=200%, TasksMax=128;
- własnym recovery marker i odrębną instancją Gateway/RM w teście ASGI,
  bez modyfikacji produkcyjnego Gateway, Hermes, ComfyUI lub systemd.

Produkcja była IDLE; ComfyUI nadal działała pod PID 4937,
ale bez aktywnych zadań i załadowanych modeli. Próba nie miała
uruchamiać drugiego procesu obliczeniowego AMD GPU. **Test nie
posiadał systemowej izolacji DevicePolicy**: wcześniejsze badania
udowodniły, że user-manager DevicePolicy=closed może być nieskuteczne.

## Trzy próby i wykryte błędy

| Próba | Moment lokalny | Przyczyna niepowodzenia | Efekt |
|---|---|---|---|
| 1 | 22:31:15 | Python -I ukrył projektowy pakiet comfy, ModuleNotFoundError | Fail-closed, brak działania |
| 2 | 22:31:57 | Biblioteka ROCm/HIP odrzuciła ROCR_VISIBLE_DEVICES=-1 | Aborted (SIGABRT), fail-closed |
| 3 | 22:33:45 | Biblioteka ROCm/HIP odrzuciła CUDA_VISIBLE_DEVICES=-1 | Aborted (SIGABRT), fail-closed |

Główny rzeczywisty powód prób 2 i 3 jest jednoznaczny
w logu: oczekiwany identyfikator/ordinal GPU, a nie wartość -1.
Nawet przy --cpu import modułu comfy_kitchen wywołuje
torch.cuda.is_available(), inicjując kod ROCm/HIP podczas importu.
Uruchomienie z --cpu **nie jest dowodem braku interakcji z GPU**.

Nie wygenerowano prawdziwego obrazu przez tę instancję. Nie uzyskano
również potwierdzenia kompletnego bezpiecznego wyłączenia sterownika.
W wyniku błędu zablokowano kontynuację próby.

## Mechanizmy bezpieczeństwa, które zadziałały

- Próby zostały zablokowane zanim RM wystawił aktywne zewnętrzne użycie
  ComfyUI (/uses nie otrzymało sukcesu 201).
- Marker DEV rm-recovery.blocked pozostaje obecny. Nie uznajemy
  nieudanego startu za pozytywne zwolnienie GPU.
- Wszystkie tymczasowe jednostki systemd zostały zakończone,
  API na 11657 nie nasłuchuje, żaden proces testowego ComfyUI
  nie pozostaje aktywny.
- Produkcyjny ComfyUI pozostał z tym samym PID 4937, Gateway,
  Ollama i bramka eGPU nie były zmieniane ani restartowane.
- Produkcyjny RM pozostał IDLE, bez aktywnych lub czekających zadań,
  recovery_required=false.
- RTX po próbie: P8, 2 MiB VRAM, PCIe Gen3 ×4, AER=0.
  Nie zaobserwowano błędów NVIDIA Xid ani resetu GPU w badanym oknie.
- Zapisano oryginalne negatywne wyniki i znaczniki w staging
  pod /srv/ai-data/staging/comfy-ondemand-dev-20261023/real-comfy-cpu/.
  Repo zawiera jedynie streszczenie i SHA256 tych lokalnych wyników.

Maszynowy wynik: RM_COMFY_REAL_START_DEV_BLOCKED_2026-10-23.json.

## Decyzja i kolejna bramka

**NO-GO dla realnego ComfyUI on-demand i produkcji.**
Bez kolejnych prób tego samego ROCm/venv przy aktywnym produkcyjnym
ComfyUI na Radeonie. Nie ustawiamy -1 w ROCR_VISIBLE_DEVICES ani
CUDA_VISIBLE_DEVICES bez potwierdzenia obsługi przez konkretny
zainstalowany ROCm.

W osobnym kontrolowanym oknie serwisowym należy:
1. Zarchiwizować konfigurację boot, Gateway oraz bieżące procesy i
   przygotować niezależny, przetestowany rollback.
2. Rozwiązać Requires=comfyui.service w Gateway i stary autostart,
   tak aby Gateway/Hermes działały bez stale aktywnego ComfyUI.
3. Dopiero po zwolnieniu istniejącego procesu/sterownika zgodnie
   z ostrożnymi wymaganiami rozpocząć test prawdziwego ComfyUI
   **w systemowym, root-owned cgroup** na Radeonie, ze znaną poprawną
   konfiguracją ROCm (bez nieobsługiwanych -1).
4. Przetestować kontrolowaną generację, zakończenie, awarię,
   timeout, OOM, brak osieroconych procesów i odzyskanie GPU.
5. Potwierdzić osobno obsługę Hermes /foto, WVC, Vision i dwóch GPU,
   a następnie wnieść o świadomą zgodę na produkcyjny cutover.

Dotychczasowe 434 testy CPU/ASGI pozostają zaliczone, lecz nie
zastępują negatywnego wyniku realnego startu. Zmiany DEV pozostają
w Draft PR #178. **Brak zmian produkcyjnych.**
