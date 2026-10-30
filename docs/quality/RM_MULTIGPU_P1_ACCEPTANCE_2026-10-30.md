# RM Multi-GPU — odbiór P1 w DEV

*Raport historyczny odbioru lokalnego P1 przed publikacją. Aktualny stan kodu i CI należy weryfikować w GitHub PR. Dane o lokalnym hoście oraz jego ścieżkach celowo pominięto w wydaniu publicznym.*

Data pakietu: 2026-10-30. Weryfikacja UTC: 2026-10-30T22:59:31.346509+00:00.

**Decyzja prowadzącego: P1 zaakceptowany wyłącznie jako kalkulator CPU-only. GO do kolejnego pakietu DEV; produkcja NO-GO.**

## Co powstało

Dwa nowe moduły: `src/ai_bridge/providers/resource_topology.py` i `src/ai_bridge/gateway/resource_accounting.py`. Opisują trwałą deklarowaną tożsamość i generację GPU, osobne VRAM kart RTX oraz wspólną domenę RAM/UMA. Kalkulator uwzględnia rezerwacje, częściowe załadowanie, obserwowane zajęcie, limity i świeżość pomiarów.

Wynik jest warunkową propozycją, nigdy zgodą na wykonanie (`authorizes_execution=False`). Nie dodano drugiej kolejki, discovery ani mechanizmu uruchamiania modeli. Nie zmieniono istniejącego schedulera, app.py i lifecycle. Druga RTX pozostaje parametryzowana; 48 GiB to tylko fikstura.

## Zweryfikowane wyniki

| Kontrola | Wynik |
|---|---|
| Wybrane dotychczasowe testy RM | 156 PASS |
| Testy P1 autora | 132 PASS |
| Osobne testy prowadzącego i regresje recenzji | 29 PASS |
| Razem | 317 PASS, 0 FAIL, 0 pominiętych |
| mypy 1.18.2 strict, Python 3.12 | PASS: 2 nowe moduły runtime |
| Ruff 0.16.9 E4/E7/E9/F/B/I/UP i format | PASS: 4 nowe pliki Python |
| SHA-256 przed i po końcowym teście | Zgodne |
| Testy sprzętowe i pełny zestaw całego repo | NOT_RUN |

Zachowano jedno istniejące ostrzeżenie deprecacji Starlette/httpx. Nie aktualizowano zależności produkcji. Testy są CPU/mock, w tym generatywne ze stałymi ziarnami; nie dowodzą bezpieczeństwa sterownika.

## Usterki wykryte przed odbiorem

Osobne próby prowadzącego wykryły akceptowanie RAM nieznanego node oraz błąd diagnostyki przy maksymalnej długości identyfikatora. Usunięto oba problemy i zachowano regresje. Poprawiono również błędy strict type checking, bez wyciszania ich przez type: ignore.

Niezależny recenzent Codex znalazł błąd wysokiej wagi: częściowa topologia pomijająca UMA mogła zawyżyć host RAM z limitu N0 96 GiB do 128 GiB. Odtworzono osiem wariantów błędu oraz kontrolę dodatnią. Poprawka sprawdza teraz znane limity host/unified z całego N0 per node, także dla pominiętych i wyłączonych urządzeń. Stosuje minimum, nie sumę; nie miesza VRAM ani limitów innych node. Po poprawce wszystkie dziewięć regresji przechodzi.

Recenzent wydał NO-GO dla przypiętego snapshotu i warunkowe GO po poprawce. Prowadzący odtworzył i zamknął uwagę testami. Nie wykonano ponownej recenzji modelowej już po poprawce; pierwotny raport zachowano bez zmiany jego werdyktu. Brak otwartych uwag wysokiej wagi z tego przeglądu.

## Codex i granice odbioru

Implementacja i oddzielna recenzja używały potwierdzonego `gpt-6-astra / max`. Sesja implementacji osiągnęła limit czasu (124), więc nie oznaczono jej jako PASS. Kod i testy powstały; końcowe poprawki oraz weryfikację wykonał prowadzący. Recenzja zakończyła się kodem 0. Osierocony proces CPU/mock pytest po sesji implementacji został zakończony po sprawdzeniu PID, czasu narodzin, komendy i cwd. Nie pozostał proces testowy tego pakietu.

P1 zakłada zaufane deklaracje tożsamości, pomiarów i komplet zobowiązań. Nie uwierzytelnia sprzętu, nie rezerwuje atomowo zasobów i nie potwierdza cleanupu GPU. Znane pojemności host/unified są ograniczeniami wspólnej domeny RAM; osobne apertury UMA nie są jeszcze modelowane. Kod GPUStack, LocalAI i Lemonade nie był kopiowany do tego pakietu.

## Lokalizacja i produkcja

Gałąź lokalna: `dev/rm-multigpu-foundation-20261030`.
Baza: `23dd598b0c7225e84607ff8cf14f5da2f90591d7`.
Worktree: izolowane środowisko DEV (niepublikowana lokalizacja).
Dowody szczegółowe: pozostają lokalnie; ich treść nie jest publikowana w publicznym repozytorium.

Kluczowe pliki: `p1_frozen_source_manifest.json`, `p1_post_review_tests.junit.xml`, `p1_post_review_tests.log`, `CODEX_P1_REVIEW_PL.md`, `p1_peer_finding_fix.json`, `p1_safety_final.json`.

Stan na moment odbioru P1 (przed migracją): nie wykonano commit/push/merge/deploy; śledzone pliki bazy nie były zmienione. Gateway pozostał uruchomiony bez restartu, RM był IDLE. Nie uruchamiano inferencji ani nie zmieniano usług i sterowników.

## Następny pakiet: P2

Integracja kalkulatora z istniejącym RM, początkowo obserwacyjna w DEV: mapowanie tożsamości i pomiarów oraz porównywanie decyzji bez uruchamiania modeli. Potem atomowe rezerwacje GPU+RAM w tej samej kolejce, ochrona właściciela/generacji i kwarantanna właściwej domeny przy niepewnym zakończeniu. Timeout lub anulowanie nie mogą automatycznie oznaczać wolnego GPU. Aktywacja sprzętowa i produkcja wymagają osobnego odbioru.
