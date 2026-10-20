# Vision RADIO — pilotaż GPU PASS i przygotowanie wdrożenia

20.10.2026. Pierwszy zaakceptowany pilot: 11:22 CEST. Wynik operatora zapisany w `VISION_RADIO_GPU_PILOT_RESULT_2026-10-20.json`.

## Potwierdzony wynik

- CPU konfiguracji ai-vision: PASS; odzyskanie znanej blokady: PASS, dowody zarchiwizowane.
- Dwie rzeczywiste inferencje na Radeon gfx1150, BDF 0000:c6:00.0: 7,180 s i 6,965 s z ładowaniem modelu.
- Ten sam obraz, score 0,43257656693458557 i identyczny SHA256 mapy 768×768 w obu wykonaniach. To test powtarzalności i integracji, nie ocena jakości detekcji.
- Sekwencje Ollama → Vision → Ollama i ComfyUI → Vision → ComfyUI: PASS. ComfyUI sprawdzono w zakresie lifecycle; generowania obrazu nie wykonywano.
- Gateway przywrócony. Odczyt hosta o 11:23:38 CEST: IDLE, active/queued/leases=0, admission_blocked=false, brak markera GPU, brak jednostek ai-radio, Ollama bez modeli, ComfyUI bez modeli/kolejki/cleanup_pending. KFD wskazywał wyłącznie dotychczasowy PID ComfyUI 267058. Brak dopasowanych błędów AMDGPU/MES w zbadanym dzienniku od 11:20 CEST.

Wynik JSON pochodzi z konsoli operatora; stan hosta sprawdzono dodatkowo odczytowo. Produkcyjne Vision nadal jest wyłączone przed wykonaniem komendy poniżej.

## Przygotowany zakres wdrożenia

Jeden istniejący Gateway/RM, jedna kolejka, cztery dotychczasowe stany, jeden nadzorowany worker. Aktywacja używa jawnego ustawienia `AI_BRIDGE_GATEWAY_VISION_RADIO_ENABLED=true`; domyślnie pozostaje false. Brak lub błąd nadzorcy przy włączonym ustawieniu odmawia startu Gateway. Wymagany jest pojedynczy slot RM.

Kandydat jest zbudowany z **obecnej produkcji**, przez przypięty patch dziewięciu plików Vision. Scheduler, GPUResidency, Platform API, benchmarki, domyślny model i pozostałe źródła zachowują produkcyjne bajty. Manifest obejmuje 239 plików źródeł i benchmarków. Zmiany DEV dotyczące N1–N5 nie są przenoszone.

Wykonawca pozostaje dokładnie pakietem przyjętym w pilocie: `/opt/ai-platform/vision-radio/releases/7cec662df1089831`; instalator sprawdza root-owned manifest, wszystkie pliki, jednostkę oraz bezpośredni link do tego samego interpretera. Etap dotyczy wykonawcy **przypiętego obrazu kalibracyjnego** `visa-pcb2-normal-0000`; rejestracja obrazów ze stanowiska nie jest dodawana przez to wdrożenie.

Nie zmienia się Stage O ani istniejący overlay. Nowy root-owned overlay i osobny drop-in pozwalają wrócić do obecnej wersji. Nie ma resetu sterownika ani zmiany uprawnień GPU.

## Walidacja pakietu

- DEV: **863 PASS**, 26 modułów, 6,92 s — `VISION_PRODUCTION_DEV_TESTS_2026-10-20.log`.
- Dokładny backport produkcyjny: **487 PASS**, 16 modułów, 4,85 s — `VISION_PRODUCTION_CANDIDATE_TESTS_2026-10-20.log`.
- Odczytowe odtworzenie pełnego kandydata, zgodność z manifestem, obecne usługi i źródła rollbacku: **SOURCE_AND_HOST_PREFLIGHT_PASS** — `VISION_PRODUCTION_PREFLIGHT_2026-10-20.json`.
- Testy obejmują domyślny brak aktywacji, odmowę bez nadzorcy i dla wielu slotów, ochronę źródeł poza Vision, odmowę po nieudanym pilocie, przełączenie → rollback → końcową aktywację i zachowanie aktywnej pracy przy wyścigu o okno.

Kontrole CPU nie zastępują odbioru GPU dokładnego backportu. Komenda operatora wykona ten odbiór przed zmianą produkcji. Nieudany pilot pozostawia dotychczasowy Gateway i wszystkie markery. Nieznany override lub aktywna praca blokuje automatyczne zatrzymanie/rollback; nadzorca pozostaje dostępny, gdy aktualny Gateway nadal go wymaga.

## Jedna komenda na AI Platform

```bash
sudo /usr/bin/python3 -I /srv/ai-data/evaluation/vision-engine-integration-20261020/tools/deploy_vision_radio.py --apply --manifest-sha256 5d9d267489609ccbd83bff7f06c7db1a919f6e3a3d56b19fa01c6d2a84bdc5e2
```

Kolejność: kontrola rootowego wyniku pilota i niezmienionego wykonawcy → niezmienny overlay → ponowny pilot GPU na dokładnym backporcie przy zatrzymanym poprzednim Gateway → przełączenie → smoke API/Control Center/benchmarków → sprawdzony rollback → ponowna aktywacja → włączenie startu nadzorcy przy boot. Wyłączny dostęp zapewniają istniejące leases; procedura odmawia zajęcia okna, jeśli inne zadanie je wyprzedzi.

Oczekiwany wynik: `VISION_PRODUCTION_PASS`, `candidate_gpu_pilot=PASS`, `rollback_test=PASS`, `production_install=PERFORMED`. Na dzień przygotowania pakietu tych wyników jeszcze nie ma.

Po wdrożeniu komenda awaryjnego powrotu zostanie podana jako `rollback_command`. Jest też stała dla tego pakietu:

```bash
sudo /usr/bin/python3 -I /opt/ai-platform/gateway-overlays/vision-radio-5d9d267489609ccb/tools/deploy_vision_radio.py --rollback --manifest-sha256 5d9d267489609ccbd83bff7f06c7db1a919f6e3a3d56b19fa01c6d2a84bdc5e2
```

Rootowy raport wdrożenia: `/var/lib/ai-platform-radio/DEPLOY_RESULT.json`. `GPU_REUSE_SAFE=NOT_VERIFIED`, N1=NOT_ADMITTED i ComfyUI generation=NOT_TESTED pozostają jawne; to wdrożenie nie wystawia globalnej zgody N1. Zdalny wykonawca blokuje sudo, więc przełączenie wymaga terminala operatora.
