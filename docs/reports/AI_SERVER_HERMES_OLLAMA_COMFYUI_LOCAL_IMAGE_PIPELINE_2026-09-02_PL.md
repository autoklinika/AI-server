# AI Server – Hermes, Ollama, ComfyUI/FLUX.2 i lokalna generacja obrazów przez Telegram

**Data:** 02.09.2026  
**Status:** stan wdrożony i zwalidowany na działającym Serwerze AI  
**Repozytorium:** `autoklinika/AI-server`  
**Zakres:** migracja Hermesa z NAS, trwałe utrzymywanie modelu Ollama, ComfyUI/ROCm, FLUX.2 Klein 4B, automatyczne przełączanie GPU, integracja Hermes + Telegram

> **Ważne:** dokument nie zawiera haseł, tokenów Telegrama, kluczy API ani identyfikatorów użytkowników. Repozytorium jest publiczne, dlatego dane uwierzytelniające i prywatne identyfikatory zostały świadomie pominięte. Sekretów nie wolno dodawać do repozytorium.

---

## 1. Cel dokumentu

Dokument zapisuje pełny stan wdrożenia warstwy lokalnego agenta i generowania obrazów na Serwerze AI po pracach wykonanych 02.09.2026.

Ma pełnić jednocześnie rolę:

- raportu wdrożeniowego,
- dokumentu architektury operacyjnej,
- punktu odtworzeniowego po awarii,
- handoffu do dalszych prac,
- listy zwalidowanych testów,
- rejestru znanych ograniczeń i ryzyk.

Zakres prac objął:

1. migrację Hermes Agent z kontenera Docker na QNAP do instalacji natywnej na Serwerze AI,
2. usunięcie Hermesa i jego zasobów z NAS,
3. konfigurację Ollamy tak, aby utrzymywała aktywny model bez timeoutu,
4. ograniczenie Ollamy do jednego modelu załadowanego jednocześnie,
5. automatyczny preload modelu domyślnego po restarcie hosta,
6. instalację ComfyUI na głównym dysku 4 TB,
7. instalację PyTorch/ROCm dla Radeon 890M (`gfx1150`),
8. instalację i walidację FLUX.2 Klein 4B FP8,
9. stworzenie konsolowego generatora obrazów,
10. automatyczne przełączanie GPU pomiędzy Qwen i FLUX,
11. wysyłkę wygenerowanego PNG do Telegrama,
12. stworzenie lokalnego skilla Hermesa do generowania obrazów,
13. natural-language routing: polecenie typu „wygeneruj obraz…” bez jawnego wywołania skilla,
14. konfigurację usług tak, aby cały zestaw działał po restarcie Serwera AI.

Generowanie i edycja wideo nie wchodzą w zakres tego wdrożenia. Do wideo zostanie wykorzystane inne rozwiązanie.

Edycja obrazu wejściowego przez FLUX.2 jest technicznie możliwa, ale **nie została jeszcze wdrożona** w opisanym etapie.

---

## 2. Wynik końcowy – streszczenie

Po zakończeniu prac Serwer AI działa według następującego modelu:

```text
START HOSTA
   |
   +--> ollama.service
   |       |
   |       +--> ollama-preload.service
   |               |
   |               +--> qwen3.6:35b-hermes64k
   |                       100% GPU
   |                       context 65536
   |                       Forever
   |
   +--> comfyui.service
   |       |
   |       +--> ComfyUI API :8188
   |
   +--> hermes-gateway.service (systemd --user)
           |
           +--> Telegram polling
```

Normalny stan spoczynkowy:

```text
Radeon 890M
   |
   +--> qwen3.6:35b-hermes64k
        100% GPU
        65536 context
        Forever
```

Przy żądaniu wygenerowania obrazu:

```text
Telegram
   |
   v
Hermes
   |
   v
local-image-generation
   |
   v
generate-image-telegram
   |
   v
generate-image
   |
   +--> unload bieżącego modelu Ollama
   |
   +--> ComfyUI / FLUX.2 Klein 4B
   |       |
   |       +--> generacja PNG
   |
   +--> ComfyUI /free
   |
   +--> preload qwen3.6:35b-hermes64k
   |
   v
Telegram <- wygenerowany PNG
```

Zwalidowany czas lokalnej generacji obrazu 1024×1024 wyniósł około **33–34 s**.

---

## 3. Host i stan bazowy

### 3.1. System

Zwalidowany host:

- hostname: `harrypotter-AI-Series`,
- system: **Ubuntu 26.04 LTS (Resolute Raccoon)**,
- kernel podczas wdrożenia: `7.0.0-30-generic`,
- architektura: `x86_64`,
- CPU: AMD Ryzen AI 9 HX 470,
- GPU/iGPU: **AMD Radeon 890M**, PCI raportowane jako `AMD Strix [Radeon 880M / 890M]`,
- target compute: **`gfx1150`**,
- pamięć fizyczna hosta: 128 GB RAM / UMA.

ComfyUI raportował podczas startu:

```text
Total VRAM 98304 MB, total RAM 31217 MB
Device: cuda:0 AMD Radeon 890M Graphics : native
AMD arch: gfx1150
DynamicVRAM support detected and enabled
```

Wartość `98304 MB VRAM` nie oznacza fizycznej, dedykowanej pamięci VRAM. Radeon 890M jest iGPU i korzysta z pamięci współdzielonej/UMA. ComfyUI/ROCm widzi dużą pulę pamięci dostępną dla GPU, a pozostała część jest raportowana jako RAM systemowy.

### 3.2. Dyski

Stan podczas wdrożenia:

#### Główny dysk 4 TB

- urządzenie: `SPCC M.2 PCIe SSD`,
- Linux: `/dev/nvme0n1`,
- partycja systemowa: `/dev/nvme0n1p2`,
- filesystem: `ext4`,
- mount: `/`,
- pojemność użytkowa: ok. 3,7 TB,
- na nim znajdują się system oraz instalacja ComfyUI i modele obrazu.

#### Dysk danych 1 TB

- urządzenie: `KINGSTON SNV3S1000G`,
- Linux podczas aktualnego audytu: `/dev/nvme1n1`,
- partycja: `/dev/nvme1n1p1`,
- filesystem: `ext4`,
- label: `AI_DATA`,
- mount: `/srv/ai-data`,
- opcja montowania: `noatime`.

