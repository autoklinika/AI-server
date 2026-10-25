# Magazyn V1 — kompletny raport ustaleń i wymagań

**Projekt:** Serwer AI / AI Platform — aplikacja Magazyn  
**Data ustaleń:** 25 października 2026 r.  
**Status dokumentu:** raport uzgodnionej koncepcji; bez implementacji i bez wdrożenia  
**Zakres:** magazyn sterowników samochodowych i elementów elektronicznych, WebGUI, użytkownicy, stany, lokalizacje, operacje, wyszukiwanie, komunikatory, inwentaryzacja, import/eksport i backup GlobalNAS  
**Priorytet nadrzędny:** prosto, bezpiecznie i stabilnie.

> Ten dokument utrwala ustalenia z rozmowy projektowej. Nie stanowi protokołu wykonania, testów ani odbioru aplikacji. W repozytorium nie publikujemy rzeczywistych stanów towaru, nazwisk pracowników, danych uwierzytelniających, tokenów botów, kluczy, prywatnych adresów ani innych sekretów. Przykłady podane poniżej są wyłącznie ilustracyjne.

## 1. Cel i zakres projektu — ZATWIERDZONE

Powstaje osobna, niewielka aplikacja **Magazyn V1** działająca na AI Platform, służąca do:
1. Ewidencji **sterowników samochodowych** katalogowanych przede wszystkim według marek pojazdów.
2. Ewidencji **elementów elektronicznych** katalogowanych według kategorii.
3. Szybkiego ustalania **co, ile, w jakim stanie i gdzie** znajduje się w magazynie.
4. Rejestrowania, **kto i kiedy** przyjął, wydał, przesunął lub skorygował stan.
5. Wyszukiwania według wielu numerów i parametrów.
6. Sprawdzania stanów przez prywatne rozmowy Telegram/Discord oraz, w przyszłości, osobną aplikację Android.
7. Ochrony informacji magazynowych i wykonywania kopii do GlobalNAS.

Zasada funkcjonalna: **ewidencja ilościowa (wariant A), a nie osobna karta każdego egzemplarza**. Zarówno sterowniki, jak i elektronika mają być obsługiwane prosto, bez systemu klasy ERP.

Aplikacja nie może zakłócać działania obecnych usług AI Platform. Ma pozostawać funkcjonalna bez uruchamiania Ollamy, dużego modelu AI, GPU, ComfyUI czy zadań Resource Managera.

## 2. Nawigacja i główne ekrany — ZATWIERDZONE KONCEPCYJNIE

Wymagane moduły:
- **Sterowniki** — podział wg marki pojazdu, katalog produktów i stanów.
- **Elektronika** — podział wg rodzaju podzespołu.
- **Wyszukiwarka** — wspólna, z przełączeniem: wszystkie produkty / sterowniki / elektronika.
- **Operacje i historia** — przyjęcia, wydania, przesunięcia, korekty, filtrowanie zdarzeń.
- **Inwentaryzacja** — sprawdzanie rzeczywistych ilości.
- **Do zamówienia** — produkty poniżej lub na progu minimalnego stanu.
- **Użytkownicy i ustawienia** — funkcje administracyjne.
- **Backup** — stan kopii, ręczne wyzwolenie i odtwarzanie dla administratora.

WebGUI ma być czytelne w przeglądarce na komputerze, tablecie i telefonie. Obsługa ma opierać się na krótkich formularzach, prostych listach i przyciskach zmiany ilości. Szczegółowy układ ekranów innych niż formularz wydania pozostaje do dopracowania podczas implementacji.

## 3. Sterowniki samochodowe — ZATWIERDZONE

### 3.1. Katalogowanie po markach pojazdów

**Marka pojazdu jest podstawowym sposobem przeglądania sterowników.** Przykładowe marki: DAF, MAN, Scania, Mercedes-Benz, Volvo, Iveco, BMW, Volkswagen, Inne. Lista marek powinna być rozszerzalna.

Po wybraniu marki można filtrować sterowniki według zastosowania, np. silnik (ECU/EMS), skrzynia biegów, EBS, ABS, EGR oraz inne typy. Marka pojazdu i producent elektroniki sterownika są **oddzielnymi polami**: np. marka DAF i producent Bosch.

