# Magazyn V1 — Android (wersja pilotażowa)

Aplikacja **Android APK**, która otwiera istniejące, produkcyjne WebGUI Magazynu V1 w bezpiecznym WebView. Bez kopiowania bazy danych, tworzenia osobnego backendu ani zmiany produkcyjnego Magazynu.

**Gałąź DEV. Nie deployować zmian backendu i nie scalać automatycznie.**

## Jak działa

- Stały, ograniczony adres HTTPS: https://ai-server.tail759e12.ts.net:8443/
- Wymaga aktywnego **Tailscale** na telefonie oraz indywidualnego konta w Magazynie.
- Dotychczasowe GUI, role użytkowników, sesje oraz operacje pozostają po stronie istniejącego Magazynu.
- W oknie **Dodaj sterownik** pojawia się dodatkowy przycisk **📷 Skanuj etykietę ECU**, umieszczony obok numeru katalogowego.
- Przycisk otwiera systemowy aparat Android przez ActivityResultContracts.TakePicture / FileProvider. APK nie potrzebuje uprawnienia CAMERA ani dostępu do galerii.
- W formularzu Dodaj sterownik ikona **✨ AI** znajduje się obok ikony **📷 aparatu**. Bez uruchamiania AI aparat używa wyłącznie ML Kit.
- Po kliknięciu AI następuje kontrola wolnej VRAM RTX, stanu RM i modeli rezydentnych. Pasek pokazuje sprawdzenie, rezerwację, ładowanie i rozgrzewanie Qwen3-VL 8B.
- Po wyświetleniu statusu AI gotowe aparat przekazuje zdjęcie wyłącznie przez HTTPS/Magazyn do RTX 5060 Ti. Przy braku pamięci lub zajętym RM pracownik widzi komunikat, a aparat korzysta z lokalnego OCR.
- Sesja AI wygasa po 120 sekundach bezczynności. W przypadku zamknięcia formularza gotowa rezerwacja jest od razu zwalniana; niezależny watchdog serwera pilnuje timeoutu.
- Zwykły OCR Android nadal odczytuje tekst i kody 2D, a walidacja wyników odbywa się w Magazynie.
- AI i lokalny OCR są porównywane. Przy niezgodnych numerach aplikacja wymaga ręcznego wyboru; nie zgaduje marki pojazdu, stanu technicznego ani lokalizacji. Pola wypełnia tylko, gdy są puste.
- Przed zapisem wyświetlany jest oryginalny tekst OCR oraz możliwe numery, które można ręcznie wybrać.
- Zapis do bazy tylko przy normalnym kliknięciu **Dodaj do magazynu** i po istniejących kontrolach duplikatów.
- Funkcja wyboru plików z WebGUI (np. dokumenty elektroniki) działa przez systemowy selektor Androida.

## Ograniczenia pilotażu

1. **Zdjęcia nie są zapisywane w bazie**. Po włączeniu AI są przesyłane tylko do naszego Serwera AI przez Tailscale/HTTPS i przetwarzane w pamięci; plik na telefonie jest usuwany po OCR. Zachowanie zdjęć przy konkretnym przyjęciu ECU wymaga osobnego rozszerzenia backendu, bazy oraz szyfrowanych backupów.
2. Parser obsługuje przede wszystkim charakterystyczne numery Bosch i numery jednoznacznie opisane jako P/N, PART NO lub OEM. Inne rozpoznane wartości są wyświetlane do wyboru, a nie zgadywane.
3. Brak Tailscale oznacza brak dostępu do danych. Nie zapisujemy operacji magazynowych offline i nie wykonujemy ukrytej synchronizacji.
4. Eksport plików i podgląd PDF w Android WebView wymagają testu na rzeczywistym telefonie; nie są jeszcze formalnie odebrane.
5. Debug APK ma podpis testowy tworzony przez GitHub Actions. Jeśli Android zgłosi błąd aktualizacji podpisu, odinstaluj **wyłącznie APK Magazyn**, a następnie zainstaluj nowe. Baza magazynowa na serwerze pozostaje bez zmian. Docelowe aktualizacje bez odinstalowywania wymagają stałego klucza podpisu poza GitHub.
6. APK jest wersją DEV do testów. Backend AI działa tylko po ustawieniu MAGAZYN_ECU_AI_ENABLED=1 na serwerze; przy wyłączonym API aplikacja bezpiecznie wraca do lokalnego ML Kit.
7. Model serwerowy: qwen3-vl:8b-instruct na RTX 5060 Ti, uruchamiany wyłącznie po kliknięciu AI. Nie zmieniamy głównego modelu AI Platform ani usługi RM.
8. Obecna bramka VRAM wymaga co najmniej 8300 MiB wolnych do załadowania Qwen3-VL, o ile nie jest już załadowany. Jest to ostrożny próg, a nie gwarancja atomowej rezerwacji całej pamięci RTX.