Dysk ten był wcześniej zwalidowany testami nośnika i pozostaje trwałym magazynem danych.

W aktualnym układzie ComfyUI **nie trzyma modeli na dysku 1 TB**. Dla ComfyUI dysk 1 TB jest używany do plików wynikowych.

Jednocześnie Hermes został wcześniej przeniesiony na `/srv/ai-data/hermes`, dlatego dysk 1 TB zawiera także trwały katalog Hermesa. Decyzja „1 TB tylko do plików wyjściowych” dotyczyła layoutu danych ComfyUI, nie migracji Hermesa wykonanej wcześniej tego samego dnia.

---

## 4. Migracja Hermes Agent z QNAP na Serwer AI

### 4.1. Powód migracji

Hermes działał pierwotnie jako kontener Docker na QNAP `GlobalNAS`.

W praktyce agent generował i cache'ował istotną ilość danych roboczych, m.in. środowisko użytkownika, pakiety, przeglądarkę Playwright, cache i logi. Powodowało to niepotrzebne zaśmiecanie NAS i utrudniało rozdzielenie ról pomiędzy magazyn danych a host obliczeniowy.

Podjęto decyzję:

> Hermes ma działać bezpośrednio na Serwerze AI, tak samo jak Ollama i pozostałe mechanizmy AI. NAS nie ma być hostem wykonawczym Hermesa.

### 4.2. Stary kontener na NAS

Przed migracją potwierdzono:

- kontener: `hermes`,
- image: `nousresearch/hermes-agent:latest`,
- command: `gateway run`,
- `HERMES_HOME=/opt/data`,
- Docker volume: `hermes_data`,
- Docker network: `hermes_default`,
- Compose project: `hermes`,
- rozmiar obrazu Docker: ok. 2,68 GB,
- `/opt/data`: ok. 888 MB.

Największym elementem starego środowiska był runtime/home/cache, który **nie został przeniesiony**.

### 4.3. Archiwum migracyjne

Z kontenera utworzono kontrolowane archiwum:

```text
hermes-migration-20260902.tar.gz
```

SHA256 archiwum:

```text
5bb0e5ec1e80fdfc30d5b844e5c5ca429c45ca44364aea9b07664964e1ae5add
```

Archiwum obejmowało tylko dane potrzebne do zachowania konfiguracji i ciągłości działania:

- `.env`,
- `config.yaml`,
- `SOUL.md`,
- `auth.json`,
- `channel_directory.json`,
- `gateway_state.json`,
- `memories/`,
- `sessions/`,
- `cron/`,
- `pairing/`,
- `scripts/`.

Hash został zweryfikowany po kopiowaniu pomiędzy kontenerem, NAS i Serwerem AI.

### 4.4. Elementy celowo nieprzeniesione

Nie migrowano starego runtime'u:

- cache,
- logów,
- starego katalogu `home`,
- Playwright/browser cache,
- runtime locków,
- gateway PID/socket/lock,
- starych locków cron,
- generowanych JPG/HTML i innych śmieci roboczych,
- runtime `state.db`.

Celem było przeniesienie **tożsamości, konfiguracji i danych użytkowych**, a nie starego środowiska wykonawczego.

### 4.5. Nowy layout Hermesa

Hermes działa natywnie na Serwerze AI:

```text
/srv/ai-data/hermes/
├── hermes-agent/          # repo/kod Hermesa
├── cache/
│   ├── uv/
│   ├── npm/
│   ├── pip/
│   └── playwright/
├── memories/
├── sessions/
├── scripts/
├── skills/
├── config.yaml
├── .env
└── SOUL.md
```

Launcher:

```text
/home/harrypotter/.local/bin/hermes
```

Najważniejsze zmienne środowiskowe:

```text
HERMES_HOME=/srv/ai-data/hermes
UV_CACHE_DIR=/srv/ai-data/hermes/cache/uv
NPM_CONFIG_CACHE=/srv/ai-data/hermes/cache/npm
PIP_CACHE_DIR=/srv/ai-data/hermes/cache/pip
PLAYWRIGHT_BROWSERS_PATH=/srv/ai-data/hermes/cache/playwright
```

Weryfikacja wykazała, że `~/.hermes` nie jest używane jako faktyczny katalog danych – konfiguracja i dane pracują z `/srv/ai-data/hermes`.

### 4.6. Wersja i środowisko

W trakcie migracji:

- Hermes Agent: **v0.21.0 (2026.8.31)**,
- Python: **3.11.16**,
- OpenAI SDK: **2.24.0**,
- wymaganie projektu: Python `>=3.11,<3.14` – spełnione.

Repo Hermesa miało lokalny stan różniący się od upstream i było kilkanaście commitów za upstream. Aktualizacja nie została wykonywana automatycznie podczas migracji, aby nie mieszać dwóch zmian naraz: migracji platformy i upgrade'u agenta.

### 4.7. Telegram dependency

Doinstalowano wymagane zależności Telegrama do venv Hermesa:

```text
python-telegram-bot==22.8
tornado==6.5.8
```

Po instalacji `hermes doctor` wykrywał pakiet Telegrama poprawnie.

### 4.8. Konfiguracja modelu Hermesa

Model domyślny:

```text
qwen3.6:35b-hermes64k
```

Provider:

```text
custom / OpenAI-compatible Ollama endpoint
```

Hermes korzysta z lokalnej Ollamy na porcie `11434`.

Adres LAN i dane uwierzytelniające zostały celowo pominięte w raporcie publicznym.

### 4.9. Test modelu po migracji

Test jednorazowy Hermesa:

```text
hermes chat --oneshot --reasoning none -Q -q "..."
```

zakończył się prawidłową odpowiedzią i `exit code 0`.

Podczas wcześniejszego testu bez wyłączenia reasoning bardzo mały limit tokenów powodował pustą odpowiedź. Po użyciu `reasoning_effort=none` odpowiedź z lokalnej Ollamy była poprawna. Stała konfiguracja reasoning Hermesa nie została z tego powodu automatycznie zmieniona.

### 4.10. Gateway i autostart

Hermes Gateway został zainstalowany jako **systemd user service**:

