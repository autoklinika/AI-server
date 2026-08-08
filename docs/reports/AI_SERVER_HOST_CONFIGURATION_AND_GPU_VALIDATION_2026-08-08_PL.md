# AI Server – konfiguracja hosta, zdalny dostęp i walidacja GPU

**Data:** 08.08.2026  
**Status:** stan zwalidowany na działającym hoście  
**Repozytorium:** `autoklinika/AI-server`

## 1. Cel dokumentu

Ten dokument zapisuje rzeczywisty stan konfiguracji Serwera AI po uruchomieniu systemu, konfiguracji zdalnego dostępu, Dockera, Ollamy oraz akceleracji GPU dla modelu Qwen 3.6 35B.

Dokument ma pełnić rolę punktu odtworzeniowego. Zawiera:

- sprzęt i system operacyjny,
- układ pamięci i dysków,
- stan sieci,
- zdalny dostęp administracyjny,
- Docker,
- Ollama i model Qwen,
- konfigurację AMD ROCm/Vulkan,
- wymagane ustawienia systemd,
- zwalidowany wynik wykorzystania GPU,
- benchmark modelu,
- elementy świadomie wyłączone lub usunięte,
- podstawowe komendy diagnostyczne.

Dokument **nie zawiera żadnych haseł ani innych sekretów**. Sekretów nie wolno dodawać do repozytorium.

---

## 2. Nadrzędna zasada architektury

Serwer AI pozostaje warstwą analityczną.

W projekcie wentylacji obowiązuje zasada:

> **CM5 steruje systemem. Python przygotowuje dane. Qwen interpretuje dane. AI doradza, ale nigdy nie steruje wentylacją.**

Konfiguracja hosta opisana tutaj nie zmienia tej granicy odpowiedzialności.

Powiązane dokumenty:

- `docs/AI_SERVER_PROJECT_INITIALIZATION_REPORT_PL.md`
- `docs/ADR-003_AI_BRIDGE_PLATFORM_ARCHITECTURE_PL.md`
- `docs/ADR-004_TELEMETRY_STORAGE_AND_RETENTION_PL.md`

---

## 3. Sprzęt

### 3.1. Host

- producent raportowany przez SMBIOS: `Micro Computer *HK* Tech Limited`
- model: `AI Series`
- hostname: `harrypotter-AI-Series`
- firmware: `1.01`
- data firmware: `2026-04-09`

### 3.2. CPU

- **AMD Ryzen AI 9 HX 470 with Radeon 890M**
- 12 rdzeni
- 24 wątki
- 2 wątki na rdzeń
- maksymalna częstotliwość raportowana przez system: ok. 5.3 GHz
- AMD-V: dostępne

### 3.3. GPU

Zintegrowany układ graficzny:

- **AMD Radeon 890M**
- wykrywany przez PCI jako `AMD Strix [Radeon 880M / 890M]`
- Vulkan/RADV: `AMD Radeon 890M (RADV STRIX1)`
- ROCm compute target wykrywany przez Ollamę: `gfx1150`

GPU jest iGPU korzystającym z pamięci współdzielonej/UMA.

### 3.4. RAM / UMA

Komputer jest wyposażony w **128 GB RAM**.

Aktualna konfiguracja platformy przeznacza około **96 GB** na pamięć współdzieloną iGPU/UMA. Linux raportuje dla systemu około:

```text
MemTotal: 31965156 kB
```

czyli ok. **30.5 GiB** pamięci systemowej dostępnej dla CPU/OS.

Ta konfiguracja jest świadoma i umożliwia uruchamianie dużych modeli na Radeon 890M z wykorzystaniem dużej puli pamięci współdzielonej.

Na tym etapie **nie zmieniamy podziału UMA**.

---

## 4. Dyski

Aktualnie w komputerze jest jeden sprawny NVMe:

```text
SPCC M.2 PCIe SSD
pojemność nominalna: 4 TB
pojemność raportowana: ok. 3.7 TiB
```

Układ partycji:

```text
nvme0n1       3.7T
├─nvme0n1p1     1G  vfat  /boot/efi
└─nvme0n1p2   3.7T  ext4  /
```

W chwili walidacji:

- zajęte: ok. 44 GB,
- wolne: ok. 3.5 TB,
- wykorzystanie partycji root: ok. 2%.

