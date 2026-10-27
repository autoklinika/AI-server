# Magazyn V1 — elektronika, dokumentacja techniczna i „Zamówione” (DEV)

Data 27.10.2026, wyłącznie gałąź feature/magazyn-v1-dev-20261026. Brak zmian w main, Stage K, Telegramie, kluczu AES i produkcji.

## Oddzielne formularze

ECU: marka pojazdu, producent sterownika, zastosowanie, numery/OEM, HW/SW, stan Nowy/Używany i techniczny, ilość/lokalizacja.

Elektronika: niezależne okno z oznaczeniem, numerem katalogowym, producentem, kategorią, obudową, ilością/lokalizacją, dodatkowymi numerami oraz szczegółowymi polami napięcia, prądu, mocy, rezystancji, pojemności, tolerancji, liczby pinów, temperatury pracy, interfejsu i parametrów dodatkowych. Pola parametrów dopuszczają różne jednostki. Elektronika nie posiada wyborów HW/SW ani stanu Nowy/Używany właściwego dla ECU. Administrator może później edytować dane elektroniki w jej szczegółach. Warianty odróżniają także parametry, nie są automatycznie scalane.

## Dokumentacja techniczna

Przy elektronice, podczas dodawania lub po otwarciu szczegółów, można przesłać kartę katalogową, schemat lub inny dokument PDF/PNG/JPG. Limit: 8 MiB/plik, 6 plików na produkt, 256 MiB całej dokumentacji. Zapis jako BLOB w tym samym SQLite z sumą SHA-256, nazwą i typem pliku. Nie ma osobnego katalogu, nowego schedulera ani pominięcia załączników w backupie.

Pobranie dokumentu wymaga zalogowania; odpowiedź ma nagłówek attachment oraz nosniff. Dodanie pliku wymaga CSRF i zalogowania, usuwanie tylko administratora. Walidacja sprawdza rozszerzenie, sygnaturę i limit danych; nie stanowi skanowania antywirusowego lub interpretacji PDF. Nie wykonujemy OCR ani automatycznej analizy obrazu.

## Status „Zamówione”

Status zakupu (Nie zamówiono / Zamówione), ilość zamówiona, opcjonalna notatka i czas zmiany. Administrator zmienia status w szczegółach oraz bezpośrednio z listy „Do zamówienia”. Pracownik może odczytać status. Zamówiona ilość nie zwiększa stanów magazynowych; fizyczne sztuki zwiększają stan dopiero podczas przyjęcia. Przy niskim stanie produkt nadal występuje na liście „Do zamówienia” z etykietą „Zamówione”. Wycofanie statusu jest ręczne. Nie dodano ERP, procesów dostaw ani rezerwacji. Dotychczasowe alerty Telegram pozostają niezależne.

## Baza i API

Addytywna migracja SQLite v2 → v3: nowe tabele electronic_specs, item_documents, purchase_state, z kluczami obcymi i CASCADE usuwającym powiązania usuwanego produktu. Dotychczasowe dane pozostają bez zmian. Obsługa starych wersji przy starcie.

Nowe endpointy: POST/GET /api/items/{id}/documents, GET/DELETE /api/items/{id}/documents/{document_id}, GET/PUT /api/items/{id}/order-status. Dotychczasowa edycja/tworzenie produktów przyjmuje dodatkowe specs dla elektroniki. Upload base64 jest ograniczony przez middleware do 12 MiB, niezależnie od Content-Length.

## Testy i migracja

Testy funkcjonalne na osobnych syntetycznych SQLite obejmują uprawnienia, CSRF, parametry i wyszukiwanie, rozróżnianie wariantów, poprawny/zły załącznik, odrzucenie ścieżek, ograniczenia plików, integrację dokumentów z AES-256-GCM backupem i odtwarzanie, zamówione bez zwiększenia stanu oraz migrację struktury v2 do v3.

Firefox headless/WebDriver BiDi z viewportem 390 px: oddzielne okno ECU i elektroniki, wpisanie parametrów, dołączenie syntetycznego PDF, oznaczenie Zamówione, podgląd pliku i listy zakupowej, wycofanie statusu bez zmian stanu — PASS. Dane syntetyczne i zrzuty pozostają poza repo.

Przed migracją bazy DEV wykonano nową szyfrowaną kopię SQLite v2 na rzeczywistym GlobalNAS. Test odczytu i przywrócenia archiwum do RAM oraz zgodności liczby rekordów: PASS. Po aktywacji należy potwierdzić integralność SQLite, v3 i oba aktywne procesy WebGUI/Telegram.

## Rollback

Przed cofnięciem aplikacji po zmianach w bazie v3 wykonać i zweryfikować backup aktualnego v3. Nie przywracać automatycznie starego v2, ponieważ utraciłoby to późniejsze zapisy. Nie usuwać nowych tabel ani dokumentów. Stary kod aplikacji sprzed migracji rozpoznaje tylko schemat v2, więc cofnięcie wymaga albo kontrolowanego restore historycznego v2 (gdy nie ma nowszych danych), albo poprawki zgodności starego kodu z v3. Samo git revert nie stanowi pełnego rollbacku danych.

## Dostęp

Po odbiorze DEV: https://ai-server.tail759e12.ts.net:8443/ (Tailscale, konto Magazynu). Produkcyjne wdrożenie i merge do main wymagają odrębnej zgody. Nie dodano fikcyjnych produktów do rzeczywistej bazy Magazynu.