```text
~/.config/systemd/user/hermes-gateway.service
```

Istotne parametry:

```text
ExecStart=/srv/ai-data/hermes/hermes-agent/venv/bin/python -m hermes_cli.main gateway run
WorkingDirectory=/srv/ai-data/hermes
Environment=HERMES_HOME=/srv/ai-data/hermes
Restart=always
RestartSec=5
```

Włączono linger użytkownika:

```text
Linger=yes
```

Dzięki temu usługa user-systemd może wystartować i działać po bootowaniu hosta bez interaktywnego logowania użytkownika.

### 4.11. Test po restarcie hosta

Po pełnym `sudo reboot` nie uruchamiano Hermesa ręcznie.

Telegram otrzymał poprawną odpowiedź z agenta, co zwalidowało:

- start systemd user manager,
- `hermes-gateway.service`,
- połączenie Telegram polling,
- połączenie z lokalną Ollamą,
- dostęp do modelu.

### 4.12. Sprzątanie NAS

Po udanym cutoverze usunięto z QNAP zasoby Hermesa:

- kontener `hermes`,
- volume `hermes_data`,
- network `hermes_default`,
- image `nousresearch/hermes-agent:latest`,
- tymczasowe archiwum migracyjne,
- nieużywany katalog starego Compose.

Końcowy audyt Docker potwierdził brak:

```text
Hermes container
Hermes volume
Hermes network
Hermes image
Compose directory
```

Nie wykonywano globalnego `docker prune`, ponieważ NAS ma inne ważne kontenery i nie wolno usuwać ich zasobów przypadkowo.

---

## 5. Ollama – polityka modelu rezydentnego

### 5.1. Problem początkowy

Domyślne zachowanie Ollamy powodowało zwolnienie modelu po kilku minutach bezczynności.

Przed zmianą:

```text
qwen3.6:35b-hermes64k
23 GB
100% GPU
CONTEXT 65536
UNTIL 4 minutes from now
```

Dla Hermesa i systemów korzystających z lokalnego AI oznaczało to niepotrzebne opóźnienie pierwszego zapytania po okresie bezczynności.

### 5.2. Cel

Przyjęta polityka:

1. domyślny Qwen ma być załadowany bezterminowo,
2. Ollama ma trzymać maksymalnie jeden model naraz,
3. gdy klient poprosi o inny model – stary ma zostać zwolniony i nowy załadowany,
4. ostatnio używany model może pozostać rezydentny,
5. po restarcie hosta ma automatycznie wrócić model domyślny Qwen3.6.

### 5.3. Konfiguracja systemd Ollamy

Utworzono drop-in:

```text
/etc/systemd/system/ollama.service.d/resident.conf
```

Treść logiczna:

```ini
[Service]
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
```

Istniejące ustawienia zachowano:

```text
OLLAMA_HOST=0.0.0.0:11434
OLLAMA_VULKAN=1
OLLAMA_IGPU_ENABLE=1
```

### 5.4. Preload modelu po bootowaniu

Utworzono skrypt:

```text
/usr/local/sbin/ollama-preload-qwen36
```

Skrypt:

- czeka na dostępność API Ollamy,
- wysyła żądanie load dla `qwen3.6:35b-hermes64k`,
- używa `keep_alive=-1`,
- kończy się sukcesem po załadowaniu modelu.

Utworzono usługę:

```text
/etc/systemd/system/ollama-preload.service
```

Typ:

```text
oneshot
```

Usługa jest `enabled` i uruchamia się po `ollama.service`.

### 5.5. Pierwsza awaria preload – przyczyna i poprawka

Pierwsza wersja `ExecStart` zawierała inline JSON w shellu. Quoting został zinterpretowany nieprawidłowo i API Ollamy zwróciło HTTP `400`.

Problem rozwiązano przez przeniesienie requestu do osobnego skryptu `/usr/local/sbin/ollama-preload-qwen36`.

Po poprawce:

```text
ollama-preload.service
status=0/SUCCESS
```

oraz:

```text
qwen3.6:35b-hermes64k ... Forever
```

### 5.6. Test automatycznego przełączania modeli

Zwalidowano sekwencję:

```text
qwen3.6:35b-hermes64k
100% GPU
65536
Forever
```

następnie request do:

```text
qwen3.8:27b-16k
```

wynik:

```text
qwen3.8:27b-16k
17 GB
100% GPU
16384
Forever
```

następnie ponowne wywołanie Qwen3.6:

```text
qwen3.6:35b-hermes64k
23 GB
100% GPU
65536
Forever
```

Test potwierdził, że przy `OLLAMA_MAX_LOADED_MODELS=1` Ollama prawidłowo przełącza model bez próby jednoczesnego utrzymywania dwóch dużych modeli.

### 5.7. Test po restarcie

Po pełnym restarcie Serwera AI:

```text
ollama.service              active
ollama-preload.service      active (exited), SUCCESS
qwen3.6:35b-hermes64k       100% GPU / 65536 / Forever
```

Cel został osiągnięty.

---

## 6. ComfyUI i ROCm na Radeon 890M

### 6.1. Założenie storage

Przyjęty finalny layout:

```text
4 TB / root filesystem
└── /opt/comfyui
    ├── ComfyUI/               # kod aplikacji
    ├── venv/                  # Python + PyTorch/ROCm
    └── data/
        ├── models/            # modele obrazu
        ├── input/
        ├── temp/
        └── user/              # workflow, Manager, baza/user data

1 TB /srv/ai-data
└── comfyui-output/            # obrazy wynikowe
```

Dla ComfyUI ciężkie modele są przechowywane na 4 TB. Dysk 1 TB jest wykorzystywany do outputu generacji.

### 6.2. Audyt przed instalacją

Potwierdzono:

```text
Python systemowy: 3.14.4
Git: 2.53.0
GPU: AMD Radeon 890M
/dev/kfd: dostępne
/dev/dri/renderD128: dostępne
użytkownik należy do grupy render
```

### 6.3. Instalacja

ComfyUI zainstalowano natywnie:

```text
/opt/comfyui/ComfyUI
```

Środowisko Python:

```text
/opt/comfyui/venv
```

Zainstalowany stack obliczeniowy:

```text
torch 2.13.0+rocm10.0.0
torchvision 0.28.0+rocm10.0.0
torchaudio 2.11.0.2+rocm10.0.0
```

Runtime PyTorch raportował:

```text
HIP: 7.15.26333
GPU available: True
GPU count: 1
GPU: AMD Radeon 890M Graphics
```

W logu ComfyUI runtime ROCm był raportowany jako:

```text
ROCm version: (7, 15)
AMD arch: gfx1150
```

Nazewnictwo pakietu `+rocm10.0.0` i runtime `HIP 7.15` należy traktować jako informacje z dwóch różnych warstw stacku AMD/PyTorch. Najważniejsza walidacja to faktyczne wykonanie obliczenia na GPU.

### 6.4. Test obliczeniowy GPU

Wykonano mnożenie macierzy 1024×1024 bezpośrednio na `torch.device("cuda")` – dla ROCm PyTorch używa API zgodnego z namespace CUDA.

Wynik:

```text
GPU: AMD Radeon 890M Graphics
matrix: (1024, 1024)
GPU MATMUL: PASS
```

To potwierdza faktyczne wykonywanie obliczeń przez GPU, a nie tylko wykrycie urządzenia.

### 6.5. ComfyUI runtime

Wersje podczas walidacji:

```text
ComfyUI 0.34.0
comfyui-frontend-package 1.51.9
comfyui-workflow-templates 0.11.52
comfy-kitchen 0.2.31
comfy-aimdo 0.4.15
```

Istotne logi:

```text
Device: cuda:0 AMD Radeon 890M Graphics : native
Using async weight offloading with 2 streams
Enabled pinned memory 23024
Using pytorch attention
DynamicVRAM support detected and enabled
```

Backend `hip` został wykryty jako dostępny i aktywny.

### 6.6. Manager

ComfyUI Manager działa w ramach instalacji i korzysta z:

```text
/opt/comfyui/data/user/__manager
```

Brak opcjonalnego `matrix-nio` był raportowany jako warning. Nie ma wpływu na lokalne generowanie FLUX i nie jest wymagany do obecnego zastosowania.

Brak `OpenGL_accelerate` również nie blokuje generacji obrazu.

---

## 7. ComfyUI jako usługa systemd

ComfyUI działa jako:

```text
comfyui.service
```

Stan końcowy został zwalidowany jako:

```text
active
```

Usługa uruchamia ComfyUI z parametrami odpowiadającymi finalnemu layoutowi:

```text
--listen 0.0.0.0
--port 8188
--enable-manager
--models-directory /opt/comfyui/data/models
--input-directory /opt/comfyui/data/input
--output-directory /srv/ai-data/comfyui-output
--temp-directory /opt/comfyui/data/temp
--user-directory /opt/comfyui/data/user
--disable-auto-launch
```

Dzięki systemd ComfyUI nie wymaga ręcznego uruchamiania po restarcie hosta.

### 7.1. Uwaga bezpieczeństwa

ComfyUI nasłuchuje na `0.0.0.0:8188`, czyli jest dostępne w sieci LAN zgodnie z routingiem/firewallem hosta.

To jest wygodne administracyjnie, ale należy traktować port 8188 jako interfejs zaufanej sieci lokalnej. Nie należy wystawiać go bezpośrednio do Internetu bez warstwy autoryzacji/reverse proxy/VPN.

Analogiczna uwaga dotyczy Ollamy na `0.0.0.0:11434`.

---

## 8. FLUX.2 Klein 4B – modele

### 8.1. Wybrany model

Do lokalnego text-to-image wybrano:

```text
FLUX.2 Klein 4B FP8 / distilled workflow
```

Model jest wystarczająco mały, aby sprawnie działać na obecnym APU, a jednocześnie daje sensowną jakość obrazów użytkowych.

### 8.2. Pliki modeli

#### Diffusion model

```text
/opt/comfyui/data/models/diffusion_models/flux-2-klein-4b-fp8.safetensors
```

Rozmiar raportowany przez system: ok. 3,8 GB.

SHA256:

```text
97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6
```

#### Text encoder

```text
/opt/comfyui/data/models/text_encoders/qwen_3_4b.safetensors
```

Rozmiar raportowany przez system: ok. 7,5 GB.

SHA256:

```text
6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a
```

#### VAE

```text
/opt/comfyui/data/models/vae/flux2-vae.safetensors
```

Rozmiar raportowany przez system: ok. 321 MB.

SHA256:

```text
d64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5
```

Wszystkie trzy sumy SHA256 zostały zweryfikowane jako `OK`.

Łączny katalog modeli po instalacji zajmował ok. 12 GB.

---

## 9. Problem z pierwszym workflow FLUX i jego rozwiązanie

### 9.1. Objaw

Pierwsza próba generacji z ręcznie wybranym workflow kończyła się błędem:

```text
RuntimeError: mat1 and mat2 shapes cannot be multiplied (512x2560 and 7680x3072)
```

Błąd pojawiał się przy pierwszym kroku samplera.

### 9.2. Przyczyna

Nie był to problem GPU, ROCm ani uszkodzonych wag.

Nieprawidłowy graf używał m.in.:

```text
CLIP type = lumina2
ModelSamplingAuraFlow
EmptySD3LatentImage
```

To nie odpowiadało wymaganiom FLUX.2 Klein.

### 9.3. Poprawny workflow

Wykorzystano oficjalny template:

```text
image_flux2_klein_text_to_image.json
```

W jego definicjach znajdują się dwa warianty:

```text
Text to Image (Flux.2 Klein 4B)
Text to Image (Flux.2 Klein 4B Distilled)
```

Zapisano lokalną wersję:

```text
/opt/comfyui/data/user/default/workflows/flux2-klein-4b-distilled-local.json
```

W niej:

- Base został wyłączony,
- Distilled został włączony,
- `UNETLoader` wskazuje `flux-2-klein-4b-fp8.safetensors`,
- `CLIPLoader` wskazuje `qwen_3_4b.safetensors`, typ **`flux2`**, device `default`,
- `VAELoader` wskazuje `flux2-vae.safetensors`,
- latent: `EmptyFlux2LatentImage`,
- scheduler: `Flux2Scheduler`,
- kroki: 4 w distilled subgraph.