Wcześniejszy dodatkowy dysk **1 TB został fizycznie zdemontowany z powodu uszkodzenia**. Jego brak w `lsblk` jest więc stanem oczekiwanym, a nie błędem wykrywania urządzenia.

`nvme-cli` nie jest obecnie zainstalowane i nie jest wymagane do bieżącego etapu projektu.

---

## 5. System operacyjny

- **Ubuntu 26.04 LTS**
- architektura: `x86-64`
- kernel w chwili walidacji: `Linux 7.0.0-29-generic`

System został zaktualizowany podczas etapu inicjalizacji. W dniu 08.08.2026 system raportował również kolejne dostępne aktualizacje; ich liczba jest informacją chwilową i nie stanowi części stałej konfiguracji.

Ubuntu Pro / ESM Apps nie jest wymagane do działania projektu i w chwili walidacji nie było aktywne.

---

## 6. Sieć

Aktywny interfejs w chwili walidacji:

```text
wlp194s0  UP  192.168.1.55/24
```

Adres LAN używany do administracji:

```text
192.168.1.55
```

Interfejsy Ethernet były w chwili walidacji nieaktywne:

```text
enp195s0  DOWN
enp196s0  DOWN
```

Docker tworzy lokalną sieć:

```text
docker0  172.17.0.1/16
```

**Uwaga:** `192.168.1.55` jest zwalidowanym bieżącym adresem hosta. Dokument nie zakłada, że adres został już zarezerwowany na DHCP lub ustawiony statycznie. To należy traktować jako osobne zadanie infrastrukturalne, jeśli wymagana będzie gwarancja niezmienności adresu.

---

## 7. Zdalny dostęp administracyjny

Po testach kilku metod przyjęto dwa proste i niezależne kanały administracji:

### 7.1. SSH

OpenSSH Server działa poprawnie i nasłuchuje na porcie:

```text
22/tcp
```

Połączenie z Windows 11:

```powershell
ssh harrypotter@192.168.1.55
```

SSH jest podstawowym kanałem do pracy terminalowej i wykonywania poleceń administracyjnych.

### 7.2. Cockpit

Zainstalowano **Cockpit** z repozytorium Ubuntu.

Socket Cockpit jest:

```text
enabled
active
```

Dzięki temu panel uruchamia się automatycznie po restarcie systemu.

Adres panelu w sieci LAN:

```text
https://192.168.1.55:9090
```

Port:

```text
9090/tcp
```

Cockpit zapewnia między innymi:

- podgląd systemu,
- usługi systemd,
- logi,
- sieć,
- dyski,
- terminal WWW.

Lokalny certyfikat Cockpit może powodować ostrzeżenie przeglądarki o niezaufanym certyfikacie. Jest to oczekiwane dla bieżącej konfiguracji LAN.

### 7.3. Zwalidowane porty zdalnego dostępu

Po uporządkowaniu konfiguracji aktywne były:

```text
22    SSH
9090  Cockpit
```

Porty:

```text
3389
3390
```

nie były już nasłuchiwane.

### 7.4. RDP / xrdp

Testowano:

- GNOME Remote Login,
- GNOME Desktop Sharing,
- `xrdp` + `xorgxrdp`.

Rozwiązania te nie zostały przyjęte jako docelowe z powodu problemów z uruchomieniem stabilnej sesji graficznej.

Stan końcowy:

- GNOME RDP wyłączone,
- poświadczenia GNOME RDP usunięte,
- `xrdp` usunięty,
- `xorgxrdp` usunięty,
- brak listenerów na 3389/3390.

### 7.5. DWService

DWService był rozważany jako alternatywa, ale **nie został zainstalowany jako usługa docelowa**. Pobrane testowo instalatory zostały usunięte podczas porządkowania.

### 7.6. Firewall

W chwili walidacji:

```text
ufw: inactive
```

To jest obecny stan, a nie rekomendacja docelowej polityki bezpieczeństwa. Przed wystawieniem jakiejkolwiek usługi poza zaufaną sieć LAN należy zaprojektować osobną politykę dostępu/firewalla/VPN.

**Nie należy wystawiać Cockpit ani SSH bezpośrednio do Internetu bez osobnej decyzji i zabezpieczeń.**

---

## 8. Docker

Zainstalowany Docker:

```text
Docker version 29.1.3, build 29.1.3-0ubuntu4.1
```

Usługa:

```text
systemctl is-active docker
active
```

