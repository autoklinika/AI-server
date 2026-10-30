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
- Referencje zostaną zamrożone i podpisane sumami SHA-256 **przed** pierwszym odtworzeniem pytań na Granite.

## SHADOW i Resource Manager

Po zamrożeniu referencji Granite v4 `granite-router-v4-tpl1:dev` ma otrzymać te same aktualne treści przez **tymczasowy Gateway DEV na localhost**. To odtworzenie (replay) ruchu z realnej historii, a **nie podłączenie przechwytywania rzeczywistych żądań produkcyjnych**. Gateway ma wyłącznie zwracać decyzję i metryki: bez wykonywania narzędzi, bez modyfikacji odpowiedzi Qwena i bez możliwości sterowania urządzeniami.

Każda próba musi przejść przez istniejący globalny RM, zweryfikować `/api/ps`, wyładować model i potwierdzić zwolnienie rezerwacji. Zajęty RM i niepotwierdzony unload kończą się odmową (fail-closed). Nie instalujemy nowych usług systemd, ani nowego planisty GPU.

## Bramka wyniku

Raport końcowy będzie podawał oddzielnie: ogólną liczbę przypadków (250), liczbę zgodnych etykiet AI (mianownik), wstrzymania/rozbieżności (wyłączone z tego mianownika), zgodność Granite z uzgodnionymi etykietami AI, błędy kontraktu, podział na obszary i medianę/p95 latencji.

**Przed zakończeniem obliczeń nie wolno wpisać w raporcie „PASS” ani dokładności.** Po obliczeniu wynik nie zwalnia bramki bezpieczeństwa produkcyjnego; `router_preview_enabled=False` pozostaje bez zmian.

## Status

Testy dwuetapowe w toku na rzeczywistym serwerze; pełny wynik liczbowy zostanie dodany dopiero po sprawdzeniu kompletności obu referencji i odtworzenia Granite. Oryginalne pliki i indywidualne etykiety pozostają w prywatnym katalogu `/srv/ai-data/staging/granite-ai-reference-benchmark-20261030`.

**Zatwierdzony human-GOLD: 0; automatyczne wykonywanie narzędzi: zabronione; produkcyjny cutover: zabroniony.**