## Budowanie APK — GitHub Actions

W repozytorium otwórz **Actions → Magazyn Android APK (DEV)**, wybierz udaną kompilację, a na dole sekcję **Artifacts → magazyn-v1-android-debug-apk**. Pobierze się ZIP zawierający plik **app-debug.apk**.

Workflow: [.github/workflows/magazyn-android-apk.yml](../../../../.github/workflows/magazyn-android-apk.yml).

Alternatywnie w Android Studio z Gradle 8.9 + JDK 17 otwórz folder apps/magazyn/android i uruchom zadanie :app:assembleDebug. Wersja lokalna wymaga zainstalowanego Android SDK 35.

## Instalacja na telefonie

1. Na telefonie Android zainstaluj i aktywuj Tailscale, upewnij się, że Magazyn :8443 jest dostępny z telefonu.
2. Pobierz artefakt ZIP z GitHub Actions, rozpakuj i otwórz **app-debug.apk**.
3. Zezwól wybranej aplikacji plików/przeglądarce na instalowanie aplikacji z tego źródła, jeżeli Android o to poprosi.
4. Uruchom aplikację **Magazyn**, zaloguj się na swoje istniejące konto.
5. Otwórz **Dodaj sterownik**, naciśnij **📷 Skanuj etykietę ECU**, sfotografuj prawdziwą etykietę, sprawdź odczyt, popraw ewentualne błędy.
6. Najpierw naciśnij **✨ AI** i sprawdź pasek postępu. Po statusie **AI gotowe na RTX** naciśnij aparat i wykonaj zdjęcie.
7. Zweryfikuj rozpoznane numery. Do pierwszych testów **nie potwierdzaj przyjęcia** na produkcji na danych eksperymentalnych — fotografowanie i wypełnienie pól nie wymaga zapisu do bazy.

## Zabezpieczenia

- Brak zdalnego JavascriptInterface; uruchomienie aparatu jest przechwytywane wyłącznie z zaufanej strony, z otwartego formularza ECU.
- HTTPS jest wymagane. WebView blokuje mixed content i nie omija błędów certyfikatu.
- Strona spoza wskazanego hosta nie otwiera się wewnątrz aplikacji.
- Tymczasowe zdjęcie nie jest wysyłane do chmury; opcjonalnie trafia tylko do lokalnego AI Gateway przez backend Magazynu.
- Natywne skanowanie nie wywołuje API zmian stanu magazynowego.
- Cookies Magazynu pozostają w prywatnym profilu aplikacji Android, a WebView debugging jest wyłączony.
- Nie zmieniamy Tailscale Grants ani konfiguracji produkcyjnej serwera.

## Testy przed formalnym odbiorem

- Budowa :app:assembleDebug i 6 testów parsera :app:testDebugUnitTest.
- Fizyczny test na Androidzie: Tailscale, logowanie, przejście między ekranami, sesja po restarcie, aparat, OCR Bosch i Continental, brak aparatu, brak Tailscale, niedziałający certyfikat.
- Potwierdzenie, że skan nie tworzy ani nie przyjmuje produktów bez interakcji użytkownika.
- Osobny odbiór instalacji, czytelności dialogu i jakości OCR na zdjęciach rzeczywistych naklejek.
