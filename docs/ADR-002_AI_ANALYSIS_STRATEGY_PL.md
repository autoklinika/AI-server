# ADR-002 – Strategia analizy danych przez AI

**Status:** Zatwierdzone

## Założenie

CM5 wysyła wyłącznie surowe dane pomiarowe do Serwera AI.

Aplikacja Python działająca na Serwerze AI:

- odbiera dane,
- zapisuje je do bazy,
- wykonuje wyłącznie obliczenia matematyczne,
- grupuje dane w okna czasowe,
- oblicza średnie, minima, maksima, trendy, odchylenia i inne statystyki,
- przygotowuje kompletny kontekst dla modelu AI.

Aplikacja NIE podejmuje decyzji o wystąpieniu anomalii.

## Zadanie AI

Model Qwen otrzymuje przygotowany zestaw danych wraz z odpowiednim promptem.

AI odpowiada za:

- interpretację danych,
- wykrywanie anomalii,
- analizę zależności,
- określenie prawdopodobnych przyczyn,
- przygotowanie rekomendacji,
- określenie poziomu pewności.

## Uzasadnienie

Oddzielenie obliczeń matematycznych od interpretacji pozwala:

- uprościć aplikację Python,
- łatwo zmieniać sposób analizy poprzez modyfikację promptów,
- wykorzystywać pełne możliwości modeli AI bez przebudowy kodu,
- zachować pełną niezależność systemu sterowania CM5.

## Wniosek

Python przygotowuje dane.

Qwen interpretuje dane.
