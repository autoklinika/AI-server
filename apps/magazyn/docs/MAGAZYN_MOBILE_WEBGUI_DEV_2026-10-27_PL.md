# Magazyn V1 — dopracowanie mobilnego WebGUI (DEV)

Data: 27.10.2026. Repozytorium: AI-server, gałąź feature/magazyn-v1-dev-20261026.

## Zakres

Cel: jedno istniejące WebGUI (FastAPI/SQLite) wygodne w Safari iPhone, bez oddzielnej aplikacji, nowego frameworka, backendu, serwisu i schedulera.

Zachowano:
- Zatwierdzone kolory: pomarańczowy #B74B0D, grafit #282D33, jasnoszary #F5F5F4.
- Katalogi Sterowniki / Elektronika, wyszukiwanie Bosch/OEM, lokalizacje, stany i użytkowników.
- Dotychczasowe endpointy, operacje, role, CSRF, backup, Telegram i niezmienioną bazę Magazynu.
- Wersję desktopową z lewą nawigacją; żadne funkcje nie zostały wyłączone w wersji komputerowej.

## Ulepszenia na telefonach (do 650 px)

1. Wykorzystano istniejące przyciski nawigacyjne jako **dolny pasek**, zamiast tworzyć drugi zestaw przycisków. Cztery sekcje dla pracownika, pięć dla administratora. Podświetlenie aktualnej sekcji i wskaźnik „Do zamówienia” pozostają. Przyciski zachowują jeden zestaw obsługiwanych zdarzeń i wspólne role.
2. Zastosowano viewport-fit=cover, uwzględnienie bezpiecznego dolnego obszaru iPhone'a oraz odpowiednio duży odstęp końcowy treści.
3. Zmieniono **mobilną kolejność wizualną** na: tytuł / „Dodaj produkt” → wyszukiwarka i filtry → wyniki → statystyki. Na desktopie zachowano dotychczasową kolejność.
4. Pokazano wszystkie trzy przyciski przy produkcie: Szczegóły / + Przyjmij / − Wydaj. Minimalne obszary dotyku 44 px.
5. Uproszczono układ inwentaryzacji i historii: zamiast szerokich tabel każda pozycja jest kartą z podpisami pól. Backend/API, wartości i uprawnienia pozostały identyczne.
6. Formularze i dialogi: większe przyciski +/- oraz wyraźne zakładki operacji, trwały dostęp do zamknięcia, większe pola i akcje, odpowiednie marginesy dla ekranu i klawiatury iOS.
7. Ekran logowania dopasowano do szerokości 320 px; pola wejściowe 16 px eliminują typowy zoom Safari przy aktywacji klawiatury. Przy wylogowaniu dane wcześniejszego użytkownika są czyszczone z formularza.
8. Poprawiono dotykowe działania panelu administratora bez zmiany kontraktów API.

Wszystkie zmiany dotyczą wyłącznie index.html, style.css i app.js; bez zmian Python, SQLite, komunikatorów i haseł.

## Wykonane testy

- 4 testy kontraktu HTML/CSS/JS w izolowanych scenariuszach pytest (unikalne identyfikatory, 5 sekcji, akcje, stany uprawnień, zachowane kolory).
- Browser smoke **na prawdziwym Firefox 158 headless + WebDriver BiDi**, w izolowanej bazie SQLite z dwoma **syntetycznymi** produktami i kontami. Odtworzono viewporty 390×844, 320×700 i 1440×900.
- 390 px: formularz logowania bez przewijania w poziomie i bez czcionki poniżej 16 px; dolna nawigacja (5 admin / 4 pracownik), wyszukiwarka przed statystykami, przyciski wydania i przyjęcia min 44 px — PASS.
- 390 px: filtrowanie historii i inwentaryzacja w kartach bez przewijania strony w poziomie — PASS.
- 390 px: przycisk − Wydaj otwiera formularz wydania, powód pozostaje obowiązkowy, przycisk zatwierdzenia jest nieaktywny do wyboru powodu, kontrolki +/- mają min 44 px — PASS. **Nie wykonywano operacji zapisu do rzeczywistego magazynu.**
- 320 px: dolne menu, formularze i produkty bez poziomego przewijania — PASS.
- 1440 px: istniejąca nawigacja boczna, karty i akcje na desktopie pozostały — PASS.
- Zmiana konta admin → użytkownik: poprzedni login resetowany, administrator ukryty, pozostałe cztery sekcje dostępne — PASS.
- Logi i zrzuty wyłącznie syntetycznych danych (nie na GitHub): /srv/ai-data/staging/magazyn-mobile-ui-dev-20261027/.

**Uwaga:** powyższe to testy Firefox z viewportem telefonu. Rzeczywisty test dotyku, klawiatury, safe-area i formularzy w Safari iOS wymaga krótkiego odbioru na iPhonie właściciela. Nie nazywamy tego „Safari PASS” bez tego testu.

## Sposób otwarcia

Magazyn DEV przez istniejące Tailscale Serve:
https://ai-server.tail759e12.ts.net:8443/

Włącz Tailscale na iPhonie i otwórz powyższy adres w Safari. Po wdrożeniu CSS/JS wykonaj odświeżenie strony, aby wymienić zasoby.

## Rollback

Wycofać wyłącznie commit mobilnego GUI na gałęzi DEV (git revert po odbiorze) i przeładować stronę.
Nie modyfikować baz, kluczy AES, GlobalNAS, usług Stage K ani użytkowników. WebGUI działa na tym samym localhost:18765 i HTTPS Serve:8443.

## Granice projektu

Nie jest to wdrożenie Magazynu na produkcję. Nie wykonano merge do main.
Osobne etapy: fizyczny backup/recovery key, odbiór daily/weekly Stage K, błąd weekly Knowledge i końcowe bezpieczeństwo.
