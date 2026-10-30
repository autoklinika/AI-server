# Granite v4 — benchmark na rzeczywistych rozmowach z referencjami AI

**Projekt: Serwer AI | 30.10.2026 | Draft PR #182 | Tryb DEV, bez wpływu na produkcję**

## Cel i oddzielenie danych

Bazą jest 250 uprzednio zamrożonych, odanonimizowanych lub zredagowanych pytań z oryginalnego eksportu ChatGPT, z identyfikatorami wiadomości i kontekstem źródłowym, pochodzących z 155 rozmów. Każdy przypadek ma sumę SHA-256 oraz oznaczenie zakazu treningu. Najpierw zweryfikowano integralność oryginalnego ZIP, następnie dobrano pytania do tego zbioru **przed uruchomieniem recenzentów AI i Granite**. Dane nie są umieszczane w GitHub.

Dodatkowy audyt dokładnego pokrywania się z wcześniejszymi danymi Silver i źródłami oraz leksykalny test bardzo bliskich duplikatów nie wykryły konfliktów. **Brak wykrycia konfliktu leksykalnego nie dowodzi niezależności semantycznej**.

## Dwie oddzielne referencje AI

- Recenzent A: lokalny Qwen3.8 27B na AMD; recenzent B: lokalny Qwen3-VL 8B Instruct na RTX.
- Oba modele otrzymują **tylko aktualną treść pytania**, bez odpowiedzi Granite ani etykiety drugiego recenzenta. Kontekst źródłowy jest zachowany osobno i nie uczestniczy w tym konkretnym benchmarku obecnego routera, który sam przyjmuje tylko aktualny tekst.
- Wymagana jest ścisła zgodność czterech pól JSON: `decision, route, selected_tools, required_capability`. Niedozwolone kombinacje nie są naprawiane automatycznie — są oznaczane jako `abstain`.
- Do głównego mianownika trafiają wyłącznie przypadki, w których obaj recenzenci zwrócą **identyczną, poprawną etykietę**. Pozostałe są zachowywane jako `AI_DISAGREEMENT` albo `ABSTAIN`, bez arbitralnego rozstrzygania.
- Obaj recenzenci wywodzą się z rodziny Qwen, więc mogą mieć skorelowane błędy. **To jest benchmark z referencją AI, nie niezależny ludzki GOLD.** Bez ludzkiego dowodu nie używać metryk jako produkcyjnej dokładności.
- Referencje zostały zamrożone i podpisane sumami SHA-256 **przed** pierwszym odtworzeniem pytań na Granite.

## SHADOW i Resource Manager

Po zamrożeniu referencji Granite v4 `granite-router-v4-tpl1:dev` ma otrzymać te same aktualne treści przez **tymczasowy Gateway DEV na localhost**. To odtworzenie (replay) ruchu z realnej historii, a **nie podłączenie przechwytywania rzeczywistych żądań produkcyjnych**. Gateway ma wyłącznie zwracać decyzję i metryki: bez wykonywania narzędzi, bez modyfikacji odpowiedzi Qwena i bez możliwości sterowania urządzeniami.

Każda próba musi przejść przez istniejący globalny RM, zweryfikować `/api/ps`, wyładować model i potwierdzić zwolnienie rezerwacji. Zajęty RM i niepotwierdzony unload kończą się odmową (fail-closed). Nie instalujemy nowych usług systemd, ani nowego planisty GPU.

## Bramka wyniku

Raport końcowy będzie podawał oddzielnie: ogólną liczbę przypadków (250), liczbę zgodnych etykiet AI (mianownik), wstrzymania/rozbieżności (wyłączone z tego mianownika), zgodność Granite z uzgodnionymi etykietami AI, błędy kontraktu, podział na obszary i medianę/p95 latencji.

**Przed zakończeniem obliczeń nie wolno wpisać w raporcie „PASS” ani dokładności.** Po obliczeniu wynik nie zwalnia bramki bezpieczeństwa produkcyjnego; `router_preview_enabled=False` pozostaje bez zmian.

## Status

Testy dwóch recenzentów AI oraz pełne odtworzenie **250/250** przypadków przez Granite zakończono. Referencje zamrożono przed predykcjami Granite. Wynik i ograniczenia przedstawiono poniżej. Prywatne teksty, etykiety, odpowiedzi modeli i sumy kontrolne pozostają w `/srv/ai-data/staging/granite-ai-reference-benchmark-20261030`.

**Zatwierdzony human-GOLD: 0; automatyczne wykonywanie narzędzi: zabronione; produkcyjny cutover: zabroniony.**

## Wyniki końcowe — 30.10.2026

Poniższe liczby są **zgodnością z referencjami dwóch lokalnych modeli AI (rodzina Qwen)**, a nie zmierzoną dokładnością weryfikowaną przez ludzi.