Użytkownik `harrypotter` został dodany do grupy:

```text
docker
```

Po ponownym zalogowaniu zwalidowano:

```bash
docker ps
```

Polecenie działa bez `sudo` i bez błędu `permission denied`.

W chwili walidacji nie było uruchomionych kontenerów:

```text
CONTAINER ID   IMAGE   COMMAND   CREATED   STATUS   PORTS   NAMES
```

Docker jest przygotowany do późniejszego wykorzystania przez AI Bridge lub usługi pomocnicze, ale **Ollama działa obecnie natywnie jako usługa systemd, nie w kontenerze**.

---

## 9. Ollama

### 9.1. Instalacja i usługa

Zainstalowana wersja:

```text
ollama 0.32.6
```

Stan usługi:

```text
active
enabled
```

Oznacza to, że Ollama działa i uruchamia się automatycznie po starcie hosta.

Domyślny lokalny endpoint API:

```text
http://127.0.0.1:11434
```

Na obecnym etapie API Ollamy pozostaje lokalne dla hosta. Integracja z AI Bridge będzie realizowana lokalnie na Serwerze AI.

### 9.2. Model

Pobrany i zwalidowany model:

```text
qwen3.6:35b
```

Model ID:

```text
07d35212591f
```

Rozmiar plików modelu raportowany przez `ollama list`:

```text
ok. 23 GB
```

Model odpowiada poprawnie po polsku i działa przez CLI oraz REST API Ollamy.

---

## 10. Akceleracja AMD – stan przed poprawką

Początkowo model działał wyłącznie na CPU:

```text
PROCESSOR: 100% CPU
CONTEXT:   4096
```

Mimo że system widział Radeon 890M, Ollama nie używała go do inferencji.

Zweryfikowano uprawnienia użytkownika usługi:

```text
uid=997(ollama)
groups=ollama,video,render
```

Urządzenia AMD istnieją i są dostępne dla grupy `render`:

```text
/dev/dri/renderD128
/dev/kfd
```

To wykluczyło problem braku urządzeń lub podstawowych uprawnień usługi Ollama.

---

## 11. Backend AMD / ROCm

Doinstalowano oficjalny pakiet backendu ROCm dla Ollamy:

```text
ollama-linux-amd64-rocm.tar.zst
```

Pakiet został rozpakowany do `/usr` z obsługą Zstandard.

Przykładowe polecenie użyte do instalacji backendu:

```bash
curl -fsSL https://ollama.com/download/ollama-linux-amd64-rocm.tar.zst \
  | sudo tar --zstd -x -C /usr
```

Po instalacji backend znajduje się między innymi w:

```text
/usr/lib/ollama/rocm_v7_2/
```

i zawiera m.in.:

```text
libggml-hip.so
libamdhip64.so
librocblas.so
libhipblas.so
libhsa-runtime64.so
```

Ollama rozpoznaje układ jako:

```text
library=ROCm
compute=gfx1150
description="AMD Radeon Graphics"
```

---

## 12. Vulkan / RADV

Zainstalowano:

```text
mesa-vulkan-drivers
vulkan-tools
```

Test uruchomiony bezpośrednio jako użytkownik `harrypotter` wskazał brak uprawnień do render node dla tego użytkownika i fallback do `llvmpipe`.

Kluczowy test został wykonany jako użytkownik usługi `ollama`:

```bash
sudo -u ollama env HOME=/usr/share/ollama \
  vulkaninfo --summary | grep -Ei 'GPU[0-9]|deviceName|driverName'
```

Wynik:

```text
GPU0:
    deviceName = AMD Radeon 890M (RADV STRIX1)
    driverName = radv

GPU1:
    deviceName = llvmpipe (...)
    driverName = llvmpipe
```

Najważniejsze: użytkownik usługi Ollama widzi poprawnie sprzętowy Radeon 890M przez RADV.

`llvmpipe` jest programowym rendererem CPU i nie jest wykorzystywany jako docelowy backend GPU.

---

## 13. Przyczyna wcześniejszego `100% CPU`

Logi Ollamy jednoznacznie wykazały przyczynę:

```text
dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1
```

Ollama poprawnie wykrywała Radeon 890M zarówno przez ROCm, jak i Vulkan, ale świadomie odrzucała go, ponieważ jest to GPU zintegrowane.

Przykładowo wykrywano:

```text
library=ROCm
compute=gfx1150
```

