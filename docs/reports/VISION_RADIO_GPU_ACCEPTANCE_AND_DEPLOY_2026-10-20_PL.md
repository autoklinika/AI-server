# Vision RADIO — wdrożenie produkcyjne PASS

20.10.2026, odbiór o 12:02 CEST. **VISION_PRODUCTION_PASS**: dokładny kandydat przeszedł ponowny pilot GPU, wdrożenie, test rollbacku i końcową aktywację. Brakujący wykonawca RADIO jest dostępny w produkcyjnym Gateway.

## Potwierdzony wynik

- `candidate_gpu_pilot=PASS`, `production_install=PERFORMED`, `rollback_test=PASS` — [wynik wdrożenia](VISION_PRODUCTION_RESULT_2026-10-20.json).
- Dwie rzeczywiste inferencje dokładnego backportu na Radeon gfx1150, BDF 0000:c6:00.0: 6,755 s i 6,991 s z ładowaniem modelu — [pilot produkcyjnego kandydata](VISION_PRODUCTION_GPU_PILOT_RESULT_2026-10-20.json), zakończony o 12:01:26 CEST.
- Ten sam obraz, score 0,43257656693458557 i identyczny SHA256 mapy 768×768 w obu wykonaniach. To test powtarzalności i integracji, nie ocena jakości detekcji.
- Sekwencje Ollama → Vision → Ollama i ComfyUI → Vision → ComfyUI: PASS. ComfyUI sprawdzono w zakresie lifecycle; generowania obrazu nie wykonywano.
- Po końcowej aktywacji: Gateway i nadzorca RADIO aktywne, nadzorca włączony przy boot, Vision `execution_available=true`. RM: IDLE, active/queued/leases=0, admission_blocked=false; brak markera GPU i jednostek roboczych ai-radio. Ollama bez modeli, ComfyUI bez modeli/kolejki/cleanup_pending. `/api/tags`, `/api/v1/benchmarks` i `/control/`: HTTP 200.
- Wszystkie 239 plików produkcyjnego overlay zgodne z manifestem. Stage O nadal wskazuje `/opt/ai-platform/releases/stage-o-28e3ea214660`. KFD wskazywał wyłącznie dotychczasowy PID ComfyUI 267058; brak dopasowanych błędów sterownika w zbadanym dzienniku od 12:00 CEST — [odczyt hosta o 12:02:47 CEST](VISION_PRODUCTION_LIVE_ACCEPTANCE_2026-10-20.json).

Wyniki pilota i wdrożenia pochodzą z konsoli operatora; stan hosta sprawdzono dodatkowo odczytowo. Pierwszy zaakceptowany pilot o 11:22 CEST pozostaje zapisany osobno w `VISION_RADIO_GPU_PILOT_RESULT_2026-10-20.json`.

## Wdrożony zakres

Jeden istniejący Gateway/RM, jedna kolejka, cztery dotychczasowe stany, jeden nadzorowany worker. Aktywacja używa jawnego ustawienia `AI_BRIDGE_GATEWAY_VISION_RADIO_ENABLED=true`; domyślnie pozostaje false. Brak lub błąd nadzorcy przy włączonym ustawieniu odmawia startu Gateway. Wymagany jest pojedynczy slot RM.

Overlay jest zbudowany z **poprzedniej produkcji**, przez przypięty patch dziewięciu plików Vision. Scheduler, GPUResidency, Platform API, benchmarki, domyślny model i pozostałe źródła zachowują produkcyjne bajty. Manifest obejmuje 239 plików źródeł i benchmarków. Zmiany DEV dotyczące N1–N5 nie zostały przeniesione.

Wykonawca pozostaje dokładnie pakietem przyjętym w pilocie: `/opt/ai-platform/vision-radio/releases/7cec662df1089831`; instalator sprawdza root-owned manifest, wszystkie pliki, jednostkę oraz bezpośredni link do tego samego interpretera. Etap dotyczy wykonawcy **przypiętego obrazu kalibracyjnego** `visa-pcb2-normal-0000`; rejestracja obrazów ze stanowiska nie jest dodawana przez to wdrożenie.

Aktywny overlay: `/opt/ai-platform/gateway-overlays/vision-radio-5d9d267489609ccb`; drop-in: `/etc/systemd/system/ai-gateway.service.d/99-vision-radio.conf`. Stage O i poprzedni overlay pozostały zachowane. Nie wykonano resetu sterownika ani zmiany uprawnień GPU.

## Walidacja pakietu

- DEV: **863 PASS**, 26 modułów, 6,92 s — `VISION_PRODUCTION_DEV_TESTS_2026-10-20.log`.
- Dokładny backport produkcyjny: **487 PASS**, 16 modułów, 4,85 s — `VISION_PRODUCTION_CANDIDATE_TESTS_2026-10-20.log`.
- Odczytowe odtworzenie pełnego kandydata, zgodność z manifestem, obecne usługi i źródła rollbacku: **SOURCE_AND_HOST_PREFLIGHT_PASS** — `VISION_PRODUCTION_PREFLIGHT_2026-10-20.json`.
- Testy obejmują domyślny brak aktywacji, odmowę bez nadzorcy i dla wielu slotów, ochronę źródeł poza Vision, odmowę po nieudanym pilocie, przełączenie → rollback → końcową aktywację i zachowanie aktywnej pracy przy wyścigu o okno.

Dokładny backport przeszedł następnie rzeczywisty odbiór GPU i wdrożenie opisane powyżej. Preflight i logi CPU zachowują stan z czasu przygotowania pakietu.

## Wykonane wdrożenie i dostępny rollback

```bash
sudo /usr/bin/python3 -I /srv/ai-data/evaluation/vision-engine-integration-20261020/tools/deploy_vision_radio.py --apply --manifest-sha256 5d9d267489609ccbd83bff7f06c7db1a919f6e3a3d56b19fa01c6d2a84bdc5e2
```

Wykonana kolejność: kontrola rootowego wyniku pilota i niezmienionego wykonawcy → niezmienny overlay → ponowny pilot GPU na dokładnym backporcie przy zatrzymanym poprzednim Gateway → przełączenie → smoke API/Control Center/benchmarków → sprawdzony rollback → ponowna aktywacja → włączenie startu nadzorcy przy boot. Wyłączny dostęp zapewniają istniejące leases; procedura odmawia zajęcia okna, jeśli inne zadanie je wyprzedzi.

Wdrożenie jest zakończone; komendy `--apply` nie trzeba powtarzać. Komenda awaryjnego powrotu podana przez instalator:

```bash
sudo /usr/bin/python3 -I /opt/ai-platform/gateway-overlays/vision-radio-5d9d267489609ccb/tools/deploy_vision_radio.py --rollback --manifest-sha256 5d9d267489609ccbd83bff7f06c7db1a919f6e3a3d56b19fa01c6d2a84bdc5e2
```

Rootowy raport wdrożenia: `/var/lib/ai-platform-radio/DEPLOY_RESULT.json`. `GPU_REUSE_SAFE=NOT_VERIFIED`, N1=NOT_ADMITTED i ComfyUI generation=NOT_TESTED pozostają jawne; to wdrożenie nie wystawia globalnej zgody N1. Obsługa dowolnych obrazów ze stanowiska pozostaje poza odebranym zakresem.
