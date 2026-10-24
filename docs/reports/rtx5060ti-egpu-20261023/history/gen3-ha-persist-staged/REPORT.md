# Raport przygotowania — 2026-10-23

**NOT_DEPLOYED · NOT_REBOOT_VERIFIED**

Pakiet implementacji znajduje się wyłącznie w
`/srv/ai-data/staging/egpu-gen3-ha-persist-20261023`.
Odczytowa weryfikacja identyfikatorów rzeczywistego sprzętu: **PASS**; wdrożenie i test po następnym rozruchu: **NIEWYKONANE**.
Statyczne `systemd-analyze verify`: **PASS na rzeczywistym hoście** (wykonane wyłącznie read-only); środowisko sandbox Codex wcześniej zwróciło `Operation not permitted`.

## Przyczyna wycofania pierwszej instalacji i rozwiązanie

Pierwsze wykonanie `sudo python3 -B deploy.py install --accept-risk` zwróciło
`INSTALL_FAILED; files rolled back: generated GRUB missing blacklist on a kernel entry`.
Przyczyną była nadmiernie szeroka walidacja wszystkich poleceń `linux` GRUB,
w tym osobnych bootów Memtest86+ (`/boot/mt86+x64`, `/boot/mt86+ia32`).
Memtest nie jest jądrem Ubuntu i nie przyjmuje parametrów sterownika NVIDIA.
Nowy walidator rygorystycznie sprawdza wszystkie wpisy `vmlinuz`/`vmlinuz-*`
i wymaga co najmniej jednego wpisu. Nie ignoruje rzeczywistych braków blacklist.
Automatyczny rollback usunął nowe pliki; brak nowej usługi, aktywne Gen3 x4,
SSH/Ethernet/Wi-Fi i NVIDIA pozostały sprawne (read-only weryfikacja hosta).

Dodano bezpieczne ponowienie instalacji po wyłącznie kompletnym rollbacku.
Stary backup nie jest kasowany, lecz przenoszony do katalogu archiwalnego
`/var/lib/ai-egpu-gen3-ha/backup-rolled-back-<sha256>`. Brak możliwości retry
po rollback-failed lub przy pozostawionych plikach zarządzanych.
Wymagana weryfikacja root-only fazy manifestu w następnym uruchomieniu instalatora.
`deploy.py check` jako użytkownik bez sudo nie ma uprawnień do katalogu backupu,
więc nie może potwierdzić jego fazy. Dodano jawne `root_only_backup_audited`
i `prior_clean_rollback`; właściwe sprawdzenie nastąpi dopiero pod sudo.

## Wyniki

- **PASS: 60 testów unittest**, w tym podprzypadki wszystkich pięciu awarii
  fsync intencji i wszystkich pięciu błędnych readbacków; log `test-results.txt`.
- End-to-end mock: GPU `0005 → 0023`, bridge `0044 → 0063`, dokładnie pięć
  maskowanych zapisów, jeden retrain na downstream, jeden controlled modprobe.
- Negatywne: typ PCIe/subsystem/device audio, bind GPU/bridge/audio, obecność
  modułów, Xid/AER/log/counter/Device Status, unsupported Gen3, brak TBGAA,
  zły UUID, timeout, drift/hotplug, zmiana modułów po intencji i po zapisie,
  błędy fsync, journal collision/symlink, retry, zmiana boot-id, marker
  mode/owner/symlink, nieprawidłowe argumenty wrappera, drift po modprobe.
- Instalator mock: sukces/rollback, oryginalne nieistnienie i enable state,
  zachowanie kolizji i jej mode, root/accept-risk, read-only check, błędy copy,
  enable/update-grub/validate, niepoprawny wygenerowany GRUB, istniejący install
  override, ponowna instalacja, fallback oryginalnego grub.cfg i ponowienie
  nieudanego rollbacku. Żaden mock nie uruchamia poleceń hosta.
- AST wszystkich Pythonów i wrappera: **PASS** w unittest.
- `/bin/sh -n zz-ai-egpu-gen3-ha.cfg`: **PASS**.
- Pierwsza statyczna próba w sandboxie Codex zwróciła ograniczenie socketów.
  Niezależna read-only weryfikacja `systemd-analyze verify` na prawdziwym hoście
  zakończyła się kodem **0**. Skuteczne zależności jednostek produkcyjnych
  wymagają nadal sprawdzenia po instalacji i rozruchu.

Testy root-owned policy używają właściciela fake-root (UID/GID 1000), sprawdzają
odrzucanie innego właściciela i złych trybów. NIE są dowodem rzeczywistego zapisu
root:root. Produkcja wymaga UID 0, sprawdza owner/group 0 i wykonuje fchown kopii
oraz dziennika. Sprawdzanie bezpiecznych ancestor directories zostało zastąpione
w fixture, aby nie wymagać roota; rzeczywisty układ uprawnień oceni instalator.

## Zakres operacji tej sesji

Odczytano oryginalne pliki pilota bez ich modyfikacji, definicje usług,
identyfikatory PCIe (GPU, audio i mostek) oraz topologię TBGAA. Wszystkie nowe
pliki powstały w stagingu. Niezależny audyt read-only: `deploy.py check`,
`Boot.discover(False)`, `systemd-analyze verify` — **PASS**. Testy unit/mocks
odbyły się bez poleceń sprzętowych. Nie wykonano `apply`, `install`, `rollback`,
`sudo`, `reboot`, `modprobe`, zapisów `setpci`, `systemctl start/stop/enable`,
`update-grub` ani regeneracji initrd. Brak zmian w produkcji i działającym GPU.

## Punkty wymagające niezależnej weryfikacji

1. Weryfikacja statyczna jednostki systemd poza sandboxem — PASS.
   Walidacja wygenerowanego GRUB i efektywnego modprobe nastąpi dopiero podczas instalacji.
2. Potwierdzono rzeczywisty subsystem audio 10de:0000 (GPU: 1043:8a11).
   Kod dopasowuje oba oddzielnie, zamiast zgadywać wspólną wartość.
3. Potwierdzono driver pcieport na downstream JHL9480. Kod dopuszcza
   wyłącznie legalny pcieport na bridge; nie odłącza go.
4. Weryfikowane są jednoznaczne urządzenia, bezpośredni parent PCI, router UUID,
   przepustowość i inode/ścieżki. Nie ma odrębnego dowodu mapowania tunelu USB4
   do PCI — opis i ograniczenie w README.
5. Guard nie monitoruje stale już działającego GPU. Po błędzie inicjalizacji
   nvidia może być załadowana; gotowość zostaje cofnięta, konsumenci zablokowani,
   bez niebezpiecznego unload/retrain. Zwykłe błędy mają rollback plikowy;
   utrata zasilania/SIGKILL wymaga odtworzenia z trwałego manifestu.
6. Wprowadzono bezpiecznik między rozruchami: poprzednia próba bez końcowego PASS blokuje automatyczne ponowienie GPU. Wymagana ręczna diagnostyka lub rollback.
7. Globalna blokada snd_hda_intel wyłącza też wewnętrzne audio AMD. Rollback
   usuwa ją z konfiguracji, ale aktualne flagi kernela pozostają do rebootu.

README zawiera dokładne polecenia użytkownika do przyszłej instalacji i rollbacku.
Żadne z tych poleceń nie zostało wykonane. SHA256SUMS obejmuje kod, konfigurację,
dokumentację i końcowe logi, z wyłączeniem samego SHA256SUMS oraz zmieniającego się
transkryptu sesji i dostarczonego pliku zadania.
