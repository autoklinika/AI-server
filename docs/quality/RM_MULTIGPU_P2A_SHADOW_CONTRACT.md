# P2-A — Shadow resource accounting (DEV only)

**Status:** osobny, zależny PR do gałęzi P1. Produkcja: **NO-GO**.
**Implementacja:** ChatGPT bez wywoływania Codexa; testy automatyczne GitHub Actions.

## Cel i granica

P2-A jest *wyłącznie pasywną diagnostyką* istniejącego Resource Managera.
Nie tworzy nowego schedulera, rezerwacji, dziennika, wykonawcy, kolejki ani usługi.
Nie zmienia parametrów GPU, decyzji przydziałów, procedur cleanupu czy
`GPU_REUSE_SAFE`.

`gateway_resource_shadow_enabled` ma wartość domyślną `false`. W tej
konfiguracji zachowanie i JSON `GET /status` pozostają takie jak wcześniej,
a wstrzyknięty dostawca danych nie jest wywoływany.

Po włączeniu tylko w izolowanym środowisku DEV, `GET /status` zawiera pole
`resource_shadow`. `GET /health`, obsługa żądań LLM, tworzenie lease,
przydział zadań i przełączanie Ollama/ComfyUI pozostają niezmienione.

Przykład pól diagnostycznych (bez ID urządzeń, danych użytkowników i tajnych
błędów):

- `mode: observation`
- `result: FIT | DENY | UNKNOWN`
- `reason_codes: [] | [reason, ...]`
- `authorizes_execution: false` (**zawsze**)

**FIT to wyłącznie hipotetyczne dopasowanie do wstrzykniętego snapshotu P1,
a nie uprawnienie do wykonania, dowód dostępności GPU ani wynik produkcyjnego
planisty.** Bez danych P1 odpowiedź to `UNKNOWN / missing_evidence`.

## Wstrzykiwanie danych i zaufanie

`create_gateway_app(..., resource_shadow_source=...)` przyjmuje opcjonalny
synchroniczny, bezefektowy dostawca `ShadowInputs | None`.
Dostawca *nie może* wykonywać I/O, pobierać GPU, uruchamiać procesów,
logować danych wrażliwych ani zmieniać RM. Może dostarczać tylko spójne,
niemutowalne dane `ResourceTopology`, `AcceleratorRegistry`,
`ResourceSnapshot`, `ResourceRequest`, `AssessmentClock`.

W obecnej produkcji taki zweryfikowany dostawca **nie istnieje**. Nie wolno
automatycznie konstruować go ze starych `scheduler.snapshot()`, stanów
`nvidia-smi`, metadanych N0 ani z wolnej VRAM: nie są dowodem własności
GPU, generacji urządzeń czy zakończenia operacji.

W P2-A dostawcą jest jedynie iniekcja testowa CPU/mock. Po otrzymaniu danych
moduł wykonuje czysty `assess_fit()`. Brak lub niespójność danych, błąd
dostawcy oraz nieaktualne/generacyjnie błędne pomiary dają `UNKNOWN`.
Odmowa przy spójnym, zdrowym obrazie oraz niedoborze zasobów lub kwarantannie
to `DENY`. Jeśli wynik zawiera jednocześnie przyczynę nieokreśloną i
powód odmowy, pierwszeństwo ma `UNKNOWN`.

Wyjątki normalnej walidacji są bezpiecznie zamieniane na ogólne kody;
szczegóły błędów dostawcy, ID GPU i wartości pamięci nie są prezentowane
ani logowane przez observer. Anulowanie zadania nie jest uznawane za zwykłą
odmowę i nie zwalnia żadnej rezerwacji.

## Zakres testów

- Wyłączony flag: identyczny status, brak wywołania dostawcy.
- Włączony bez wiarygodnego dostawcy: `UNKNOWN`, nigdy `FIT`.
- Wstrzyknięte spójne, syntetyczne P1: `FIT` wyłącznie informacyjny.
- Dwa niezależne RTX: brak fikcyjnego sumowania VRAM.
- Radeon UMA: wspólny budżet RAM hosta z rezerwą systemową.
- Quarantine RTX A nie blokuje RTX B bez zadeklarowanej wspólnej domeny awarii.
- Stale/future/missing telemetry, clock epoch, generation i revision: `UNKNOWN`.
- Zbyt duży model: `DENY`.
- Zewnętrzny błąd dostawcy: `UNKNOWN`, bez ujawnienia wyjątku.
- Równoczesne GET status oraz istniejące lease: bez wpływu na RM.

Testy GH są CPU/mock, nie uruchamiają rzeczywistych GPU. Ostrzeżenia o
niezaktualizowanej bibliotece FastAPI nie są naprawiane w tym PR.

## Czego tu jeszcze nie ma

P2-A nie rejestruje rzeczywistych zadań RM jako P1 żądań ani nie uwierzytelnia
prawdziwych telemetrii GPU. Nie ma więc jeszcze automatycznej, kompletnej
obserwacji wszystkich uruchomień.

Kolejne, **osobno zatwierdzane** etapy:

- P2-B: zaufany adapter tożsamości/telemetrii i atomowe rezerwacje w
  istniejącym RM, bez drugiego schedulera.
- P2-C: potwierdzanie quiescence, izolacja domen błędów, kwarantanna i recovery
  na rzeczywistym AMD/NVIDIA, po testach sprzętowych.

Ten PR nie jest zgodą na merge do `main` ani deploy na Minisforum.
