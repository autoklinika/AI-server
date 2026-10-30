# RM Multi-GPU — kontrakt jakości i odbioru

Data: 2026-10-30. Status: DEV / wymagania odbiorowe, NIE zgoda produkcyjna.
Baza: `23dd598b0c7225e84607ff8cf14f5da2f90591d7` z `autoklinika/AI-server`.

## Cel i granice

Rozszerzamy istniejący RM, nie tworzymy konkurencyjnego planisty. RM kontroluje własne silniki AI; nie przejmuje całego Ubuntu, grup render/video ani dowolnych aplikacji użytkownika. Pierwszy cel to niezależne modele na osobnych GPU. Dzielenie jednego modelu między karty jest osobnym, późniejszym eksperymentem.

Radeon 890M korzysta z pamięci współdzielonej hosta. RTX 5060 Ti ma 16 GiB pamięci dedykowanej. Druga RTX jest planowana; jej model i pojemność pozostają parametrami, nie założeniami implementacji. Testowe 48 GiB jest fiksturą, nie potwierdzeniem zakupu.

## Niezmienniki bezpieczeństwa

1. Jedynym właścicielem decyzji o przydziale jest obecny RM. Backend nie może sam rozszerzać przyznanego zbioru urządzeń.
2. Każda karta ma trwałą tożsamość, oddzielny budżet, stan zdrowia oraz generację/incarnation. Indeks CUDA jest wyłącznie bieżącym mapowaniem.
3. Dedykowane VRAM nie jest sumowane do fikcyjnej pamięci jednej karty. UMA odwołuje się do wspólnego budżetu RAM hosta; ten sam obszar nie może być liczony dwa razy.
4. Atomowość obejmuje sprawdzenie możliwości i rezerwację. Zadanie wymagające kilku zasobów otrzymuje wszystkie albo żaden. I/O nie może blokować globalnego zamka.
5. Zwalnianie jest idempotentne i sprawdza właściciela/generację. Stary heartbeat lub release nie może zmienić nowego przydziału.
6. Anulowanie, timeout, utrata eGPU i restart oznaczają przerwanie przepływu, nie dowód zwolnienia GPU. Brak wiarygodnego potwierdzenia utrzymuje blokadę odpowiednich zasobów.
7. Błąd lub brak telemetrii nie oznacza wolnego GPU. Nieznana pamięć, niezgodny backend i nieznana tożsamość powodują odmowę, nie zgadywanie.
8. Aktywne/chronione zadania nie są wyładowywane przez zwykłe LRU. Presja na GPU A nie uzasadnia usuwania modelu z GPU B.
9. Awaria jednego GPU nie blokuje zdrowych urządzeń bez udokumentowanego powodu wspólnej domeny awarii.
10. Gwarancje dotyczą kontrolowanych silników. Zmienna widoczności GPU i rezerwacja logiczna nie są same w sobie twardą izolacją hosta ani limitowaniem pamięci przez sterownik.

## Dodatkowe warunki rachunku pamięci

Budżet profilu musi uwzględniać szczyt ładowania, pamięć modelu, kontekst/KV i narzut wykonania dla zadeklarowanej współbieżności, nie sam rozmiar pliku wag. Estymacja i zmierzony profil są odrębnymi źródłami informacji.

Trzeba jawnie rozdzielić pamięć już zajętą przez procesy od przyznanych zobowiązań, które jeszcze nie znalazły odzwierciedlenia w telemetrii. Nie wolno ani odjąć zajętości dwa razy, ani pominąć oczekującej alokacji. Test obowiązkowy: zewnętrzne zajęcie pamięci podczas częściowego ładowania wcześniej zarezerwowanego modelu. Przy niepewnej atrybucji przyjmujemy konserwatywny budżet lub blokadę, nie przypisujemy sobie kontroli nad obcym procesem.

## Kolejność pakietów

