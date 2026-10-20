# Resource Manager: cztery stany i rejestr silników — V1, 2026-10-20

Zmiana wyłącznie DEV. Dodano czysty, odczytowy widok `resource_manager`
(`schema_version: 1`) do istniejących GET `/status` i `/health`.
Obie trasy używają tej samej funkcji, lokalnego snapshotu PriorityScheduler
oraz GPUResidency. Nie dodano kolejki, schedulera, daemona, pollingu ani I/O.
Widoki z dwóch żądań mogą się różnić, jeśli pomiędzy nimi zmieni się praca.
Dotychczasowy `gpu_residency`, przejścia, marker i mechanizm lease pozostają bez zmian.

## Znaczenie stanów

| Legacy / scheduler | Nowy stan | Silnik / cel |
| --- | --- | --- |
| `llm`, zero aktywnych ticketów | `IDLE` | brak |
| `llm`, jeden ticket wyłącznie Ollama | `RUNNING` | `ollama` |
| `llm`, jeden mieszany lease | `RUNNING` | `active_engine: null` |
| `media`, jeden aktywny workload dopuszczający ComfyUI | `RUNNING` | `comfyui` |
| `draining_ollama`, aktywny workload media | `SWITCHING` | `ollama` → `comfyui` |
| `freeing_comfy`, aktywny workload media | `SWITCHING` | `comfyui` → `ollama` |
| `media` bez aktywnego workloadu, blokada, brakujące/nieznane dane | `BLOCKED` | brak |
| więcej niż jeden aktywny ticket | `BLOCKED` | brak |

`RUNNING` oznacza zajęcie slotu, również ticket `admitted`; nie dowodzi
wykonywania kernela. Oczekujące zadania nie są właścicielami zasobu i ich liczba
nie powoduje blokady. Nieznany/niedostępny provider w aktywnym workloadzie daje
`BLOCKED`. Powód jest stałym kodem; widok nie kopiuje ID lease, tokenów, źródła
żądania ani surowych danych cleanup. Nie czyta deklaracji silnika od klienta HTTP.
Blokada tego widoku jest diagnostyczna i nie zmienia decyzji admission.

## Rejestr i rzeczywisty runtime

`EngineRegistry` przechowuje niemutowalne, walidowane deskryptory z polami
`id`, `provider_id`, `status`, `execution_available`. ID i provider są unikalne.
Snapshot zwraca nowe obiekty, więc jego modyfikacja nie zmienia rejestru.
Ollama i ComfyUI mają status `configured` i dostępny istniejący adapter;
to nie jest bieżący health check ani dowód gotowości GPU.
Vision (`vision-local`) ma `not_installed`, `execution_available: false`.
Nie dodano Vision do aktywnego runtime provider registry, nie uruchomiono go
ani nie rozszerzono ComfyUI external-use na Vision.

N1 pozostaje `NOT_ADMITTED`, a `GPU_REUSE_SAFE` pozostaje `NOT_VERIFIED`.
`IDLE` nie oznacza pustego VRAM ani zwolnienia kontekstu KFD. Zgodnie z opisem
zadania produkcyjny idle ComfyUI może nadal posiadać kontekst; tej informacji
nie weryfikowano na produkcji. Nie ma nowego dowodu E_safe.

## Kontrakt rozszerzania

Nowy deskryptor można dodać bez dodawania piątego stanu zasobu. Sam wpis nie
instaluje runtime i nigdy nie daje grantu. Aktywacja nowego silnika wymaga
osobnego adaptera, walidowanego provider/node/capability, zaufanych metadanych
trasy oraz obsługi przez ten sam PriorityScheduler i ResourceLeaseRegistry.
Wymagane są testy sprzątania, błędów, anulowania i utrzymania ownership przy
niepewnym cleanup. Obecna interpretacja przejść legacy obejmuje tylko
Ollama/ComfyUI; przyszłe przejścia wymagają jawnej integracji i testów.
Nowych tras inferencji nie wolno kierować poza istniejące admission.

## Wdrożenie i wycofanie

Ten raport nie autoryzuje wdrożenia. Przyszły rollout: przegląd diff i testów
CPU, osobna akceptacja operacyjna, następnie kontrola zgodności obu endpointów
oraz dotychczasowych pól. Rollback: wycofać import i pola `resource_manager`
w Gateway oraz nowy moduł/testy. Brak migracji danych i nowego stanu trwałego;
nie usuwać markera recovery w ramach rollbacku.

Nie wykonywano restartów usług, systemd/sudo, operacji na GPU ani
zmian urządzeń/grup/sterowników. Zmiana DEV może zostać zapisana na
osobnej gałęzi; żadnego automatycznego wdrożenia na produkcję.


## Niezależna regresja po implementacji

Rozszerzona regresja 29 modułów Gateway, CPU, GPUResidency,
ResourceLeaseRegistry, N1–N5, stage N0, API, provider registry
oraz nowego widoku silników: **856/856 PASS**, exit 0.
Log serwera: `/tmp/rm-generic-engine-states-full-regression-20261020.log`.
Ostrzeżenie: jedynie deprecacja Starlette/httpx.

**Zakres odbioru V1:** nowy widok czterech stanów i rejestr w działającym
kodzie Gateway DEV. Nie jest to jeszcze przepisanie wewnętrznej
implementacji `GPUResidency` na dowolne przejścia silników.
Wykonanie Vision oraz nowych silników wymaga kolejnych jawnych
adapterów wejścia/wyjścia i testów, a N1 real GPU grant pozostaje
NO-GO. Rejestr nie nadaje nowych uprawnień.
