# Magazyn V1 — Android (wersja pilotażowa)

Aplikacja **Android APK**, która otwiera istniejące, produkcyjne WebGUI Magazynu V1 w bezpiecznym WebView. Bez kopiowania bazy danych, tworzenia osobnego backendu ani zmiany produkcyjnego Magazynu.

**Gałąź DEV. Nie deployować zmian backendu i nie scalać automatycznie.**

## Jak działa

- Stały, ograniczony adres HTTPS: https://ai-server.tail759e12.ts.net:8443/
- Wymaga aktywnego **Tailscale** na telefonie oraz indywidualnego konta w Magazynie.
- Dotychczasowe GUI, role użytkowników, sesje oraz operacje pozostają po stronie istniejącego Magazynu.
- W oknie **Dodaj sterownik** pojawia się dodatkowy przycisk **📷 Skanuj etykietę ECU**, umieszczony obok numeru katalogowego.
- Przycisk otwiera systemowy aparat Android przez ActivityResultContracts.TakePicture / FileProvider. APK nie potrzebuje uprawnienia CAMERA ani dostępu do galerii.
- Po zrobieniu zdjęcia ML Kit (model w APK) odczytuje lokalnie tekst i kody kreskowe/2D.
- Parser wypełnia wyłącznie puste pola (numer główny, producent, HW, SW i model). Nie zgaduje marki pojazdu, stanu technicznego ani lokalizacji.
- Przed zapisem wyświetlany jest oryginalny tekst OCR oraz możliwe numery, które można ręcznie wybrać.
- Zapis do bazy tylko przy normalnym kliknięciu **Dodaj do magazynu** i po istniejących kontrolach duplikatów.
- Funkcja wyboru plików z WebGUI (np. dokumenty elektroniki) działa przez systemowy selektor Androida.

## Ograniczenia pilotażu

1. **Zdjęcia nie są zapisywane na serwerze**. Na razie plik jest tymczasowy, lokalny i usuwany po OCR. Zachowanie zdjęć przy konkretnym przyjęciu ECU wymaga osobnego rozszerzenia backendu, bazy oraz szyfrowanych backupów.
2. Parser obsługuje przede wszystkim charakterystyczne numery Bosch i numery jednoznacznie opisane jako P/N, PART NO lub OEM. Inne rozpoznane wartości są wyświetlane do wyboru, a nie zgadywane.
3. Brak Tailscale oznacza brak dostępu do danych. Nie zapisujemy operacji magazynowych offline i nie wykonujemy ukrytej synchronizacji.
4. Eksport plików i podgląd PDF w Android WebView wymagają testu na rzeczywistym telefonie; nie są jeszcze formalnie odebrane.
5. Debug APK ma podpis testowy tworzony przez GitHub Actions. Kolejne kompilacje nie gwarantują tego samego podpisu. Do aktualizacji bez odinstalowywania potrzebny będzie trwały klucz wydawniczy, trzymany poza GitHub repo.
6. APK jest wersją DEV do testów; nie jest wdrożeniem produkcyjnym Android.

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
6. Do pierwszych testów **nie potwierdzaj przyjęcia** na produkcji na danych eksperymentalnych — fotografowanie i wypełnienie pól nie wymaga zapisu do bazy.

## Zabezpieczenia

- Brak zdalnego JavascriptInterface; uruchomienie aparatu jest przechwytywane wyłącznie z zaufanej strony, z otwartego formularza ECU.
- HTTPS jest wymagane. WebView blokuje mixed content i nie omija błędów certyfikatu.
- Strona spoza wskazanego hosta nie otwiera się wewnątrz aplikacji.
- Tymczasowe zdjęcie nie jest wysyłane do chmury, ML Kit działa na urządzeniu.
- Natywne skanowanie nie wywołuje API zmian stanu magazynowego.
- Cookies Magazynu pozostają w prywatnym profilu aplikacji Android, a WebView debugging jest wyłączony.
- Nie zmieniamy Tailscale Grants ani konfiguracji produkcyjnej serwera.

## Testy przed formalnym odbiorem

- Budowa :app:assembleDebug i 6 testów parsera :app:testDebugUnitTest.
- Fizyczny test na Androidzie: Tailscale, logowanie, przejście między ekranami, sesja po restarcie, aparat, OCR Bosch i Continental, brak aparatu, brak Tailscale, niedziałający certyfikat.
- Potwierdzenie, że skan nie tworzy ani nie przyjmuje produktów bez interakcji użytkownika.
- Osobny odbiór instalacji, czytelności dialogu i jakości OCR na zdjęciach rzeczywistych naklejek.