Walidacja zapisanego workflow:

```text
EmptyFlux2LatentImage: [1024, 1024, 1]
UNETLoader: ['flux-2-klein-4b-fp8.safetensors', 'default']
CLIPLoader: ['qwen_3_4b.safetensors', 'flux2', 'default']
VAELoader: ['flux2-vae.safetensors']
Flux2Scheduler: [4, 1024, 1024]
```

### 9.4. Ostateczna decyzja

Do normalnego działania nie polegamy na stanie GUI ani na ręcznym otwieraniu workflow.

Produkcja obrazu jest wykonywana poprzez ComfyUI API z grafem zdefiniowanym przez skrypt `generate-image`.

GUI pozostaje narzędziem diagnostycznym i eksperymentalnym.

---

## 10. Pierwszy udany test FLUX przez API

Bezpośrednio przez endpoint ComfyUI `/prompt` wysłano prawidłowy workflow.

Wynik:

```text
COMPLETE: 33.0 s
IMAGE: /srv/ai-data/comfyui-output/Flux2-Klein-test_00001_.png
```

Obraz był prawidłowy i wizualnie użyteczny.

Test potwierdził jednocześnie:

- poprawny stack PyTorch/ROCm,
- poprawny FLUX.2 Klein FP8,
- poprawny Qwen3 4B text encoder,
- poprawny VAE,
- działanie API ComfyUI,
- zapis PNG na dysku 1 TB.

---

## 11. `generate-image` – docelowy lokalny generator

### 11.1. Lokalizacja

```text
/usr/local/bin/generate-image
```

### 11.2. Interfejs

Podstawowe użycie:

```bash
generate-image "opis obrazu"
```

Opcje:

```text
--width WIDTH
--height HEIGHT
--seed SEED
```

Domyślnie:

```text
1024 x 1024
```

Wymiary muszą być podzielne przez 16.

### 11.3. Parametry workflow

Generator używa:

```text
UNET: flux-2-klein-4b-fp8.safetensors
CLIP: qwen_3_4b.safetensors
CLIP type: flux2
VAE: flux2-vae.safetensors
CFG: 1.0
sampler: euler
scheduler: Flux2Scheduler
steps: 4
latent: EmptyFlux2LatentImage
```

### 11.4. Zarządzanie GPU

Skrypt realizuje cały cykl automatycznie:

1. sprawdza API ComfyUI,
2. pobiera listę aktywnych modeli Ollamy,
3. wykonuje `ollama stop` dla aktywnych modeli,
4. wywołuje ComfyUI `/free`,
5. wysyła job FLUX przez `/prompt`,
6. odpytuje `/history/<prompt_id>`,
7. zapisuje/odczytuje ścieżkę obrazu,
8. po zakończeniu wywołuje `/free`,
9. przywraca `qwen3.6:35b-hermes64k` przez `/usr/local/sbin/ollama-preload-qwen36`,
10. pokazuje końcowy `ollama ps`.

### 11.5. Lock

Generator korzysta z blokady:

```text
/tmp/generate-image.lock
```

z `fcntl.flock()`.

Oznacza to, że dwie równoległe instancje **tego samego generatora obrazów** nie wykonują właściwej sekcji jednocześnie – druga czeka na lock.

Nie jest to jednak jeszcze centralny scheduler wszystkich zadań AI. Patrz sekcja „Znane ograniczenia”.

### 11.6. Przywracanie Qwena po błędzie

Kluczowe operacje restore znajdują się w `finally`, dzięki czemu zwykły wyjątek lub błąd generacji powinien zakończyć się próbą:

```text
free ComfyUI
restore qwen3.6
```

Hard kill procesu (`kill -9`), crash interpretera lub reset hosta może ominąć `finally`. W takim przypadku Qwen wróci po restarcie dzięki `ollama-preload.service`, a ręcznie można wykonać:

```bash
sudo /usr/local/sbin/ollama-preload-qwen36
```

### 11.7. Zwalidowany test końcowy

Polecenie produkcyjne wygenerowało obraz w:

```text
34.0 s
```

Po zakończeniu:

```text
qwen3.6:35b-hermes64k
23 GB
100% GPU
CONTEXT 65536
Forever
```

Czyli pełny cykl:

```text
Qwen -> FLUX -> Qwen
```

został potwierdzony praktycznie.

---

## 12. Wysyłka obrazów na Telegram

### 12.1. Native `MEDIA:` Hermesa

Hermes potrafi wysłać lokalny plik jako media przez zapis:

```text
MEDIA:/absolute/path/to/file.png
```

Test istniejącego obrazu zakończył się poprawną dostawą PNG na Telegram.

### 12.2. Dlaczego powstał wrapper

Pierwsza wersja skilla generowała obraz prawidłowo, ale model językowy nie zawsze zwracał końcową odpowiedź w formacie `MEDIA:`. Potrafił opisać ścieżkę tekstowo zamiast przekazać plik.

Aby usunąć tę niedeterministyczność, wysyłka została przeniesiona z decyzji LLM do deterministycznego wrappera.

---

## 13. `generate-image-telegram`

### 13.1. Lokalizacja

```text
/usr/local/bin/generate-image-telegram
```

### 13.2. Działanie

Wrapper:

1. uruchamia `/usr/local/bin/generate-image`,
2. przechwytuje stdout,
3. parsuje linię:

```text
Image : /absolute/path.png
```

4. sprawdza, czy plik istnieje,
5. wywołuje Hermesa:

```text
hermes send --to telegram "... MEDIA:/absolute/path.png"
```

6. potwierdza:

```text
TELEGRAM_MEDIA_SENT: /absolute/path.png
```

### 13.3. Test

Bez udziału Qwena uruchomiono wrapper z promptem testowym.

Wynik:

- obraz został wygenerowany lokalnie,
- Qwen został przywrócony do GPU,
- Telegram otrzymał PNG jako rzeczywisty obraz/załącznik.

---

## 14. Hermes skill `local-image-generation`

### 14.1. Lokalizacja

```text
/srv/ai-data/hermes/skills/creative/local-image-generation/SKILL.md
```

### 14.2. Rejestracja

`hermes skills list` wykazał:

```text
local-image-generation | creative | local | local | enabled
```