P0: porównanie aktualnego main i wcześniejszych modułów N1–N5, kontrakt zasobów, plan minimalnej integracji, spis braków i testy bazowe.
P1: model tożsamości GPU i domen pamięci, czysta kalkulacja zasobów, testy jednostkowe i generatywne; bez aktywacji sprzętu.
P2: integracja z istniejącymi rezerwacjami, kolejką i lifecycle, kontrolowane anulowanie i odzyskiwanie; CPU/mock.
P3: odrębny przegląd, poprawki, ponowne testy zamrożonej rewizji, plan testów sprzętowych i rollback.
P4: osobno zatwierdzone testy sprzętowe i odbiór; brak automatycznego merge/deploy.

## Wymagane dowody odbiorowe

- Testy regresji obecnego API i zachowania jedno-GPU przed i po zmianie.
- Testy permutacji kolejności urządzeń, różnych pojemności RTX i UMA współdzielącego host RAM.
- Testy współbieżnych rezerwacji, podwójnego release, anulowania w każdym punkcie await, starych generacji i częściowej alokacji.
- Testy restartu RM/workera, braku/nieaktualności pomiaru, utraty urządzenia, odrzuconej autoryzacji, wyczerpania budżetu i ochrony aktywnych żądań.
- Testy deterministyczne: kontrolowany zegar, jawne bariery zdarzeń, stałe ziarna; bez zależności od przypadkowego sleep.
- Testy właściwości dla rachunku pamięci: brak wartości ujemnych, brak przekroczenia budżetu, niezmienniczość na permutacje i zachowanie sumy rezerwacji. Narzędzie dobieramy po sprawdzeniu istniejących zależności; brak instalacji do produkcji.
- Formatter/linter i kontrola typów dla nowego kodu. Wynik i zakres każdego narzędzia zapisane; brak narzędzia oznacza NOT_RUN, nie PASS.
- Jawne typy, walidacja wejść, małe funkcje, jawne wyjątki, brak broad except maskującego błędy, brak globalnych efektów ubocznych przy imporcie.
- Osobny przegląd osoby/agenta niepiszącego danej poprawki plus weryfikacja przez ChatGPT. Dwa modele nie są równoważne niezależnemu audytowi ludzkiemu.
- Bez nierozwiązanych błędów krytycznych/wysokich. Niższe ryzyka z właścicielem, uzasadnieniem i testem. Sam procent coverage lub liczba PASS nie jest odbiorem jakości.
- Minimalny diff, domyślnie nieaktywny nowy tor, zgodność wsteczna, dokumentacja decyzji i droga wycofania. Bez masowego cherry-pick starych branchy.

## Wykorzystanie open source

Dla każdego fragmentu: repozytorium, pełna rewizja, ścieżka, SHA-256 źródła, obowiązująca licencja i ewentualny NOTICE, zakres adaptacji i testy. Rozróżniamy kod skopiowany/adaptowany, zależność uruchamianą oraz własną implementację inspirowaną algorytmem. Nie kopiujemy całych aplikacji, zależności i wadliwych założeń UMA/dGPU tylko dla oszczędzenia kilku linii.

Wnioski poprzedniego audytu GPUStack, LocalAI i Lemonade wymagają potwierdzenia w przypiętych źródłach przed wykorzystaniem implementacji. Ten pakiet nie udziela automatycznej zgody na pobieranie/wykonywanie obcego kodu.

## Konfiguracja Codex i ślad audytowy

Wybrany model: `gpt-6-astra`. Rozumowanie: `max`. Oddzielne zadania implementacji i recenzji zamiast niekontrolowanego równoległego edytowania. Parametry przekazywane dla konkretnego uruchomienia; globalna konfiguracja użytkownika pozostaje bez zmian. Brak cichego fallbacku do innego modelu.

Manifest uruchomienia zapisuje wersję CLI, żądany model/effort, potwierdzenie uruchomienia, bazowy commit, status worktree, komendy testów, kody zakończenia, hashe raportów i jawne ograniczenia. Wyniki: PASS, FAIL, NOT_RUN, BLOCKED; statusy nie są zamienne. Testy sprzętowe, pełny audyt zależności i odbiór produkcyjny są oddzielnymi etapami.
