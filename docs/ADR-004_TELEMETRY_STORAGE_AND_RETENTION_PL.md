# ADR-004 – Przechowywanie i retencja danych telemetrycznych

**Status:** Zatwierdzone  
**Data:** 07.08.2026

## Kontekst

System wentylacji musi zapewniać jednocześnie:

- lokalny dostęp CM5 do bieżącej historii pomiarów,
- możliwość rysowania wykresów i prezentowania historii w GUI CM5,
- odporność na czasową niedostępność sieci lub Serwera AI,
- długoterminowe archiwum danych dla analiz AI,
- możliwość zbudowania baseline'u normalnej pracy warsztatu,
- możliwość analizy zmian sezonowych i długoterminowych.

CM5 nie powinien pełnić roli głównego, wieloletniego magazynu danych.

## Decyzja

Przyjmujemy dwupoziomową architekturę przechowywania danych.

### 1. Lokalny magazyn CM5

CM5 przechowuje lokalnie dane operacyjne z ostatnich **30 dni**.

Planowanym lokalnym magazynem jest lekka baza danych, np. SQLite.

Lokalna historia służy przede wszystkim do:

- rysowania wykresów w GUI CM5,
- szybkiego dostępu do ostatnich pomiarów,
- zachowania historii podczas niedostępności Serwera AI,
- buforowania danych oczekujących na synchronizację.

Historia lokalna oraz kolejka synchronizacji są logicznie rozdzielone. Rekord może być już poprawnie zsynchronizowany z Serwerem AI, ale nadal pozostawać lokalnie na CM5 do końca 30-dniowego okresu retencji.

Dane oczekujące na synchronizację nie mogą zostać usunięte wyłącznie z powodu upływu zwykłego okresu retencji, zanim Serwer AI nie potwierdzi ich przyjęcia.

## 2. Centralne archiwum

Pełna historia telemetryczna jest przechowywana poza CM5:

### Etap początkowy

```text
CM5
 ↓
AI Bridge
 ↓
centralna baza danych na Serwerze AI
```

### Etap docelowy po wdrożeniu NAS

```text
CM5
 ↓
AI Bridge / infrastruktura danych
 ↓
NAS – centralny magazyn danych
```

Serwer AI pozostaje jednostką wykonującą analizę. NAS pełni rolę centralnego magazynu danych.

## 3. Pierwszy rok – okres uczenia charakterystyki warsztatu

Przez minimum pierwsze **12 miesięcy** działania systemu zachowujemy pełną, szczegółową historię pomiarów w centralnym archiwum.

Celem jest zebranie danych pozwalających poznać normalną charakterystykę pracy warsztatu i zbudować wiarygodny baseline.

Pierwszy rok powinien umożliwić obserwację między innymi:

- różnic sezonowych – lato/zima i okresów przejściowych,
- zmian jakości powietrza w różnych warunkach zewnętrznych,
- różnic między godzinami pracy i okresem poza godzinami pracy,
- charakterystycznych cykli dobowych i tygodniowych,
- zachowania instalacji przy różnych obciążeniach warsztatu,
- stopniowych zmian parametrów instalacji,
- powtarzalnych zdarzeń i anomalii.

Dane z tego okresu stanowią materiał analityczny dla AI i budowy baseline'u. Nie oznacza to uczenia ani dostrajania wag modelu Qwen – jest to budowanie historycznego kontekstu normalnej pracy systemu.

## 4. Retencja po pierwszym roku

Po zebraniu reprezentatywnego okresu co najmniej 12 miesięcy nie zakładamy bezwarunkowego kasowania całej starszej historii.

Zamiast tego planujemy retencję warstwową.

Przykładowa przyszła polityka:

- świeże dane – pełna rozdzielczość,
- starsze dane – agregaty minutowe,
- dane długoterminowe – agregaty 15-minutowe i/lub godzinowe,
- istotne zdarzenia i anomalie – zachowywane wraz z kontekstem w wysokiej rozdzielczości.

Dokładne progi czasowe i poziomy agregacji zostaną ustalone po analizie rzeczywistego tempa przyrostu danych i wartości poszczególnych rozdzielczości pomiarowych.

## 5. Historia wieloletnia

Celem retencji warstwowej jest zachowanie możliwości analiz wieloletnich bez konieczności przechowywania każdego surowego odczytu bezterminowo.

System powinien umożliwiać między innymi porównania:

- tego samego miesiąca w kolejnych latach,
- sezonów grzewczych,
- zmian baseline'u,
- długoterminowych trendów jakości powietrza,
- zmian wydajności instalacji.

## 6. Dostęp CM5 do historii

GUI działające na CM5 powinno korzystać z dwóch źródeł zależnie od zakresu czasu.

Dla krótkich zakresów historia może być pobierana bezpośrednio z lokalnej bazy CM5.

Dla zakresów przekraczających lokalną retencję CM5 może pobierać historię przez API AI Bridge z centralnego magazynu danych.

Dzięki temu brak połączenia z Serwerem AI nie uniemożliwia korzystania z bieżącej historii i wykresów.

## 7. Synchronizacja

Podstawowa zasada synchronizacji:

```text
pomiar
 ↓
zapis lokalny na CM5
 ↓
próba wysłania do AI Bridge
 ↓
potwierdzenie przyjęcia (ACK)
 ↓
oznaczenie rekordu jako zsynchronizowanego
```

Jeżeli AI Bridge lub sieć są niedostępne, CM5 kontynuuje normalną pracę i przechowuje niewysłane dane lokalnie. Po odzyskaniu komunikacji zaległe dane są przesyłane ponownie.

Mechanizm synchronizacji powinien być odporny na duplikaty i umożliwiać identyfikację brakujących paczek.

## 8. Niezależność sterowania

Mechanizm przechowywania, synchronizacji, AI Bridge, centralna baza danych, NAS ani model AI nie mogą być wymagane do prawidłowego sterowania wentylacją.

CM5 pozostaje autonomicznym sterownikiem systemu.

**AI wyłącznie analizuje dane i przygotowuje rekomendacje. AI nigdy nie steruje wentylacją.**

## Podsumowanie

Przyjmujemy następujący model:

```text
CM5
├── sterowanie i bezpieczeństwo
├── lokalna historia: 30 dni
├── GUI i lokalne wykresy
├── kolejka synchronizacji
│
└── AI Bridge
      ↓
   centralne archiwum
      ├── pierwszy rok: pełna szczegółowa historia
      └── później: retencja warstwowa i agregacja
             ↓
          historia wieloletnia
```

Rozwiązanie zapewnia lokalną autonomię CM5, pełny materiał do zbudowania baseline'u w pierwszym roku oraz możliwość zachowania wartościowej historii wieloletniej bez niekontrolowanego wzrostu bazy danych.