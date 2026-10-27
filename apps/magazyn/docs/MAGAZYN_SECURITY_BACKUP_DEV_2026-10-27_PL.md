# Magazyn V1 — odbiór DEV: logowanie, admin i GlobalNAS
Data: 27 października 2026 r. · Serwer AI / AI Platform

## Zakres i izolacja

Zmiany dotyczą wyłącznie Magazynu V1 w osobnej gałęzi DEV. Zatwierdzone kolory (pomarańczowy `#B74B0D`, grafitowy `#282D33`, jasnoszary `#F5F5F4`) i układ WebGUI pozostają bez zmian. Nie modyfikowano usług produkcyjnych AI Platform, Resource Managera, Hermesa ani Stage K. Nie dodano schedulerów, crona ani otwartych portów LAN.

## Ochrona logowania — DEV PASS

- Logowanie HTTP ma trwałe, atomowo zapisywane w SQLite limity: **5 nieudanych prób na konto i połączenie w 5 minut → blokada na 10 minut**; dodatkowo **30 prób z jednego adresu źródłowego** w takim samym oknie.
- Po przekroczeniu limitu API zwraca **HTTP 429 i Retry-After**, bez ujawniania istnienia konta.
- Tablica limitów zawiera wyłącznie SHA-256 kluczy; nie zapisuje jawnych loginów, adresów klienta ani haseł. Nie ufa nagłówkom `X-Forwarded-For` dostarczanym przez użytkownika.
- Dla nieistniejących kont wykonywany jest porównywalny koszt weryfikacji scrypt (ograniczenie możliwości wykrywania kont na podstawie czasu odpowiedzi).
- Udane logowanie kasuje limit dla bieżącej pary konto/klient. Blokady wygasają samoczynnie; działające sesje nie są unieważniane przez cudze nieudane próby.
- Próby współbieżne są atomowo ewidencjonowane; limit przetrwa restart procesu. Lokalny CLI odzyskiwania konta nie podlega sieciowemu limitowi HTTP.
- Nie można przez pomyłkę dezaktywować, zdegradować ani skasować **ostatniego aktywnego administratora**. Gdy istnieje drugi aktywny administrator, przeniesienie odpowiedzialności działa.

## Backup GlobalNAS — DEV PASS

- Spójny snapshot pracującej bazy SQLite przez SQLite Backup API (wraz z zatwierdzonym WAL).
- Archiwum **AES-256-GCM** z prywatnym kluczem 0600; archiwum i katalogi prywatne 0600/0700.
- **Próbny restore lokalny z kopii szyfrowanej** do katalogu w pamięci RAM: integralność i zgodność treści PASS; dane jawne po teście usunięte.
- Prawdziwy udział `//globalnas.local/AI_Platform` zweryfikowany przez CIFS oraz istniejący marker Stage K. `findmnt` na tym serwerze zwraca warstwy `autofs` i `cifs`; walidator wymaga poprawnego, najwyższego (ostatniego) montowania CIFS.
- **Jedno zaszyfrowane archiwum** zapisano w odrębnym katalogu `/mnt/AI_Platform/Magazyn/daily`, odczytano i ponownie zweryfikowano. Nie dotykano innych kopii ani katalogów Stage K.
- **Pełne odtworzenie bezpośrednio z archiwum na GlobalNAS do /dev/shm**: `PRAGMA integrity_check=ok`, struktura Magazynu poprawna, kopia jawna usunięta po teście. PASS.
- W ustawieniach WebGUI DEV skonfigurowano możliwość ręcznego wykonania kopii. Tworzy ona archiwum **lokalne** oczekujące na synchronizację z NAS; nie oznacza automatycznego transferu. Do synchronizacji używa się osobnego, kontrolowanego polecenia `magazyn.backup flush`.

## Testy i stan wdrożenia

**132/132 testy PASS**, w tym reguły limitowania, nieznane konta, równoległość, fałszywe IP nagłówka, zapobieganie zablokowaniu ostatniego administratora, szyfrowanie i odmowa kopii na samym `autofs` lub nieoczekiwanym udziale. Testy automatyczne używają sztucznych danych; powyższa próba GlobalNAS i restore zostały wykonane osobno na rzeczywistej bazie DEV.

## Warunki przed produkcją

1. **Bezpieczna kopia klucza odszyfrowania poza hostem i NAS**, np. kontrolowany nośnik offline; bez niej kopia na NAS nie wystarcza do odzyskania po całkowitej awarii serwera.
2. Podłączenie zadań okresowych do **istniejącego Stage K** lub innego zaakceptowanego mechanizmu, bez tworzenia nowego schedulera niezależnego od architektury AI Platform. Dodać monitoring spóźnionych kopii i awarii NAS.
3. HTTPS i przegląd uprawnień kont/plików oraz sposób udostępnienia WebGUI pracownikom. DEV działa wyłącznie na localhost przez tunel SSH, z ciasteczkiem bez flagi Secure tylko na loopback.
4. Końcowe testy bezpieczeństwa i odbiór produkcyjny, w tym ochrona prywatności i sytuacje awaryjne. Nie scalać automatycznie na main.

**To odbiór DEV, nie akceptacja wdrożenia produkcyjnego.**