| Miara | Wynik |
|---|---:|
| Oryginalne pytania z eksportu | **250** |
| Referencje: pełna zgoda obu modeli AI | **133** |
| Referencje: spór obu modeli AI | **111** |
| Referencje: co najmniej jedna wstrzymana etykieta | **6** |
| Pokrycie zestawu zgodną referencją | **133/250 = 53,2%** |
| Granite — zgodność z uzgodnioną referencją AI | **75/133 = 56,4%** |
| Granite — niezgodność na uzgodnionych przypadkach | **58/133** |
| Granite — prawidłowy kontrakt odpowiedzi | **247/250** |
| Granite — odrzucone odpowiedzi | **3/250** |
| Mediana / p95 odtworzenia przez Gateway DEV | **3287 / 4152 ms** |
| Wykonane narzędzia i zmienione odpowiedzi produkcyjne | **0 / 0** |
| Ludzkie etykiety GOLD | **0** |

Zgodna część referencji AI składała się z **91 `clarify`, 30 `fallback`, 12 `no_action` i 0 `route`**. Zatem pełna ocena *pozytywnego wyboru lokalnych tras i narzędzi* jest niemożliwa na tym mianowniku.

### Szczegółowa kontrola nadmiernego routingu

| Oba modele AI uzgodniły | Liczba | Granite wskazał `route` |
|---|---:|---:|
| `clarify` | 91 | **22** |
| `fallback` | 30 | **10** |
| `no_action` | 12 | **2** |
| **Razem** | **133** | **34** |

W pięciu przypadkach spośród 34 wskazanych lokalnych tras Granite proponował `tool` (agent ERS), mimo że zgodne referencje AI kwalifikowały sprawę poza `route`. **Żadne z tych pięciu wskazań nie zostało wykonane.** Bez niezależnych ocen ludzkich jest to ważny *sygnał ryzyka*, a nie potwierdzony rzeczywisty odsetek błędów.

Rozkład dopasowań Granite do uzgodnionych referencji AI według obszaru: AI Platform 27/42, ECU 28/47, Vision 11/25, DevOps 8/18, Magazyn 1/1. Ostatni obszar ma za mało przykładów do interpretacji.

### Kontrole jakości i stan serwera

- Ocena A (Qwen3.8 27B) ukończona 250/250, 245 ważnych etykiet, 5 wstrzymań.
- Ocena B (Qwen3-VL 8B) ukończona 250/250, 249 ważnych etykiet, 1 wstrzymanie.
- Referencja AI zamrożona przed pierwszym zapytaniem do Granite. Model oceniany otrzymał wyłącznie bieżące pytanie, identycznie jak recenzenci.
- Zestaw 250 przypadków wybrano przed benchmarkiem; weryfikacja leksykalnych bliskich duplikatów względem wcześniejszych Silver i testów diagnostycznych nie wykazała konfliktów przy ustalonym progu.
- Wszystkie 250 żądań SHADOW przekazano jedynie do **tymczasowego Gateway DEV na localhost**, który po odpowiedzi sprawdzał opróżnienie RTX i zwolnienie istniejącego globalnego RM. **Nie włączono rzeczywistego przechwytywania żądań produkcyjnych.**
- Po teście: tymczasowy Gateway wyłączony, produkcyjny `ai-gateway` aktywny, RM `IDLE`, zero leases/queued/active i brak blokady; RTX bez rezydentów (2 MiB według NVIDIA).

Prywatne dowody wynikowe: `AI_CONSENSUS_MANIFEST.json`, `GRANITE_V4_SHADOW_REPLAY_REPORT.json`, `GRANITE_V4_SHADOW_NONROUTE_SAFETY_AUDIT.json`, `AI_CONSENSUS_COVERAGE_AUDIT.json`.

### Decyzja

**`DEV_REPLAY_EXECUTION_PASS` — infrastruktura i fail-closed; `ROUTER_QUALITY_NOT_ACCEPTED` — jakość i bezpieczeństwo routingu.**

Nie ma podstaw do włączenia Granite jako produkcyjnego routera, nawet w trybie automatycznego wyboru narzędzi. Nie włączać ani nie scalać PR #182 jako produkcyjnego cutover. Zachować `router_preview_enabled=False`.

Następny etap (oddzielny od tego zamrożonego benchmarku): zbudować nowy, źródłowo niezależny zestaw zawierający pozytywne przykłady dla każdej z sześciu tras, z pełnym kontekstem sesji tam, gdzie jest wymagany, i poprawić zabezpieczenie przed nadmiernym `route`. Nie trenować na 250 przypadkach z tego testu ani nie zmieniać promptu na podstawie ich indywidualnych wyników. Pozostają one diagnostycznym holdoutem AI-only.