oraz:

```text
library=Vulkan
description="AMD Radeon 890M (RADV STRIX1)"
```

Bez dodatkowej zmiennej środowiskowej końcowy backend inferencji pozostawał:

```text
cpu
```

---

## 14. Docelowa konfiguracja Ollama dla iGPU

Utworzono override systemd:

```text
/etc/systemd/system/ollama.service.d/vulkan.conf
```

Aktualna istotna zawartość:

```ini
[Service]
Environment="OLLAMA_VULKAN=1"
Environment="OLLAMA_IGPU_ENABLE=1"
```

Po każdej zmianie override należy wykonać:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Kontrola konfiguracji:

```bash
systemctl show ollama --property=Environment
```

W środowisku usługi muszą być widoczne:

```text
OLLAMA_VULKAN=1
OLLAMA_IGPU_ENABLE=1
```

### Ważne

Obie zmienne należy zachować przy późniejszych modyfikacjach usługi Ollama.

Usunięcie `OLLAMA_IGPU_ENABLE=1` spowoduje ponowne odrzucenie Radeon 890M jako iGPU i powrót inferencji na CPU.

---

## 15. Walidacja wykorzystania GPU

Po ustawieniu:

```text
OLLAMA_VULKAN=1
OLLAMA_IGPU_ENABLE=1
```

oraz restarcie Ollamy model został załadowany z następującym wynikiem:

```text
NAME           ID              SIZE     PROCESSOR         CONTEXT
qwen3.6:35b    07d35212591f    28 GB    4%/96% CPU/GPU    262144
```

Stan uznajemy za poprawny:

- **96% GPU**,
- **4% CPU**,
- model działa stabilnie,
- Qwen odpowiada przez lokalne API Ollamy.

To jest zwalidowany punkt odniesienia konfiguracji.

---

## 16. Kontekst modelu

Po poprawnym wykryciu dużej puli pamięci GPU Ollama uruchomiła model z:

```text
CONTEXT: 262144
```

czyli kontekstem 256k.

Na etapie 08.08.2026 podjęto decyzję:

- **nie ustawiać jeszcze globalnego ograniczenia `OLLAMA_CONTEXT_LENGTH`,**
- **nie rozdzielać jeszcze osobnych profili kontekstu dla wentylacji i CRT,**
- pozostawić działający model w obecnej konfiguracji,
- do profilowania kontekstu wrócić dopiero przy implementacji konkretnych adapterów AI Bridge.

W przyszłości wentylacja i CRT mogą otrzymać osobne ustawienia `num_ctx`, ale nie jest to część obecnej konfiguracji.

---

## 17. Benchmark Qwen 3.6 35B

Benchmark wykonano przez lokalne REST API Ollamy z wyłączonym `thinking`, aby mierzyć właściwą generację odpowiedzi.

Parametry testu:

- model: `qwen3.6:35b`,
- prompt: krótka odpowiedź po polsku,
- `stream=false`,
- `think=false`,
- GPU: 96% według `ollama ps`.

Wynik:

```text
Tokeny wyjściowe: 295
Czas generowania: 10.28 s
Prędkość: 28.68 tokenów/s
Całkowity czas: 10.69 s
Tokeny promptu: 32
```

Zwalidowana prędkość generowania:

> **28.68 tokenów/s**

Wynik jest wystarczający z dużym zapasem dla planowanych analiz danych wentylacji wykonywanych cyklicznie, np. co 15 minut.

Przykładowy sposób benchmarku:

```bash
curl -s http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"qwen3.6:35b",
    "prompt":"W trzech krótkich punktach opisz, dlaczego monitorowanie jakości powietrza jest ważne.",
    "stream":false,
    "think":false
  }' | python3 -c '
import sys,json
d=json.load(sys.stdin)
print("Tokeny wyjściowe:", d.get("eval_count"))
print("Czas generowania: %.2f s" % (d.get("eval_duration",0)/1e9))
print("Prędkość: %.2f tokenów/s" % (d.get("eval_count",0)/(d.get("eval_duration",1)/1e9)))
print("Całkowity czas: %.2f s" % (d.get("total_duration",0)/1e9))
print("Tokeny promptu:", d.get("prompt_eval_count"))
'
```

---

## 18. Aktualny stan usług

Docelowo aktywne i istotne dla bieżącego etapu są:

```text
ssh / sshd
cockpit.socket
docker
ollama
```

