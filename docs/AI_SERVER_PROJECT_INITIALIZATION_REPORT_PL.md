# AI Server – Raport z etapu inicjalizacji projektu

**Data:** 06.08.2026  
**Status:** dokument bazowy projektu

## 1. Cel projektu

Celem projektu jest budowa lokalnego **Serwera AI** odpowiedzialnego za analizę danych z systemu wentylacji.

Serwer AI **nie steruje wentylacją**. Jego zadaniem jest:

- analiza danych,
- wykrywanie anomalii,
- przygotowywanie rekomendacji,
- tworzenie raportów,
- wspomaganie użytkownika w podejmowaniu decyzji.

Sterowanie pozostaje całkowicie po stronie CM5.

---

## 2. Architektura systemu

### 2.1. CM5

CM5 odpowiada za:

- odczyt wszystkich czujników,
- sterowanie wentylatorami,
- realizację logiki bezpieczeństwa,
- wykonywanie algorytmów sterowania,
- wysyłanie surowych danych pomiarowych.

CM5 **nie komunikuje się bezpośrednio z modelem AI**.

### 2.2. Serwer AI

Serwer AI odpowiada za:

- odbiór danych z CM5,
- zapis danych,
- przygotowanie danych do analizy,
- komunikację z lokalnym modelem Qwen,
- zapis wyników analizy,
- udostępnianie rekomendacji.

---

## 3. Docelowa architektura

### Etap 1

```text
CM5
 ↓
Serwer AI
 ↓
Baza danych
 ↓
Qwen
```

### Etap 2 – po wdrożeniu NAS

```text
CM5
 ↓
NAS – centralny magazyn danych
 ↓
Serwer AI
 ↓
Qwen
```

NAS pełni wyłącznie rolę centralnego magazynu danych.

AI nadal działa na dedykowanym Serwerze AI.

---

## 4. Najważniejsze decyzje projektowe

### 4.1. AI nie steruje systemem

Model AI nigdy nie wydaje poleceń sterujących do systemu wentylacji.

Może jedynie:

- analizować,
- proponować,
- rekomendować,
- wykrywać anomalie.

Każda funkcja odpowiedzialna za rzeczywiste sterowanie oraz bezpieczeństwo pozostaje poza warstwą AI.

### 4.2. Python pełni rolę pośrednika

Aplikacja Python odpowiada za:

- odbiór danych,
- zapis danych,
- przygotowanie danych,
- komunikację z Ollamą,
- odbiór odpowiedzi AI.

### 4.3. AI wykonuje interpretację

Python wykonuje wyłącznie obliczenia matematyczne i przygotowanie kontekstu.

Do jego zadań należą między innymi:

- grupowanie danych,
- obliczanie średnich,
- wyznaczanie minimów i maksimów,
- obliczanie trendów,
- obliczanie odchyleń,
- przygotowanie kontekstu dla modelu.

Python **nie stwierdza, że wystąpiła anomalia**.

Interpretację danych wykonuje Qwen.

---

## 5. Strategia analizy danych

Podstawowy przepływ danych:

```text
CM5 wysyła surowe pomiary
 ↓
Python przygotowuje dane
 ↓
Tworzony jest kompletny prompt
 ↓
Qwen analizuje dane
 ↓
Wynik analizy zostaje zapisany i udostępniony użytkownikowi
```

Qwen zwraca między innymi:

- wykryte anomalie,
- możliwe przyczyny,
- poziom pewności,
- rekomendacje,
- uzasadnienie.

---

## 6. Częstotliwość analizy

Planowana analiza cykliczna:

**co 15 minut**.

Dodatkowo przewidziana jest analiza natychmiastowa po wykryciu zdarzenia krytycznego.

Zdarzenie krytyczne nie oznacza przekazania sterowania modelowi AI. Logika bezpieczeństwa i reakcje sterujące nadal należą do CM5. Serwer AI może w takim przypadku jedynie wykonać dodatkową analizę i przygotować informację lub rekomendację.

---

## 7. Baseline

System od pierwszego uruchomienia buduje własny model normalnej pracy warsztatu.

Baseline będzie wykorzystywany przez AI do:

- porównywania nowych danych,
- wykrywania odchyleń,
- obserwowania zmian długoterminowych.

Baseline powinien być traktowany jako kontekst analityczny, a nie jako element logiki bezpieczeństwa lub bezpośredniego sterowania.

---

## 8. Knowledge Base

Powstanie osobna baza wiedzy zawierająca:

- parametry instalacji,
- opis urządzeń,
- charakterystyki wentylatorów,
- dokumentację projektu,
- decyzje projektowe.

AI będzie korzystała zarówno z danych pomiarowych, jak i z wiedzy zgromadzonej w Knowledge Base.

---

## 9. Stan Serwera AI po etapie inicjalizacji

### System operacyjny

- Ubuntu Desktop 26.04 LTS

### Zainstalowane komponenty

- [x] Ubuntu
- [x] aktualizacje systemu
- [x] Ollama
- [x] model Qwen 3.6 35B
- [x] Docker
- [x] Git
- [x] OpenSSH Server

SSH działa poprawnie (`active/running`).

Docker działa poprawnie (`active/running`).

Model Qwen został uruchomiony i poprawnie odpowiada na zapytania.

---

## 10. Kolejne etapy

Plan dalszych prac:

1. konfiguracja zdalnego pulpitu,
2. utworzenie struktury projektu Python,
3. przygotowanie aplikacji odbierającej dane z CM5,
4. wybór bazy danych,
5. integracja z Ollamą,
6. opracowanie promptów dla AI,
7. implementacja analizy anomalii,
8. budowa panelu użytkownika,
9. migracja magazynu danych na NAS po jego wdrożeniu.

---

## 11. Główna zasada projektu

> **CM5 odpowiada za sterowanie. Python przygotowuje dane. Qwen interpretuje dane. AI doradza, ale nigdy nie steruje systemem.**

Ta zasada jest nadrzędnym ograniczeniem architektonicznym projektu i powinna być zachowana we wszystkich kolejnych etapach implementacji.