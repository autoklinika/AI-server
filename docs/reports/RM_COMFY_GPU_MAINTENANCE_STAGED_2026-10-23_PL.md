# ComfyUI on-demand — jednorazowy test GPU, procedura serwisowa DEV

Data: 23.10.2026. Host: harrypotter-AI-Series.

**Stan: STAGED / PREFLIGHT PASS / REAL GPU MAINTENANCE NOT EXECUTED.**
**PRODUKCJA NIENARUSZONA.** PR #178 pozostaje Draft; nie scalać.

## Dlaczego potrzebne jest okno serwisowe

- Produkcyjny comfyui.service nadal uruchamia się automatycznie
  (multi-user.target, Restart=always) i utrzymuje deskryptory AMD KFD/DRM,
  mimo zerowych modeli i pustej kolejki.
- Produkcyjny Gateway ma Requires=comfyui.service i After=comfyui.service.
  Niezależne zatrzymanie ComfyUI może wpłynąć na Gateway.
- Hermes /foto już wykonuje zlecenia z użyciem wspólnej kolejki
  Resource Managera. Problemem jest lifecycle procesu, nie planowanie.
- Próby rzeczywistego ComfyUI z --cpu i niewłaściwymi zmiennymi
  widoczności ROCm zakończyły się fail-closed. Obecny pilot nie
  używa --cpu ani wartości -1 dla żadnej zmiennej GPU.

Nie można bezpiecznie uruchomić drugiej instancji ROCm obok
produkcyjnego ComfyUI trzymającego kontekst Radeona. Dlatego
krótki test sprzętowy wymaga odizolowania starego procesu.

## Przygotowana procedura operatorska

Skrypt na NVMe:
 /srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023/run-maintenance-dev.sh

Repozytorium:
 deploy/comfy-ondemand-dev/maintenance-20261023/

Tryb domyślny --check odczytuje konfigurację systemd, PID, kolejkę,
recovery marker, aktywność ComfyUI, Ollamę i PCIe.
**Wykonany zdalnie: PASS.**

Tryb --run (wymaga sudo, NIE WYKONANO) ma następującą kolejność:
1. Ponowne sprawdzenie preflight i utworzenie backupu efektywnej
   konfiguracji jednostek systemd w katalogu staging (bez modyfikacji).
2. Uzbrojenie niezależnego watchdog rollback timer; jego skrypt
   jest kopiowany root-owned do /run, poza katalog użytkownika.
3. Zatrzymanie produkcyjnego ai-gateway.service, potem comfyui.service.
   Hermes może czasowo utracić możliwość obsługi wiadomości.
4. Weryfikacja pustych kolejek, braku procesów ComfyUI, portów
   11435/8188 i otwartych deskryptorów AMD KFD/renderD128.
   Nieznany właściciel GPU natychmiast blokuje próbę.
5. Uruchomienie rzeczywistego ComfyUI tylko w tymczasowym,
   *systemowym* systemd (DevicePolicy=closed, DeviceAllow=KFD +
   renderD128, MemoryMax=9G, RuntimeMaxSec=240s, Restart=no)
   jako użytkownik harrypotter. Nie instaluje się jednostki.
6. W pamięci testowej instancji istniejącego Gateway/RM
   przydzielenie jednej rezerwacji, przypisanie inkarnacji procesu
   boot/PID/cgroup/InvocationID, weryfikacja fizycznego Radeona 890M.
   Test ma uruchomić VAE Flux2 na obrazie 64×64 i zapisać PNG.
7. Kontrola, że następne zadanie stoi w jednej kolejce RM,
   aż silnik zakończy /free, zwolni modele, proces i cgroup.
8. Niezależnie od wyniku: zatrzymanie jednostki DEV i sprawdzenie,
   że nie ma jego procesu ani portu 11657. Dopiero wtedy
   przywrócenie oryginalnego comfyui.service i ai-gateway.service,
   potwierdzenie obu endpointów /health i /ai-platform/residency.
   Nie zmienia się żadnych plików produkcyjnych.

Jeśli jednostka DEV nie może zostać zatrzymana w pełni,
rollback **nie uruchomi równolegle produkcyjnego ComfyUI**.
W takiej sytuacji API może pozostać niedostępne i konieczny
jest ręczny nadzór operatora. Bezpieczeństwo GPU ma pierwszeństwo
przed ciągłością pracy podczas krótkiego okna serwisowego.

## Wyniki testów procedury (nie GPU)

- bash -n dla skryptu operatora i rollbacku: PASS.
- Python AST dla harness: PASS.
- Kontrola wyłączności AMD KFD/renderD128 i braku NVIDIA w
  jednostce systemowej: PASS (statyczna).
- 7/7 testów ochrony systemd, timera, rollbacku, ograniczeń
  i braku zmian trwałych: PASS.
- Rzeczywisty --check na AI Platform: PASS.
- Wywołanie --run bez uprawnień administratora: poprawnie
  odmówione, brak przerwy w usługach: PASS.
- Produkcyjne Gateway, ComfyUI, Ollama i eGPU boot-gate
  po preflight pozostały aktywne, RTX P8/2 MiB, Gen3×4.
- Realny test GPU ComfyUI w tym oknie: **NOT EXECUTED**.

## Bramka po próbie

Po --run ostateczne PASS wolno nadać tylko gdy wykonanie obrazu,
prawidłowe przypięcie cgroup, oczekiwanie zadania i stop procesów,
rollback produkcyjnych jednostek i testy zdrowia przejdą.
W przeciwnym razie zapisujemy wynik fail-closed.

Nawet sukces pojedynczego zadania nie oznacza pozytywnego
GPU_REUSE_SAFE ani SHARED/N1; pozostaje **NOT_VERIFIED**,
bo globalna izolacja urządzeń i kompletna weryfikacja sterownika
AMDGPU/KFD/MES nadal są osobnymi etapami.

**Nie wykonano wdrożenia produkcyjnego, nie zmieniono GRUB,
sterownika, firmware, PCIe Gen3 + HA, power limit ani systemd.**
