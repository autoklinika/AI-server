# Raport naprawy pierwszego normalnego bootu — 2026-10-23

**Stan: V2_STAGED, NOT_INSTALLED, NOT_REBOOT_VERIFIED.**

Podczas normalnego bootu z UUID `83427b55-db11-4fa2-b67d-a7f89e9e41bd` 23.10.2026 o 14:02 gate zakończył się FAIL po 50,1 s. W dzienniku `attempt`, `FAIL: journalctl ... timed out after 0.0071...`, **0 write-intent**, więc nie wykonano retrain. NVIDIA pozostała niezaładowana, łącze 16GT/s x4 (Gen4). SSH, LAN, Wi-Fi, Tailscale działają; AER=0.

Dodatkowy root read-only:
- RTX 03:00.0 CAP_EXP+0a.w 0009 (CED i URD), 02:00.0 0010 (auxiliary power, nie błąd)
- EXP, LnkSta, LnkCtl2, identyfikatory i sysfs topology PASS poza restrykcyjnym warunkiem v1 zerowych error bits
- PCIe / BAR zasoby były przeliczane podczas rozruchu. Historyczna natura RW1C uzasadnia hipotezę wcześniejszego zdarzenia, ale **nie potwierdza źródła flag**
- v1 w zbyt częstej pętli uruchamiał `journalctl`, wyczerpując budżet timeoutu i maskując właściwy warunek.

Kandydat v2 w `ai_egpu_boot.py` dopuszcza wyłącznie dokładnie obserwowany wzór 0009 lub 0000, blokuje inne Device Status errors i nowe bity, stale wymaga AER=0 i czystego kernela, a limituje obciążenie `journalctl`; nadal 5 masked writes i jeden retrain. Dane oryginalnego zdarzenia Device Status zapisywane są na NVMe.

`repair.py` ma kontrolę tylko do odczytu i kontrolowaną jednorazową podmianę root-owned jednego skryptu, wraz z atomowym zachowaniem starego źródła i wcześniejszego nieudanego dziennika. **Nie zmienia systemd, GRUB, initrd, urządzeń, sterownika ani usług w tym boocie.** Dokumentacja `README.md`.

Testy: see `test-results.txt` and `SHA256SUMS`. Kandydat nie ma real-hardware PASS: warunkiem następnego kroku jest `sudo python3 -B repair.py check`, które uruchomi candidate `Boot.full` tylko READ-ONLY na rzeczywistym GPU. Instalacja i ponowny rozruch wymagają oddzielnych kroków operatora.

**Ograniczenie bezpieczeństwa:** przy ustawionym historycznie CED|URD bit nie rozróżni kolejnego zdarzenia tej samej klasy bez W1C clear, którego celowo NIE wykonujemy, aby uniknąć dodatkowego niezbadanej operacji na PCIe. Trwałą stabilność można potwierdzić dopiero testami i obserwacją po skutecznym starcie.
