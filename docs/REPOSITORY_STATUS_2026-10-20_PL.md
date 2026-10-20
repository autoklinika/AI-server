# Repozytorium AI-server — stan po porządkowaniu 20.10.2026

## Produkcja i źródła

Produkcja została odebrana po restarcie: ComfyUI → Gateway/RM → Hermes startują automatycznie; cykl Ollama → RADIO → ComfyUI → Ollama przeszedł PASS w 56,198 s. Stage K i komunikatory są sprawne. Pełne dowody: [odbiór po restarcie](reports/COMFYUI_POST_REBOOT_ACCEPTANCE_2026-10-20_PL.md).

Gałąź `cleanup/production-sync-20261020` jest przygotowana od bieżącego `main`, po scaleniu #175. Zawiera dokładnie 239 plików źródeł Gateway i benchmarków odpowiadających manifestowi produkcyjnego overlay `vision-radio-5d9d267489609ccb`. Względem `main` zmienia się dziesięć plików runtime: sześć istniejących i cztery nowe moduły. Scheduler, GPUResidency, Platform API i pozostałe źródła zachowują produkcyjne bajty.

Ta gałąź nie zawiera N1–N5, SHARED/Multi-GPU, eksperymentalnych ROCm workerów ani trybu `n2-dev-blocked`. Domyślna aktywacja RADIO nadal jest false; produkcja korzysta ze swojego jawnego drop-inu. Porządkowanie Git nie zmienia `/opt/ai-platform/current`, nie instaluje jednostek i nie restartuje usług.

## Mapa PR-ów

| PR | Status | Decyzja |
|---|---|---|
| #175 | MERGED, CI PASS | Ograniczone ponowienia kopii Stage K; już obecne w main |
| #174 | otwarty draft REFERENCE | Zachowany stos implementacji i dowodów; nie scalać w całości do main |
| #160 | CLOSED / ARCHIVE | Historyczny szkielet benchmarku; gałąź i commity zachowane |
| #161–#163 | CLOSED / ARCHIVE | Poprzednia integracja Vision, audyt i provisioning; gałęzie i dowody zachowane; zamknięcie nie rozwiązuje ustaleń audytu |
| #165 | CLOSED / ARCHIVE | Historyczna propozycja recertyfikacji; main używa przyjętej poprawki recovery #166 |
| #167–#173 | CLOSED / ARCHIVE | Prace DEV N1–N5 i eksperymentalny ROCm; zachowane bez aktywacji produkcyjnej |

Nowy PR dla czystej gałęzi produkcyjnej oczekuje publikacji. Automatyczna kontrola odrzuciła push czterech lokalnych commitów gałęzi Vision, wskazując brak jednoznacznej zgody na publikację tego kodu i raportów do `autoklinika/AI-server`. Nie obchodzono odmowy przez inne API. PR produkcyjny można utworzyć po tej zgodzie; przed merge wymagane jest zielone CI na aktualnym headzie i aktualność względem main.

## Klasyfikacja zachowanych plików

| Klasa | Pliki | Powód |
|---|---|---|
| KEEP | src, stały supervisor/worker RADIO, usługa RADIO, helper gotowości i drop-iny | Źródła rzeczywiście przyjętego rozwiązania |
| KEEP | testy kontraktów/lifecycle/cleanup i odmów instalacji | Regresje CPU; same nie certyfikują GPU |
| KEEP | narzędzia wdrożenia i rollbacku, manifesty produkcji | Odtworzenie i wycofanie odebranych pakietów |
| ARCHIVE | jednorazowe instalatory i skrypty recovery | Audyt przebiegu instalacji, regresje odmów i odtworzenie historycznych pakietów |
| ARCHIVE | raporty, JSON, logi i jeden PNG | Dowody odbiorów i diagnozy historycznych błędów |
| ARCHIVE | gałęzie zamkniętych draftów | Zachowanie niescalonej pracy; brak zgody na jej produkcyjną aktywację |

`deploy/vision-radio/BUNDLE_SHA256.json` opisuje historyczny pakiet DEV użyty przed backportem. Jego hashów nie przeliczamy pod czyste źródła produkcji. Do kontroli bieżących źródeł służy `GATEWAY_PRODUCTION_SOURCE_SHA256.json`; do historycznego pakietu należy użyć jego przypiętego refu lub niezmiennego katalogu na hoście. Tak samo instalator autostartu pozostaje jednorazowym narzędziem przypiętym do starego boot ID i żądania recovery — nie służy do ponownej instalacji po odebranym restarcie.

## Granice

Pełna walidacja czystej gałęzi: **1463 PASS, 9 SKIP, 0 FAIL**; budowanie dziesięciu typów wydań **10/10 PASS**. Szczegóły, lista wykonanych porządków i stan publikacji: [raport końcowy](reports/REPOSITORY_CLEANUP_2026-10-20_PL.md).

RADIO nadal obsługuje przypięty obraz kalibracyjny. Globalne `GPU_REUSE_SAFE=NOT_VERIFIED` i N1=`NOT_ADMITTED` pozostają niezmienione. Nie usunięto gałęzi z niescaloną pracą, rootowych dowodów odzyskiwania ani rollbacków. Stare raporty zachowują status z czasu ich sporządzenia; README prowadzi do bieżącego odbioru.