### 3.2. Dane pozycji sterownika

Dane podstawowe:
- Marka pojazdu.
- Numer identyfikacyjny/numer sterownika — główne oznaczenie pozycji.
- Ilość.
- Lokalizacja magazynowa.
- **Stan produktu: Nowy albo Używany**.
- **Stan techniczny: Sprawny, Uszkodzony albo Nieznany**.

Dane dodatkowe, gdy są znane:
- Kategoria/zastosowanie sterownika.
- Producent sterownika (np. Bosch, Continental, Denso).
- Typ/model sterownika (np. EDC7, EDC17).
- Numer producenta.
- Numer OEM producenta pojazdu.
- Dowolna liczba numerów dodatkowych/zamiennych.
- Wersja sprzętowa HW.
- Wersja oprogramowania SW.
- Uwagi/krótki opis.
- Opcjonalne zdjęcie jako załącznik dokumentacyjny, **bez automatycznej analizy obrazu w V1**.

Nowy/Używany to inny wymiar niż sprawność. Dla tego samego oznaczenia i lokalizacji mogą istnieć osobne ilości: np. nowe-sprawne, używane-sprawne, używane-uszkodzone, używane-o-stanie-nieznanym. Nie należy wymuszać jednej oceny technicznej dla całego typu.

### 3.3. Wiele numerów dla jednej pozycji — ZATWIERDZONE

Jednej pozycji można przypisać **wiele numerów katalogowych i identyfikatorów**. Wyszukiwarka odnajduje ją po każdym z nich. Numer Bosch, OEM i oznaczenia zamienne nie powinny wymuszać zakładania duplikatów.

**Nie scalać automatycznie różnych wariantów HW/SW ani różnych urządzeń tylko dlatego, że numery są podobne.** Przy potencjalnym duplikacie aplikacja proponuje istniejącą pozycję, a człowiek potwierdza wybór.

Techniczna zasada do uwzględnienia: jeśli ten sam model występuje w kilku markach pojazdów, powiązania z markami nie mogą powodować wielokrotnego liczenia jednej fizycznej sztuki. Dokładny model współdzielonych marek należy rozstrzygnąć przy projektowaniu schematu danych; nie ustalono automatycznego łączenia produktów między markami.

## 4. Elementy elektroniczne — ZATWIERDZONE

Druga sekcja tej samej aplikacji. Przewidywane kategorie:
- Mikrokontrolery i pamięci.
- Układy scalone.
- Tranzystory i MOSFET-y.
- Rezystory i kondensatory.
- Diody.
- Złącza.
- Pozostałe elementy.

Pozycja zawiera w szczególności:
- Nazwę/oznaczenie i numer katalogowy.
- Producenta, jeśli znany.
- Kategorię.
- Typ obudowy, np. SMD/0603/SOIC/QFP, gdy ma zastosowanie.
- Parametry techniczne, np. rezystancję, pojemność, napięcie.
- Ilość i lokalizację lub kilka lokalizacji.
- Opcjonalny opis/uwagi.

Podstawową operacją jest szybkie zwiększanie i zmniejszanie ilości. Nie tworzymy osobnych kart każdego rezystora, kondensatora czy układu.

## 5. Lokalizacje i ilości — ZATWIERDZONE

- **Ta sama pozycja magazynowa może być przechowywana w wielu lokalizacjach** (regały, szuflady, pudełka).
- Każda lokalizacja ma własną ilość; suma daje łączną liczbę sztuk pozycji.
- Dotyczy to sterowników i elektroniki.
- Przy sterownikach rozdzielenie stanów Nowy/Używany oraz Sprawny/Uszkodzony/Nieznany pozostaje zachowane także dla poszczególnych lokalizacji.
- Dostępne są operacje przyjęcia, wydania, przesunięcia pomiędzy lokalizacjami oraz korekty ilości.
- Przesunięcie między lokalizacjami nie zmienia globalnej ilości.
- Prosty interfejs z przyciskami **+ / −** oraz wyborem lokalizacji.

Przykładowe oznaczenia A1, B3, C2 są fikcyjnymi etykietami projektowymi, a nie rzeczywistym rozkładem magazynu.

