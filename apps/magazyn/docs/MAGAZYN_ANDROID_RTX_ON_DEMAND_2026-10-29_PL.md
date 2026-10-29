# Magazyn V1 Android — RTX na żądanie (29.10.2026)

## UI
W istniejącym formularzu Dodaj ECU dwie sąsiadujące ikony: AI i aparat. Pierwsza uruchamia preflight GPU + RM i przygotowanie modelu; druga otwiera natywny aparat. Bez włączonego AI aparat zawsze korzysta z OCR ML Kit.

Po kliknięciu AI paskiem pokazujemy prawdziwe etapy: weryfikacja zasobów, rezerwacja RM, załadowanie modelu na RTX, rozgrzewanie modułu obrazu i gotowość. W przypadku zajętych zasobów pokazujemy komunikat i przechodzimy na OCR telefonu, nie AMD. Nie zapisujemy automatycznie przyjęć magazynowych. Przycisk AI można wyłączyć; po zamknięciu formularza zwalniamy gotową sesję. Limit bezczynności: 120 s od aktywacji lub ostatniego skanowania.

## Integracja
- Backend: ecu_rtx.py, jeden proces Magazynu, jedna aktywna sesja na użytkownika z losowym identyfikatorem.
- Resource Manager: lokalny AI Gateway 127.0.0.1:11435; rezerwacja workload=llm, priority_class=background i heartbeat co 6 s.
- Model RTX: Qwen3-VL 8B Instruct przez osobną istniejącą Ollamę 127.0.0.1:11436 (CUDA), bez ponownej instalacji modelu i bez nowego schedulera.
- Preflight: RM llm/niezablokowany, brak aktywnej rezerwacji i kolejki; GPU 0 RTX 5060 Ti; nvidia-smi wolna VRAM co najmniej 8300 MiB (gdy model jeszcze nie jest załadowany), modele Ollamy /api/ps. Maksymalnie dwa modele rezydentne wg aktualnej konfiguracji RTX. Preflight jest ponawiany po przyznaniu rezerwacji RM.
- Model w pamięci: odczyt API generate z pustym promptem i keep_alive=3m; następnie rozgrzanie obrazu przez chat. Scan: chat na RTX, nigdy przez domyślną Ollamę AMD. Po zakończeniu: wyładuj model na RTX i zwolnij rezerwację RM.
- Tailscale HTTPS i istniejący CSRF/role/logowanie Magazynu. Zdjęcia w pamięci, nie są dopisywane do bazy.
- GET /api/ecu-label/status, POST /api/ecu-label/activate, POST /api/ecu-label/analyze (wymagany session_id), POST /api/ecu-label/deactivate. Starszy APK bez sesji wraca do OCR telefonu.

## Istotne ograniczenie RM
Obecny RM nie ma odrębnej atomowej rezerwacji pamięci RTX: istniejący globalny lease llm koordynuje wejście do platformy, a nvidia-smi i /api/ps są dodatkowymi zabezpieczeniami. Jeśli inny klient omija RM, stan GPU może zmienić się między pomiarem a startem; przy błędzie serwer fail-closed i telefon używa OCR. Globalny slot RM jest zajęty podczas gotowości AI, ale tylko do krótkiego timeoutu bezczynności.

## Test sprzętowy
29.10.2026: odizolowany TestClient Magazynu, aktywacja -> prawdziwy RM -> CUDA na RTX -> nagrzanie modelu -> analiza syntetycznej etykiety Bosch -> zamknięcie. Wynik: PASS. Przygotowanie ok. 10,57 s, pierwszy skan po przygotowaniu 1,545 s. Poprawny numer Bosch 0281016738, HW H1, SW S3, EDC17C46, brak zapisu bazy. Wcześniejszy benchmark świeżych obrazów: RTX 1,52 s średnio vs AMD 7,30 s, około 4,8 razy szybciej.

## Wdrożenie
Kod i APK wyłącznie na gałęzi DEV, z testami CI. Zalecany release addytywny Magazynu z zachowaniem bieżącej bazy/Telegram/Stage K i kontrolowanym restartem tylko WebGUI. Ostateczny odbiór wymaga skanu rzeczywistych etykiet na telefonie.