Czyli skill jest lokalny, aktywny i wykrywany przez Hermesa.

### 14.3. Zasada użycia

Skill jest przeznaczony dla żądań typu:

- wygeneruj obraz,
- stwórz grafikę,
- narysuj,
- wyrenderuj,
- pokaż wizualizację,
- stwórz realistyczny obraz.

Nie wymaga jawnego `/local-image-generation` w normalnej rozmowie.

### 14.4. Wykonywany program

Skill został ustawiony tak, aby używał:

```text
/usr/local/bin/generate-image-telegram
```

W efekcie wysyłka PNG nie zależy od tego, czy LLM poprawnie zapisze `MEDIA:` w swojej odpowiedzi końcowej.

### 14.5. Natural-language routing

Zwalidowano wiadomość Telegram wysłaną bez nazwy skilla, np. w formie:

```text
Wygeneruj realistyczny obraz zielonego sterownika ECU na stole w nowoczesnym warsztacie elektronicznym.
```

Hermes sam:

1. rozpoznał potrzebę generacji obrazu,
2. wczytał `local-image-generation`,
3. uruchomił lokalny generator,
4. doprowadził do wygenerowania obrazu,
5. wysłał PNG na Telegram.

To potwierdza działanie etapu „naturalne polecenie -> lokalny FLUX”.

---

## 15. Ograniczenie technicznych komunikatów Hermesa na Telegramie

Aby w normalnym użyciu nie eksponować użytkownikowi szczegółów typu:

```text
Reading skill...
terminal
Bash
argumenty narzędzia
```

skonfigurowano wyciszenie tool progress i streamingu odpowiedzi pośrednich.

Docelowa konfiguracja logiczna:

```yaml
display:
  tool_progress: "off"
  tool_progress_command: false

gateway:
  streaming:
    enabled: true
    transport: off
```

Po zmianie zrestartowano `hermes-gateway.service`.

Użytkownik potwierdził zachowanie jako poprawne w normalnym użyciu.

Jeżeli po przyszłej aktualizacji Hermesa komunikaty techniczne wrócą, należy w pierwszej kolejności zweryfikować właśnie te klucze w:

```text
/srv/ai-data/hermes/config.yaml
```

---

## 16. Finalny test end-to-end przez Telegram

Końcowy test odbył się bez ręcznego wywołania skilla.

Łańcuch:

```text
Telegram
   |
   | naturalne polecenie po polsku
   v
Hermes Gateway
   |
   v
Qwen3.6
   |
   | automatyczne rozpoznanie skilla
   v
local-image-generation
   |
   v
generate-image-telegram
   |
   v
generate-image
   |
   +--> Ollama/Qwen unload
   |
   +--> FLUX.2 Klein 4B przez ComfyUI
   |
   +--> PNG /srv/ai-data/comfyui-output
   |
   +--> ComfyUI free
   |
   +--> Qwen preload / Forever
   |
   v
Hermes send MEDIA
   |
   v
Telegram – obraz
```

Wynik został zaakceptowany jako działający.

---

## 17. Autostart całego stacku po restarcie

Końcowy audyt usług wykazał:

```text
===== OLLAMA =====
active

===== PRELOAD =====
active

===== COMFYUI =====
active

===== HERMES =====
active

===== OLLAMA MODEL =====
qwen3.6:35b-hermes64k
23 GB
100% GPU
65536
Forever
```

To jest oczekiwany stan produkcyjny.

### 17.1. Elementy trwałe

Po restarcie mają wstać automatycznie:

- `ollama.service`,
- `ollama-preload.service`,
- `comfyui.service`,
- user service `hermes-gateway.service`,
- model `qwen3.6:35b-hermes64k`,
- Telegram gateway,
- skill `local-image-generation`.

### 17.2. Dlaczego Hermes user service wstaje bez logowania

Ponieważ dla użytkownika włączono:

```text
Linger=yes
```

---

## 18. Aktualna architektura storage

### 18.1. 4 TB – kod, runtime i modele ComfyUI

```text
/opt/comfyui/
├── ComfyUI/
├── venv/
└── data/
    ├── models/
    │   ├── diffusion_models/
    │   │   └── flux-2-klein-4b-fp8.safetensors
    │   ├── text_encoders/
    │   │   └── qwen_3_4b.safetensors
    │   └── vae/
    │       └── flux2-vae.safetensors
    ├── input/
    ├── temp/
    └── user/
        └── default/workflows/
            └── flux2-klein-4b-distilled-local.json
```

### 18.2. 1 TB – output ComfyUI oraz Hermes

```text
/srv/ai-data/
├── comfyui-output/
│   └── Flux2-Klein_*.png
└── hermes/
    ├── hermes-agent/
    ├── cache/
    ├── memories/
    ├── sessions/
    ├── skills/
    ├── config.yaml
    └── ...
```

---

## 19. Aktualna architektura usług

```text
systemd system
├── ollama.service
│   ├── override.conf
│   ├── vulkan.conf
│   └── resident.conf
│
├── ollama-preload.service
│   └── /usr/local/sbin/ollama-preload-qwen36
│
└── comfyui.service
    └── /opt/comfyui/venv/bin/python ... main.py :8188

systemd --user
└── hermes-gateway.service
    └── Hermes Telegram gateway
```

Narzędzia lokalne:

```text
/usr/local/bin/generate-image
/usr/local/bin/generate-image-telegram
/home/harrypotter/.local/bin/hermes
```

---

## 20. Komendy diagnostyczne

### 20.1. Cały stack

```bash
echo "===== OLLAMA ====="
systemctl is-active ollama

echo "===== PRELOAD ====="
systemctl is-active ollama-preload.service

echo "===== COMFYUI ====="
systemctl is-active comfyui.service

echo "===== HERMES ====="
systemctl --user is-active hermes-gateway.service

echo "===== MODEL ====="
ollama ps
```

### 20.2. Ollama

```bash
systemctl status ollama --no-pager -l
systemctl show ollama -p Environment --no-pager
ollama ps
ollama list
```

### 20.3. Preload

```bash
systemctl status ollama-preload.service --no-pager -l
journalctl -u ollama-preload.service -b --no-pager
sudo /usr/local/sbin/ollama-preload-qwen36
```