## 6. Formularze — ZATWIERDZONY KIERUNEK I WYGLĄD V1

### 6.1. Dodawanie sterownika

Dwa poziomy: krótki formularz podstawowy oraz rozwijane **Więcej szczegółów (opcjonalnie)**.

Podstawowy:
1. Marka pojazdu.
2. Numer sterownika lub oznaczenie.
3. Ilość (przyciski + / −).
4. Lokalizacja.
5. Nowy/Używany.
6. Stan techniczny.

Rozszerzony:
- Producent, typ.
- Dodatkowe numery OEM i zamienne.
- HW, SW.
- Uwagi.
- Opcjonalne zdjęcie w przyszłości jako zwykły załącznik.

Przed utworzeniem nowej pozycji aplikacja sprawdza podobne numery/duplikaty, także w alternatywnych identyfikatorach. Gdy pozycja już istnieje, proponuje **dodanie ilości do istniejącego wpisu**. Różnych wariantów HW/SW nie scala samodzielnie. Data i tożsamość wprowadzającego są rejestrowane automatycznie.

### 6.2. Wydawanie towaru — WYGLĄD ZATWIERDZONY

Zatwierdzono początkowy układ formularza wydania, z możliwością późniejszej edycji:
1. Nazwa/oznaczenie produktu.
2. Wybór lokalizacji z podaną dostępną ilością.
3. Wydawana ilość, sterowana przyciskami + / −.
4. **Powód wydania jako lista rozwijana**.
5. Opcjonalny **numer zlecenia**, pokazywany po wyborze „Naprawa klienta”.
6. Opcjonalne uwagi.
7. Podsumowanie przed zatwierdzeniem: ilość ujmowana oraz stan, który pozostanie w wybranej lokalizacji.
8. Potwierdzenie wydania.

Powody wydania (ustalona lista początkowa):
- Naprawa klienta.
- Sprzedaż.
- Potrzeby warsztatu.
- Uszkodzenie / utylizacja.
- Inne (z możliwością opisu).

**Powód jest obowiązkowy przy zmniejszaniu stanu z tytułu wydania.** Użytkownik, data, godzina, produkt, lokalizacja, ilość i stan przed/po mają być rejestrowane automatycznie. Numer zlecenia to jedynie opcjonalna informacja tekstowa; nie oznacza integracji z obsługą napraw i nie tworzy rezerwacji.

### 6.3. Przyjęcia, przesunięcia i korekty

Przyjęcie jest prostsze niż wydanie: wybór produktu lub nowa pozycja, lokalizacja, ilość i zapis. Przesunięcie wskazuje źródło i cel. Korekty stanów i inwentaryzacja muszą zapisywać różnice oraz autora.

Prototypy formularzy w rozmowie były demonstracyjne — **nie zapisywały danych i nie były implementacją**.

## 7. Użytkownicy, uprawnienia, historia — ZATWIERDZONE

### 7.1. Indywidualne konta

- Każda osoba ma **osobny login i hasło**, bez współdzielonych kont.
- Konto pracownika wiąże operacje z konkretną tożsamością.
- Hasła nie mogą być przechowywane jawnym tekstem; wymagane są bezpieczne skróty haseł oraz kontrola sesji.
- Model ról ma pozostać prosty: Administrator i Użytkownik.

### 7.2. Nadrzędna decyzja o administratorze

**Administrator ma wszystkie możliwości bez wyjątków**, w tym:
- Wszystkie operacje magazynowe i korekty.
- Dodawanie, edycję i usuwanie produktów, lokalizacji, danych i ustawień.
- Pełne zarządzanie kontami i uprawnieniami.
- Pełne zarządzanie importem, eksportem i kopiami zapasowymi.
- **Przeglądanie, edytowanie i usuwanie historii operacji magazynowych.**

Odrzucono wcześniejszą propozycję nieusuwalnej historii, której nie mógłby zmienić nawet administrator. Nie wolno wprowadzać takiego ograniczenia wbrew decyzji właściciela. Dla bezpieczeństwa można proponować ostrzeżenia i kopie przed operacją destrukcyjną, ale nie znoszą one pełnych praw administratora.

### 7.3. Zwykły użytkownik