W chwili walidacji:

```text
Docker:          active
Ollama:          active + enabled
Cockpit socket:  active + enabled
SSH:             działa i przyjmuje połączenia
```

---

## 19. Komendy szybkiej diagnostyki

### Host

```bash
hostnamectl
free -h
lscpu
lsblk -o NAME,SIZE,MODEL,SERIAL,TYPE,FSTYPE,MOUNTPOINTS
ip -br address
```

### Usługi

```bash
systemctl is-active ssh
systemctl is-active cockpit.socket
systemctl is-active docker
systemctl is-active ollama
```

### Porty administracyjne

```bash
ss -ltn | grep -E ':(22|9090)\b'
```

### Docker

```bash
groups
docker ps
```

### Ollama

```bash
ollama --version
ollama list
ollama ps
```

### Środowisko usługi Ollama

```bash
systemctl show ollama --property=Environment
```

### Diagnostyka wykrywania GPU

```bash
journalctl -u ollama -b --no-pager | \
  grep -Ei 'vulkan|rocm|gpu|compute|device|runner|library|gfx|error' | tail -n 100
```

### Vulkan jako użytkownik Ollama

```bash
sudo -u ollama env HOME=/usr/share/ollama \
  vulkaninfo --summary | grep -Ei 'GPU[0-9]|deviceName|driverName'
```

---

## 20. Procedura odtworzenia krytycznej konfiguracji GPU

Jeżeli po aktualizacji lub reinstalacji model wróci do `100% CPU`:

1. Sprawdzić urządzenia:

```bash
ls -l /dev/kfd /dev/dri/renderD*
```

2. Sprawdzić grupy użytkownika Ollama:

```bash
id ollama
```

Oczekiwane grupy:

```text
video
render
```

3. Sprawdzić Vulkan jako użytkownik Ollama:

```bash
sudo -u ollama env HOME=/usr/share/ollama \
  vulkaninfo --summary | grep -Ei 'GPU[0-9]|deviceName|driverName'
```

4. Sprawdzić override:

```bash
cat /etc/systemd/system/ollama.service.d/vulkan.conf
```

Powinno zawierać:

```ini
[Service]
Environment="OLLAMA_VULKAN=1"
Environment="OLLAMA_IGPU_ENABLE=1"
```

5. Przeładować konfigurację:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

6. Uruchomić model i sprawdzić:

```bash
ollama run qwen3.6:35b
```

w drugim terminalu:

```bash
ollama ps
```

Punkt odniesienia:

```text
4%/96% CPU/GPU
```

---

## 21. Elementy celowo niekonfigurowane na tym etapie

Na 08.08.2026 świadomie **nie wykonano jeszcze**:

- podziału modelu/profili na osobny kontekst `ventilation` i `crt`,
- globalnego ograniczenia `OLLAMA_CONTEXT_LENGTH`,
- implementacji AI Bridge,
- implementacji adaptera `ventilation`,
- implementacji adaptera `crt`,
- docelowej bazy danych AI Bridge,
- docelowej polityki firewall/VPN dla dostępu spoza LAN,
- wystawienia API Ollamy do sieci LAN lub Internetu,
- migracji magazynu danych na NAS.

Te elementy wymagają osobnych etapów i decyzji projektowych.

---

## 22. Stan końcowy etapu

Na zakończenie etapu host jest gotowy jako platforma dla dalszej implementacji AI Bridge:

- Ubuntu 26.04 LTS działa stabilnie,
- zdalna administracja przez SSH działa,
- Cockpit działa i startuje automatycznie,
- Docker działa bez `sudo` dla użytkownika roboczego,
- Ollama działa jako usługa systemd,
- Qwen 3.6 35B jest zainstalowany,
- Radeon 890M jest wykrywany przez ROCm i Vulkan,
- iGPU jest jawnie dozwolone w Ollamie,
- model korzysta w ok. 96% z GPU,
- benchmark generacji wynosi ok. 28.68 tokenów/s,
- RDP/xrdp nie są częścią docelowego dostępu administracyjnego,
- obecna konfiguracja jest wystarczająca do rozpoczęcia implementacji warstwy aplikacyjnej AI Bridge.

**Checkpoint funkcjonalny:** Serwer AI jest dostępny z Windows 11 przez SSH/Cockpit, a lokalny Qwen 3.6 35B działa z akceleracją Radeon 890M.