### 20.4. ComfyUI

```bash
systemctl status comfyui.service --no-pager -l
journalctl -u comfyui.service -b --no-pager
curl -fsS http://127.0.0.1:8188/system_stats
```

### 20.5. Hermes

```bash
systemctl --user status hermes-gateway.service --no-pager -l
journalctl --user -u hermes-gateway.service -b --no-pager
hermes gateway status
hermes doctor
hermes skills list
```

### 20.6. Generator obrazu

```bash
generate-image "Photorealistic automotive ECU on a workshop bench"
```

### 20.7. Generator + Telegram

```bash
generate-image-telegram "Photorealistic automotive ECU on a workshop bench"
```

### 20.8. Output

```bash
find /srv/ai-data/comfyui-output -type f -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n' | sort | tail
```

---

## 21. Procedura awaryjna – Qwen nie wrócił po generacji

Sprawdzić:

```bash
ollama ps
```

Jeżeli lista jest pusta:

```bash
sudo /usr/local/sbin/ollama-preload-qwen36
ollama ps
```

Oczekiwane:

```text
qwen3.6:35b-hermes64k ... 100% GPU ... 65536 ... Forever
```

Jeżeli preload nie działa:

```bash
systemctl status ollama --no-pager -l
journalctl -u ollama -b --no-pager | tail -100
curl -fsS http://127.0.0.1:11434/api/version
```

---

## 22. Procedura awaryjna – ComfyUI nie odpowiada

```bash
systemctl status comfyui.service --no-pager -l
journalctl -u comfyui.service -b --no-pager | tail -150
curl -fsS http://127.0.0.1:8188/system_stats
```

Restart:

```bash
sudo systemctl restart comfyui.service
```

Sprawdzić modele:

```bash
ls -lh /opt/comfyui/data/models/diffusion_models/
ls -lh /opt/comfyui/data/models/text_encoders/
ls -lh /opt/comfyui/data/models/vae/
```

W razie podejrzenia uszkodzenia pliku można ponownie zweryfikować SHA256 wartościami zapisanymi w sekcji 8.

---

## 23. Procedura awaryjna – Hermes nie odpowiada na Telegramie

```bash
systemctl --user status hermes-gateway.service --no-pager -l
journalctl --user -u hermes-gateway.service -b --no-pager | tail -150
hermes doctor
ollama ps
```

Restart gateway:

```bash
systemctl --user restart hermes-gateway.service
```

Sprawdzić:

```bash
loginctl show-user "$USER" -p Linger
```

Oczekiwane:

```text
Linger=yes
```

Nie publikować w logach/repo tokena Telegrama ani zawartości `.env`.

---

## 24. Procedura awaryjna – Telegram nie dostaje obrazu

Najpierw ominąć LLM i przetestować wrapper:

```bash
generate-image-telegram "blue ECU on electronics workshop bench"
```

Jeżeli obraz powstaje, ale Telegram go nie dostaje, sprawdzić ręcznie transport Hermesa z istniejącym plikiem:

```text
hermes send --to telegram "MEDIA:/absolute/path/to/test.png"
```

Jeżeli to działa, problem leży w wrapperze/parsing ścieżki lub w skill routing, a nie w Telegram transport.

---

## 25. Znane ograniczenia i ryzyka

### 25.1. Brak centralnego arbitra GPU / kolejki priorytetowej

Obecny `generate-image` ma lokalny lock i potrafi sam przełączyć Qwen -> FLUX -> Qwen.

To **nie jest** jednak pełny centralny scheduler wszystkich zadań AI.

Nie rozwiązuje jeszcze ogólnego problemu:

- wiele niezależnych klientów Ollamy,
- Hermes,
- analiza wentylacji,
- generowanie obrazów,
- przyszłe zadania okresowe,
- różne priorytety krytyczności.

Dla docelowej architektury nadal potrzebny jest centralny zarządca/kolejka, w której np. analiza krytyczna wentylacji ma wyższy priorytet niż generowanie grafiki.

### 25.2. `OLLAMA_MAX_LOADED_MODELS=1` nie jest globalnym schedulerem

Ustawienie ogranicza liczbę modeli w Ollamie, ale nie koordynuje ComfyUI ani zewnętrznych procesów ROCm.

`generate-image` wykonuje koordynację ręcznie na poziomie skryptu.

### 25.3. Hard kill może ominąć restore

`finally` w `generate-image` chroni przed zwykłymi błędami, ale nie przed `SIGKILL`, awarią hosta lub twardym resetem.

Po reboot Qwen wraca przez preload service.

### 25.4. ComfyUI raportuje „VRAM” jako UMA

`98304 MB VRAM` nie może być interpretowane jak 96 GB pamięci na dedykowanej karcie.

Wydajność i stabilność trzeba oceniać praktycznymi testami modeli.

### 25.5. Aktualny wrapper Telegram kieruje obraz do home channel

To ważne ograniczenie dla przyszłej obsługi wielu użytkowników.

`generate-image-telegram` używa:

```text
hermes send --to telegram ...
```

co w obecnej konfiguracji wysyła do skonfigurowanego **Telegram home channel**.

Dla pojedynczego operatora działa poprawnie i zostało zwalidowane.

Dla dwóch lub większej liczby użytkowników może być niewystarczające, ponieważ odpowiedź powinna wrócić dokładnie do czatu/użytkownika, który zlecił generację.

Przed uznaniem funkcji za multi-user production należy zmienić delivery tak, aby zachowywało kontekst originating chat/session zamiast zawsze używać home channel.

### 25.6. Kolejkowanie wrappera obejmuje tylko generację obrazów

`/tmp/generate-image.lock` serializuje instancje generatora obrazów, ale nie daje priorytetów i nie blokuje innych procesów przed bezpośrednim użyciem GPU.

### 25.7. Image editing jeszcze nie istnieje jako gotowa ścieżka

FLUX.2 może obsługiwać pracę z obrazem wejściowym, ale nie utworzono jeszcze:

```text
generate-image-edit
local-image-editing skill
Telegram image -> local input -> edited PNG
```

To jest osobny następny etap.

### 25.8. Wideo poza zakresem