Zwykły użytkownik ma **tylko część uprawnień**. Proponowany profil początkowy (dokładny zakres do potwierdzenia przed kodowaniem):
- Przeglądanie i wyszukiwanie.
- Przyjmowanie i wydawanie towaru.
- Przesunięcia lokalizacji.
- Ewentualne dodawanie nowych produktów.
- Podgląd dozwolonej historii.

Bez dostępu do zarządzania kontami, ustawieniami systemu, usuwania/administracyjnej edycji danych, backupów i operacji zastrzeżonych. Szczegółowe uprawnienia (np. prawo do tworzenia pozycji, zakres widoczności historii, ewentualna indywidualna konfiguracja) nie są jeszcze zamkniętą decyzją. **Nie dodajemy teraz rozbudowanego RBAC**.

### 7.4. Historia operacji

Każda operacja automatycznie utrwala:
- Rodzaj: przyjęcie, wydanie, przesunięcie, korekta/inwentaryzacja.
- Użytkownika i datę/godzinę.
- Produkt, lokalizację lub lokalizacje źródłową i docelową.
- Ilość, stan przed i po.
- Powód wydania, jeżeli dotyczy.
- Numer zlecenia i uwagi, jeżeli podane.

Historia powinna być przeszukiwalna według produktu, użytkownika i daty. Normalni użytkownicy nie otrzymują nieograniczonych praw do edycji/usuwania historii; administrator otrzymuje je w pełni.

## 8. Rozbudowana wyszukiwarka — ZATWIERDZONE

Wyszukiwarka ma być szybka, lokalna i użyteczna bez uruchamiania modelu AI.

**Tryby:** Wszystko / Sterowniki / Elektronika.

**Pola wyszukiwania:** numer główny, każdy numer producenta/OEM/zamienny, nazwa, oznaczenie, producent, typ/model, marka pojazdu; opcjonalnie HW/SW. Dla elektroniki także kategoria, typ obudowy i parametry.

**Filtry łączone:**
- Sterowniki: marka, producent, rodzaj/typ, Nowy/Używany, stan techniczny, lokalizacja, ilość/dostępność.
- Elektronika: kategoria, oznaczenie/producent, parametry, obudowa, lokalizacja i dostępność.
- Sortowanie np. nazwa, marka, ilość, lokalizacja.
- Wynik pokazuje stany łączne oraz rozbicie na lokalizacje i stany.
- W historii: filtrowanie po użytkowniku, dacie i produkcie.
- Obsługa kilku numerów w jednym wyszukiwaniu została zaproponowana jako funkcja użyteczna.

Ważna normalizacja identyfikatorów: wielkość liter i typowe spacje/myślniki nie powinny blokować trafienia; wyszukiwanie po części numeru ma działać. Przykład fikcyjny: forma ze spacjami i bez spacji tego samego numeru wskazuje ten sam wpis. Tolerancja prostych literówek oraz wyszukiwanie po kombinacjach parametrów (np. „10k 0603”) były proponowane i są **oczekiwanym kierunkiem jakościowym**, ale algorytm/fuzzy ranking wymagają dopracowania przy realizacji.

## 9. Inwentaryzacja — DODANA I ZATWIERDZONA

- Inwentaryzacja całego magazynu albo wybranego regału/szuflady/lokalizacji.
- Lista pozycji, które według systemu powinny znajdować się w danym miejscu.
- Wpisanie faktycznie policzonych ilości.
- Automatyczne obliczenie różnic.
- Zastosowanie korekty i zapis informacji o użytkowniku, dacie/godzinie, produkcie oraz różnicy.
- Uprawnienia do zatwierdzania korekt zgodne z rolą.

## 10. Minimalne stany i lista „Do zamówienia” — ZATWIERDZONE

- Dla poszczególnych produktów można ustawić minimalny stan magazynowy.
- Gdy ilość spada do minimum lub niżej, pozycja pojawia się na liście **Do zamówienia**.
- Dotyczy w szczególności elektroniki, ale nie musi być ograniczone do elektroniki.
- Można wyświetlać ilość aktualną, próg oraz sugerowane uzupełnienie do progu.
- Zasada agregowania progu (cały produkt vs konkretna lokalizacja) i ewentualnego zapasu docelowego jest do określenia przy implementacji; w rozmowie nie zatwierdzono dodatkowych poziomów progów.

