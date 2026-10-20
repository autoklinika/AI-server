# AI Platform — kontrakt wykonania silników V1 (20.10.2026)

## Zakres i decyzja
**Integracja do istniejącego Gateway w DEV.** Nie ma nowego schedulera,
własnego systemu stanów, nowego serwisu ani zmian sterownika i uprawnień GPU.
Zatwierdzone cztery stany zasobu pozostają dokładnie takie same:
IDLE, RUNNING, SWITCHING, BLOCKED.
Silnik jest osobnym identyfikatorem z rejestru; jego liczba nie
wymaga dodawania piątego stanu.

## Faktycznie wykonane zmiany
- `src/ai_bridge/gateway/engine_lifecycle.py`: zaufany kontrakt
  `prepare / verify_active / release` i stała, wewnętrzna lista
  implementacji. Nie jest modyfikowana przez klienta HTTP.
- **Ollama**: rzeczywiste żądania inferencji Gateway, zwykłe
  i powiązane z lease, sprawdzają kontrakt `llm` przed wysłaniem
  upstream. Bez dodatkowych zapytań do Ollamy, przeładowywania modeli
  lub restartu procesu. Właścicielem zadania pozostaje PriorityScheduler.
- **ComfyUI**: zewnętrzne wykonanie na faktycznej ścieżce
  ResourceLeaseRegistry używa adaptera. Jego `prepare` i `release`
  wywołują **te same** `GPUResidency.enter_media` i `leave_media`,
  w tym obecne sprawdzanie /api/ps, /queue,
  /ai-platform/residency, /free i allocator. `verify_active`
  potwierdza fazę `media` bez przyznawania nowego uprawnienia.
  Istniejący lease jest utrzymywany przez wszystkie fazy.
- Endpoint `POST /resource/leases/{lease}/uses` nie wymienia już
  na sztywno ComfyUI jako jedynego możliwego przyszłego wykonawcy;
  kontroluje **oba** istniejące warunki: wewnętrzny, zatwierdzony
  adapter zewnętrzny i provider/node/capability z DescriptorRegistry.
  W tej wersji zewnętrzne uruchamianie ma nadal tylko ComfyUI.
- **Vision**: jest w rejestrze diagnostycznym, ale brak gotowego
  zatwierdzonego kontraktu GPU. `lifecycle_for("vision-local")`
  jawnie odmawia `DENIED_UNAVAILABLE`; endpoint nie dopuszcza
  wykonania Vision, a N1 nadal nie ma rzeczywistego grantu.
  Rozszerzenie wymaga jego własnego, sprawdzonego adaptera
  i rejestracji fizycznego wykonawcy po testach.
- Przy odmowie przygotowania Ollamy (np. stan media/blocked)
  Gateway **nie oddaje** przedwcześnie slotu schedulera:
  zatrzymuje admission, zapisuje marker DIRTY i pozostawia
  aktywną rezerwację do kontroli. Przy awarii czyszczenia
  ComfyUI utrzymuje wcześniejsze zachowanie fail-closed
  i zatrzymaną własność zadania.

## Kompatybilność i testy
- Bez zmiany dotychczasowego JSON `gpu_residency`, protokołu
  lease, endpointów Ollamy i działania streamingu HTTP.
- Nowe testy ASGI: normalne i leased Ollama (stream/non-stream),
  odmowa w złej fazie, zachowanie slotu i DIRTY; pełna sekwencja
  ComfyUI przez rzeczywistą API Gateway z udawanym HTTP backendem;
  błędy HTTP, timeout, anulowanie; brak obejścia przez nagłówki
  oraz jawne odrzucanie Vision/nieznanych wykonawców.
- Testy wykorzystują wyłącznie mock HTTP i CPU, **bez wykonywania GPU**.
- Pełna regresja 30 wybranych modułów N1–N5, Gateway, rezydencji,
  providerów, rejestru silników i zadań: **887/887 PASS**, exit 0,
  log `/tmp/rm-engine-adapters-final-20261020.log`. Jedyny warning
  dotyczy znanej deprecacji Starlette/httpx.

## Ograniczenia i następny krok
To **prawdziwy kontrakt używany przez Gateway w kodzie DEV**, ale
nie oznacza jeszcze migracji produkcyjnego release. Nie wykonano
cutover, nie uruchamiano obciążeń GPU i nie wprowadzono nowego
mechanizmu odzyskiwania na żywym serwerze.
`GPU_REUSE_SAFE=NOT_VERIFIED` i `N1_REAL_GPU_GRANT=NOT_ADMITTED`.
Zaufany host pozostaje w trybie cooperative scheduling, nie
globalnego izolowania użytkowników Linuksa.

Kolejny etap jest konkretny: audyt i odbiór nowego release
Gateway, jeden realny test Ollama → ComfyUI → Ollama przy
obecnej jednej kolejce, a potem zatwierdzony cutover z rollbackiem.
Vision można włączyć tylko po dostępności jego procesu i
testach przygotowania/czyszczenia jako osobnego wykonawcy.
