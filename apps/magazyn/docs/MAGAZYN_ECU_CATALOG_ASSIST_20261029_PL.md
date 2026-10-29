# Magazyn V1 — porównanie odczytu ECU z aktualnym katalogiem

Data: 2026-10-29. Wersja Android DEV 0.4.0. Dotyczy formularza Dodaj sterownik ECU.

## Po co

Poprzedni mechanizm poprawnie rozdzielał transkrypcję AI na numer główny, OEM, HW/SW, nazwę i model, ale nie korzystał aktywnie z istniejącego katalogu Magazynu. Przy kilku numerach OEM dla jednego ECU prowadziło to do niekompletnych propozycji i ryzyka utworzenia dubla.

## Nowy przepływ

1. Android wykonuje zdjęcie. Zgodnie z obecną architekturą AI na RTX 5060 Ti rozpoznaje etykietę i zwraca uporządkowane pola, a OCR telefonu jest fallbackiem.
2. WebGUI wysyła do istniejącego Magazynu odczytane numery: główny, jawnie oznaczone OEM i numery niejednoznaczne (do 25), oraz kontekst: marka z etykiety, producent, model, HW, SW. Nie przekazuje obrazu do wyszukiwarki katalogowej.
3. Nowy POST /api/ecu-label/catalog-match (sesja + CSRF) przeprowadza wyłącznie SELECT na aktualnej bazie SQLite (item_numbers.normalized, indeks istnieje), bez udziału GPU i bez zmian tabel.
4. Serwer sprawdza dokładnie znormalizowane numery główne i aliasy OEM dla rodzaju ecu (nigdy nie dobiera produktów z kategorii elektronika). Porównuje również markę, producenta, model oraz HW/SW.
5. Wynik rozdziela stany: możliwy ten sam wariant (zgodne jawne numery, HW i SW), numer zgodny, ale wariant do zweryfikowania, oraz konflikt HW/SW/modelu/marki.
6. Podgląd Android pokazuje pasujące istniejące pozycje i różnice. Przy unikalnym mocnym dopasowaniu może zaproponować brakującą nazwę, producenta, model, kategorię lub markę na podstawie istniejącego katalogu. Wszystkie podpowiedzi z bazy pozostają nieoznaczone do zatwierdzenia.
7. NIGDY nie przenosimy HW/SW z innego sterownika do fotografowanego ECU; wszystkie dane odczytane z naklejki mają pierwszeństwo. Przy konflikcie nie proponujemy pól z innego wariantu.
8. Jeśli wykryto ten sam numer, HW i SW, przycisk Otwórz przyjęcie sztuk do istniejącej pozycji otwiera znany formularz przyjęcia zamiast tworzyć duplikat; zapis magazynowy nadal wymaga osobnego zatwierdzenia użytkownika.
9. Jeśli brak wyników, skaner nadal pokazuje własne propozycje OCR/AI. Brak możliwości korekty jednej nieczytelnej cyfry na podstawie podobieństwa: bez dowodów nie zmieniamy numerów.

## Bezpieczeństwo

- Nie ma nowych usług, schedulerów, GPU, zewnętrznych usług ani osobnej bazy.
- Endpoint wymaga uwierzytelnienia i CSRF; używa bieżących danych SQLite bez eksportu i bez odczytu notatek o numerach seryjnych.
- Dokładne dopasowanie numeru nie dowodzi tożsamości wariantu. Bez jednoczesnego potwierdzenia HW i SW status jest verify_variant i żadne uzupełnienie nie następuje automatycznie.
- Odczyt i katalog są oddzielnymi źródłami; poprawność zależy także od jakości danych już zapisanych w bazie.
- Istniejąca walidacja duplikatów podczas POST /api/items/receive pozostaje nienaruszona.
- Surowe teksty i pola bazy trafiają do bezpiecznego DOM przez textContent, nie do innerHTML. Użytkownik zatwierdza podgląd przed zapisaniem.

## Testy

- Python: dwa ECU z identycznym numerem głównym i OEM, lecz różnymi HW/SW; jednoznaczny rekomendowany wariant, konflikty, brak HW/SW, wyszukiwanie tylko po OEM, wyłączenie numeru seryjnego, brak zgadywania jednej niezgodnej cyfry, uprawnienia i CSRF, pełna niezmienność bazy. PASS.
- Node: brak nadpisywania fotograficznych danych, brak kopiowania HW/SW, niejednoznaczne marki pojazdu, niezaznaczone propozycje z bazy. PASS.
- Rzeczywisty mobilny Firefox 390x844 z izolowaną FastAPI/SQLite: dwa warianty, podgląd z bazy, niezatwierdzone propozycje brakującej kategorii, ręczne zastosowanie, brak mutacji magazynu, odmowa dopasowania przy konflikcie HW/SW. PASS.
- Pełny pakiet testów Magazynu: PASS. Kompilacja APK 0.4.0 na GitHub Actions.

## Odbiór i stan wdrożenia — 29.10.2026

- Produkcyjny backend Magazynu został przełączony na addytywny release: /srv/ai-data/magazyn-v1/releases/ecu-catalog-assisted-v4-20261029/apps/magazyn.
- Jedynymi zmianami backendu są nowy, odczytowy moduł ecu_catalog_match.py i dodanie trasy /api/ecu-label/catalog-match w server.py. Moduły store.py, ECU AI, RM i modele RTX pozostają bez zmian.
- Przed restartem zachowano plik drop-in: /srv/ai-data/magazyn-v1/rollback/ecu-catalog-assisted-20261029/80-ecu-ai-ocr.conf.before.
- Po restarcie: localhost /healthz PASS, Tailscale HTTPS /healthz PASS, nieautoryzowany POST na katalog-match HTTP 401 PASS, webgui/Telegram active PASS.
- Test na prawdziwej bazie produkcyjnej w trybie sqlite mode=ro, przy użyciu już istniejącego identyfikatora ECU: dopasowanie PASS, bez HW/SW rekomendacja automatyczna NULL; kontrola liczby rekordów i numerów bez zmian.
- Pełne testy Magazynu, testy izolowane katalogu, Node oraz mobilny Firefox 390 px: PASS. APK 0.4.0 przez GitHub Actions build PASS, artefakt magazyn-v1-android-debug-apk.
- Odbiór na fizycznym Androidzie po instalacji nowego APK pozostaje do wykonania. Wyświetlanie i przyjmowanie propozycji wymaga ręcznego potwierdzenia.

## Wdrożenie i rollback

Docelowo addytywny backend: nowy plik magazyn/ecu_catalog_match.py i osobna trasa w server.py; bez zmian schema SQLite, obecnego GPU RM, Tailscale i Telegrama. Nowy APK korzysta z już istniejącego WebGUI; jeśli katalog jest niedostępny, wystawia propozycje na podstawie OCR bez katalogowego uzupełniania.
Rollback: przywrócenie poprzedniego katalogu release przez systemd drop-in, bez odtwarzania bazy. Nie usuwać ostatnio wykonanych przyjęć i zmian stanów.

Rollback aktualnego release: skopiować zapisany plik 80-ecu-ai-ocr.conf.before do /home/harrypotter/.config/systemd/user/magazyn-webgui.service.d/80-ecu-ai-ocr.conf, następnie XDG_RUNTIME_DIR=/run/user/1000 systemctl --user daemon-reload oraz restart wyłącznie magazyn-webgui.service. Nie przywracać starej SQLite, żeby nie utracić późniejszych operacji magazynowych.