### 10.1. Powiadomienia o niskim stanie przez Telegram/Discord

**ZATWIERDZONE wymaganie: powiadomienie do jednego, wskazanego odbiorcy danego produktu**, a nie do wszystkich użytkowników.

- Administrator przypisuje do **konkretnego produktu** osobę, która ma otrzymywać alarm.
- Konto Telegram lub Discord odbiorcy musi być wcześniej powiązane i autoryzowane.
- Wiadomość trafia **prywatnie** do wskazanego użytkownika, nigdy do publicznego kanału ani zbiorowo do wszystkich.
- Brak przypisanego odbiorcy = brak wysyłki; pozycja nadal widoczna w „Do zamówienia”.
- Ograniczyć powtarzanie alarmów: podstawowa propozycja to powiadomienie przy przekroczeniu progu w dół, a ponowne dopiero po uzupełnieniu ponad próg i kolejnym spadku.
- Decyzja o preferowanym komunikatorze, gdy użytkownik ma oba, wymaga późniejszego ustalenia; zakaz wysyłania do niepowiązanych odbiorców jest bezwzględny.

**ODRZUCONE:** przypisywanie osoby odpowiedzialnej za **całą kategorię produktów** oraz dziedziczenie odbiorcy z kategorii. Nie budujemy takiej funkcji.

## 11. Zapytania o stan przez Telegram i Discord — ZATWIERDZONE DLA V1

- Telegram i Discord służą do wyszukiwania produktów i zapytań typu „ile mam …?”.
- Wyniki mogą zawierać oznaczenie, ilość ogólną, rozbicie Nowy/Używany, sprawność i lokalizacje, zgodnie z uprawnieniami pytającego.
- Boty korzystają z tego samego **API, wyszukiwarki i danych** co WebGUI.
- W V1 boty działają **wyłącznie do odczytu**: bez przyjęć, wydań, edycji czy usuwania.
- Każde konto na komunikatorze musi być indywidualnie powiązane z kontem Magazynu i zweryfikowane.
- Bot odpowiada tylko w prywatnej rozmowie z uprawnioną osobą; wiadomości z nieautoryzowanych kont i publicznych kanałów nie mogą ujawniać zawartości magazynu.
- Można realizować proste zapytania bez modelu LLM i bez GPU.

**Ograniczenie poufności:** treść wysłana na Telegram/Discord przechodzi przez zewnętrznego dostawcę; nie należy uznawać tych kanałów za prywatne w sensie lokalnej bazy. Ograniczamy zakres danych i nie publikujemy list zapasów w kanałach publicznych.

## 12. Przyszła aplikacja Android — ZATWIERDZONY KIERUNEK, POZA V1

W przyszłości powstanie **osobna, prosta aplikacja Android** wykorzystująca wspólne zabezpieczone API Magazynu i indywidualne konta. Przewidywane funkcje:
- Wyszukiwanie i sprawdzanie stanów.
- Dodawanie oraz zmiana stanów z właściwymi uprawnieniami.
- Wykorzystanie **aparatu smartfona** do fotografowania etykiet sterowników i oznaczeń elektroniki.
- W przyszłości odczytywanie tych oznaczeń ze zdjęcia i wstępne wypełnianie danych po potwierdzeniu użytkownika.

**Poza Magazynem V1:** budowanie aplikacji Android, OCR/rozpoznawanie zdjęć, automatyczne katalogowanie na podstawie obrazu. Nie integrujemy systemu ze stanowiskiem Vision ani aparatem Sony A6100. Zwykłe opcjonalne zdjęcie produktu jako załącznik nie oznacza rozpoznawania obrazu.

API projektujemy od początku tak, aby aplikację Android można było dołączyć później, bez tworzenia osobnej bazy produktów.

## 13. Import i eksport danych — DODANE I ZATWIERDZONE