Nie należy rozszerzać tego pipeline'u o wideo automatycznie. Dla wideo ma zostać wybrane inne rozwiązanie/model/pipeline.

### 25.9. Publicznie dostępne usługi w LAN

Ollama i ComfyUI nasłuchują na `0.0.0.0`.

Nie należy wystawiać portów 11434 i 8188 bezpośrednio do Internetu.

---

## 26. Priorytetowe następne kroki

### P0 – zachować obecny stabilny stan

Nie zmieniać jednocześnie:

- wersji Hermesa,
- stacku ROCm/PyTorch,
- ComfyUI,
- skryptów przełączania GPU,

bez osobnej gałęzi/testu i planu rollback.

### P1 – centralny Resource Manager / kolejka AI

Docelowo wszystkie obciążenia AI powinny przechodzić przez jeden arbitraż zasobów:

```text
AI Resource Manager
├── priority 100: zadania bezpieczeństwa / wentylacja
├── priority 80: analizy systemowe
├── priority 50: interaktywne pytania Hermes
└── priority 20: generowanie obrazów
```

Powinien kontrolować co najmniej:

- aktywny model,
- GPU ownership,
- queue,
- priorytet,
- preemption lub bezpieczne oczekiwanie,
- timeout,
- retry,
- status zadania,
- użytkownika/źródło żądania.

### P1 – poprawny routing multi-user Telegram

Należy usunąć zależność od home channel w `generate-image-telegram` i zwracać plik do originating Telegram chat/session.

To jest szczególnie ważne przed regularnym użyciem przez więcej niż jednego operatora.

### P2 – lokalna edycja obrazów

Planowana ścieżka:

```text
Telegram image + instrukcja
-> Hermes
-> local-image-editing
-> generate-image-edit
-> FLUX.2 image edit
-> PNG
-> originating chat
```

Powinna używać tego samego mechanizmu Qwen -> FLUX -> Qwen.

### P2 – monitoring usług

Warto dodać kontrolę:

- `ollama.service`,
- `ollama-preload.service`,
- `comfyui.service`,
- `hermes-gateway.service`,
- dostępność `/api/version`,
- dostępność `/system_stats`,
- ostatnia udana generacja,
- wykorzystanie miejsca `/srv/ai-data/comfyui-output`.

### P3 – retention outputów

Wraz ze wzrostem liczby obrazów trzeba ustalić:

- retencję,
- katalogowanie per projekt/użytkownik,
- ewentualne przenoszenie archiwalnych obrazów do NAS.

---

## 27. Minimalna checklista po przyszłym restarcie

```bash
systemctl is-active ollama
systemctl is-active ollama-preload.service
systemctl is-active comfyui.service
systemctl --user is-active hermes-gateway.service
ollama ps
curl -fsS http://127.0.0.1:8188/system_stats >/dev/null && echo COMFYUI_OK
```

Oczekiwane:

```text
ollama: active
preload: active/exited success
comfyui: active
hermes: active
qwen3.6:35b-hermes64k: 100% GPU, 65536, Forever
COMFYUI_OK
```

Następnie test funkcjonalny na Telegramie:

```text
Wygeneruj realistyczny obraz sterownika ECU na stole warsztatowym.
```

Oczekiwany rezultat:

- skill wybiera się automatycznie,
- generacja trwa około kilkudziesięciu sekund,
- obraz trafia na Telegram,
- `ollama ps` po operacji ponownie pokazuje Qwen3.6 jako `Forever`.

---

## 28. Stan końcowy na 02.09.2026

### Hermes

**DZIAŁA**

- natywna instalacja na Serwerze AI,
- dane trwałe na `/srv/ai-data/hermes`,
- Telegram Gateway działa,
- start po boot zwalidowany,
- lokalny skill generowania obrazu działa,
- natural-language routing działa.

### Ollama

**DZIAŁA**

- `qwen3.6:35b-hermes64k` jest modelem domyślnym,
- 100% GPU,
- context 65536,
- `Forever`,
- jeden model jednocześnie,
- przełączanie Qwen3.6 <-> inny model zwalidowane,
- preload po boot zwalidowany.

### ComfyUI

**DZIAŁA**

- instalacja na 4 TB,
- Radeon 890M / gfx1150,
- PyTorch/ROCm GPU compute zwalidowany,
- API i GUI działają,
- systemd autostart aktywny.

### FLUX.2 Klein 4B

**DZIAŁA**

- pliki modeli zweryfikowane SHA256,
- prawidłowy workflow `flux2`,
- obraz 1024×1024 generuje się lokalnie,
- praktyczny czas ok. 33–34 s.

### GPU handoff

**DZIAŁA**

```text
Qwen -> unload -> FLUX -> free -> Qwen preload -> Forever
```

### Telegram delivery

**DZIAŁA dla obecnego home channel**

- obraz jest wysyłany jako media,
- skill może być wywołany naturalnym tekstem,
- wymagane jest dalsze dopracowanie do pełnego multi-user routing.

### NAS

**HERMES USUNIĘTY**

- brak starego kontenera,
- brak volume,
- brak network,
- brak image Hermesa.

---

## 29. Wniosek

Etap zakończył się pełnym uruchomieniem lokalnego, samowystarczalnego pipeline'u tekst + obraz na Serwerze AI.

Serwer potrafi teraz:

1. stale utrzymywać główny Qwen w pamięci GPU,
2. obsługiwać Hermesa przez Telegram,
3. automatycznie rozpoznawać żądania generacji obrazu,
4. tymczasowo zwolnić Qwen,
5. lokalnie wygenerować obraz przez FLUX.2 Klein i ComfyUI,
6. zwolnić zasoby generatora,
7. automatycznie przywrócić Qwen,
8. wysłać gotowy PNG na Telegram,
9. odtworzyć cały runtime automatycznie po restarcie hosta.

Najważniejszym kolejnym krokiem architektonicznym nie jest dodawanie kolejnych modeli, tylko **centralny zarządca zasobów i kolejka priorytetowa**, szczególnie przed równoczesnym użyciem przez wielu użytkowników oraz system wentylacji.

Obecny pipeline generowania obrazów jest gotowy do dalszego użycia i rozwijania, z jasno zapisanymi ograniczeniami dotyczącymi multi-user delivery i centralnego arbitrażu GPU.