- Import i eksport w formatach **CSV i Excel/XLSX**.
- Eksport całego magazynu lub wybranych kategorii/zakresów.
- Hurtowe wprowadzanie produktów.
- Walidacja danych oraz wykrywanie duplikatów przed importem.
- Administrator ma dostęp do importu i eksportu.
- Import nie może niejawnie łączyć odmiennych modeli HW/SW.
- Operacje importu zmieniające stan muszą zachować informację o wykonującym i historię zmian.
- Eksport jest funkcją użytkową, **nie zastępuje kopii zapasowej**.

## 14. Backup do GlobalNAS — ZATWIERDZONE

### 14.1. Zakres i harmonogram

- **Główna baza działa lokalnie na AI Platform**; GlobalNAS jest celem kopii, nie bazą roboczą.
- Automatyczny backup **raz dziennie**.
- Ręczne wykonanie backupu przez administratora.
- Retencja: **7 kopii dziennych, 4 tygodniowe, 3 miesięczne**.
- **Szyfrowanie kopii zapasowych**.
- Status backupu widoczny w WebGUI.
- Odtworzenie kopii dostępne administratorowi.
- Okresowe testy przywracania i kontrola integralności.

Backup musi obejmować:
1. Katalog produktów, numery, lokalizacje i ilości.
2. Stany Nowy/Używany oraz techniczne, konfigurację minimów.
3. Historię operacji i dane użytkowników.
4. Konta, role/uprawnienia oraz ustawienia aplikacji, w tym konfigurację powiązań z komunikatorami **bez ujawniania sekretów w raporcie ani niechronionym eksporcie**.
5. Ewentualne zdjęcia i załączniki, jeśli będą używane.

Kopia bazy musi być **spójna**: nie wolno kopiować aktywnego pliku bazy w sposób grożący niespójnym stanem transakcji.

### 14.2. Gdy GlobalNAS jest niedostępny

To jest **obowiązkowe** zachowanie:
- Magazyn nadal działa normalnie.
- Kopia zostaje bezpiecznie zachowana lokalnie.
- Po odzyskaniu GlobalNAS zaległe kopie są automatycznie przekazywane.
- Administrator widzi datę ostatniej udanej kopii i stan synchronizacji backupu.
- Błąd backupu **nie blokuje przyjęć, wydań ani przeglądania magazynu**.

W momencie rozmowy GlobalNAS był wyłączony. Nie oznacza to zgody na uzależnianie startu aplikacji od jego dostępności. Limity bufora lokalnego, godzinę zadania dziennego, sposób przechowywania klucza i procedurę przywracania należy ustalić podczas projektu technicznego.

## 15. Bezpieczeństwo i ochrona informacji — ZATWIERDZONY KIERUNEK

Właściciel chce, aby osoba nieuprawniona **nie poznała, ile jakich sterowników i elementów jest w magazynie**, ale jednocześnie nie chce komplikować szyfrowania.

Wymagane:
- Indywidualne uwierzytelnianie użytkowników, bez jawnych haseł.
- Kontrola dostępu według roli i uprawnień; administrator bez ograniczeń funkcjonalnych.
- Aplikacja dostępna przede wszystkim w sieci lokalnej; ewentualny zdalny dostęp przez VPN, bez publicznego wystawiania WebGUI/API.
- Lokalna baza zabezpieczona przed nieautoryzowanym odczytem.
- Zaszyfrowane kopie do GlobalNAS.
- Prywatne odpowiedzi komunikatorów tylko do zweryfikowanych kont.
- API używane przez WebGUI, boty i późniejszy Android respektuje tę samą autoryzację.
- Żadnych rzeczywistych stanów magazynu ani sekretów w publicznym repozytorium.

Rozważono SQLCipher/SQLite i szyfrowanie bazy. **Nie zatwierdzono obowiązkowego, rozbudowanego mechanizmu kluczy, sprzętowych sejfów, wielowarstwowych procedur odblokowania ani specjalnej infrastruktury kryptograficznej.** Dobór technologii powinien pozostać prosty, adekwatny do zagrożeń, zgodny z wymaganiem szyfrowania backupów. Nie należy twierdzić, że samo szyfrowanie chroni dane po przejęciu uruchomionej aplikacji.

## 16. Architektura i granice techniczne — ZATWIERDZONY KIERUNEK

- Oddzielna aplikacja na AI Platform, własne WebGUI i własne dane.
- Jedno wspólne **zabezpieczone API** dla WebGUI, Telegrama, Discorda i przyszłego Androida.
- Bez obowiązkowego użycia GPU, modeli AI, Ollamy, Resource Managera lub Vision.
- Lokalna baza danych; jako prostą opcję rozważano SQLite (oraz SQLCipher, jeżeli nie skomplikuje utrzymania). Konkretna technologia **nie została jeszcze ostatecznie wybrana**.
- GlobalNAS służy tylko do backupu.
- Nie dodajemy osobnego koordynatora ani nie przebudowujemy produkcyjnych usług AI Platform dla potrzeb ewidencji magazynu.
- Projekt i wdrożenie powinny być odizolowane od istniejących aplikacji, z możliwością testowania przed instalacją produkcyjną.

## 17. Funkcje wykluczone, odłożone i niezatwierdzone

### Wyraźnie poza zakresem Magazynu V1 / odrzucone
- **Rezerwowanie produktów pod naprawy** — istnieje inne oprogramowanie do tego celu.
- Obsługa zleceń, faktur, księgowości i rozbudowanych procesów serwisowych (poza opcjonalnym tekstowym numerem zlecenia przy wydaniu).
- Osobne karty i identyfikatory **każdego egzemplarza** sterownika — wybrano ewidencję ilościową, wariant A.
- Nieusuwalny przez administratora dziennik operacji.
- Przypisywanie odbiorcy alertów do całej kategorii i dziedziczenie powiadomień.
- Wysyłanie stanów na publiczne kanały Telegrama/Discorda albo rozsyłanie ich zbiorowo do wszystkich.
- Automatyczne wykonywanie operacji zapisu magazynowego przez boty w V1.
- Integracja z Vision i aparatem Sony A6100.
- Rozpoznawanie numerów ze zdjęć w V1 i budowanie aplikacji Android w V1.
- Ciężki system ERP, rozbudowany silnik AI i infrastruktura GPU do rutynowej obsługi magazynu.

### Pomysły wspomniane, ale **niezatwierdzone do implementacji V1**
- Etykiety/QR z losowymi identyfikatorami na regałach i produktach.
- Automatyczne rozpoznawanie zdjęć/oznaczeń poza przyszłą aplikacją Android.
- Zaawansowane dopasowywanie literówek/fuzzy o jeszcze nieustalonych regułach.
- Indywidualny, drobiazgowy edytor uprawnień pracowników; początkowo dwie proste role.
- Integracje z innymi procesami serwisowymi.

## 18. Kryteria odbioru — propozycja wynikająca z ustaleń

Kryteria do zweryfikowania przed odbiorem produkcyjnym:
1. Dodanie sterownika pod marką pojazdu i jego wyszukanie po numerze głównym.
2. Wyszukanie tej samej pozycji po numerze OEM i dodatkowym/zamiennym.
3. Brak automatycznego połączenia dwóch różnych wariantów HW/SW.
4. Dwa niezależne miejsca składowania tego samego typu — poprawna suma.
5. Oddzielne ilości Nowy/Używany oraz stanów technicznych.
6. Przyjęcie, wydanie i przesunięcie z poprawnym bilansem; przesunięcie nie zmienia sumy.
7. Wydanie wymaga powodu i pokazuje stan pozostały; numer zlecenia jest opcjonalny.
8. Historia identyfikuje użytkownika, czas, lokalizację, ilość i stan przed/po.
9. Administrator może edytować i usuwać historię oraz zarządzać wszystkimi ustawieniami.
10. Zwykły użytkownik nie może wykonać czynności niedozwolonych przez nadane uprawnienia.
11. Globalne wyszukiwanie, łączone filtry i wyszukiwanie po fragmentach numerów działają.
12. Inwentaryzacja liczy różnicę i rejestruje korektę.
13. Produkt z przekroczonym progiem pojawia się na liście „Do zamówienia”.
14. Powiadomienie trafia wyłącznie do wskazanego odbiorcy danego produktu; brak przypisania nie powoduje wysyłki.
15. Konta niepowiązane z Magazynem i kanały publiczne nie otrzymują stanów.
16. Telegram/Discord pozwalają na odczyt, ale nie zmieniają stanów.
17. Import XLSX/CSV wykrywa problemy i duplikaty; eksport odzwierciedla dane.
18. Utrata GlobalNAS nie zakłóca działania magazynu.
19. Po powrocie GlobalNAS lokalne kopie są przekazywane, a odtworzenie jest weryfikowane.
20. Brak wpływu uruchomienia Magazynu na usługi AI Platform, zasoby GPU i produkcyjny RM.

To **proponowana lista testów akceptacyjnych**, nie wynik wykonanych testów.

## 19. Kwestie do doprecyzowania przed kodowaniem

1. Dokładne uprawnienia roli Użytkownik: dodawanie produktu, edycja własnych wpisów, inwentaryzacja, podgląd historii.
2. Czy progi minimalnego stanu liczyć zawsze dla sumy produktu we wszystkich lokalizacjach, czy przewidzieć ustawienie per lokalizacja.
3. Czy alert dla jednego produktu idzie na wybrany komunikator Telegram **albo** Discord, czy dopuszczamy oba prywatne kanały tej samej uprawnionej osoby; jeden odbiorca to nie broadcast.
4. Sposób pierwszego powiązania kont komunikatorów, zmiany kont, odwoływania dostępu i resetu hasła.
5. Konkretna biblioteka/baza i prosty sposób zabezpieczenia lokalnych danych oraz klucza do szyfrowania backupu.
6. Godzina backupu, limity lokalnego bufora, retencja lokalna oraz obsługa długo niedostępnego NAS.
7. Sposób reprezentacji jednego sterownika pasującego do wielu marek bez podwójnego liczenia.
8. Kryteria uznawania wpisu za ten sam produkt przy rozbieżnych HW/SW/OEM.
9. Szczegóły formatu CSV/XLSX i zachowania przy konflikcie ilości/importowanego rekordu.
10. Dokładna lista filtrów/sortowań i strategia tolerowania literówek, jeżeli jest potrzebna.
11. Lokalizacja, nazewnictwo i numeracja regałów/szuflad; faktyczny katalog marek.
12. Wymagania przechowywania zwykłych zdjęć/załączników, jeśli zostaną włączone.
13. Czy automatyczne alerty niskiego stanu wdrażać w pierwszym uruchomieniu V1, czy jako kolejny niewielki etap funkcjonalny; sama funkcja i zasada odbiorcy zostały zaakceptowane.

Żaden z tych punktów nie zmienia zatwierdzonej zasady: administrator ma pełne uprawnienia, użytkownik ograniczone, a system ma pozostać prosty.

## 20. Status prac i reguła zmian

**Na dzień 25.10.2026:**
- Koncepcja funkcjonalna jest uzgodniona i zatwierdzona w opisanym zakresie.
- Nie zbudowano, nie zainstalowano, nie uruchomiono i nie przetestowano aplikacji w ramach tych ustaleń.
- Nie wykonano migracji danych, konfiguracji botów ani backupu Magazynu.
- Niniejszy etap obejmuje **wyłącznie raport oraz jego zapis w odrębnej gałęzi GitHub**, bez zmiany głównej gałęzi produkcyjnej.
- Zmiany zakresu można wprowadzać iteracyjnie; zaakceptowany wygląd formularza wydania jest punktem wyjścia, nie niezmienną blokadą dalszego rozwoju.

**Kolejny etap po osobnej decyzji użytkownika:** projekt techniczny, wykonanie w odseparowanym środowisku DEV, testy uprawnień i integralności stanów, weryfikacja backupu/odtwarzania i dopiero potem ewentualny kontrolowany rollout.

---

**Podsumowanie decyzji:** Magazyn V1 to prosta, niezależna aplikacja ewidencyjna sterowników i elektroniki, z wieloma lokalizacjami i identyfikatorami, stanami i historią, indywidualnymi kontami, administratorem z pełnią praw, rozbudowaną wyszukiwarką, inwentaryzacją, minimami, importem/eksportem, prywatnymi zapytaniami i powiadomieniami Telegram/Discord oraz odpornym na niedostępność NAS backupem do GlobalNAS. Android z aparatem pozostaje etapem przyszłym. 
