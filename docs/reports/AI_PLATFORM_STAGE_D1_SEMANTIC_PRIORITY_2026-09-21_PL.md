# AI Platform — Stage D.1 Semantic Priority Classes

**Data:** 2026-09-21
**Branch:** `agent/stage-dh`
**Baseline:** `stage-d0-complete`
**Status:** READY FOR PRODUCTION VALIDATION

## Zakres i decyzja

D.1 dodaje semantyczny kontrakt `priority_class` i mapowanie na istniejący
numeryczny scheduler. Kanoniczne klasy: infrastructure=10, interactive-high=25,
interactive=50, normal=100, background=200, maintenance=300. Historyczne
`critical` jest wyłącznie aliasem infrastructure=10.

Implementacja:

- `src/ai_bridge/gateway/priority.py`: enum klas i niemutowalna tabela mapowania;
- `src/ai_bridge/gateway/app.py`: opcjonalne pole JSON na istniejących scheduled
  POST trasach i `POST /resource/leases`, walidacja 400 i usunięcie metadanych
  przed przekazaniem body do providera;
- Settings/env: komentarze rozróżniają legacy defaulty od jawnych klas;
- architecture/component contracts/migration plan: decyzja, precedence i granice D.1;
- `tests/test_gateway_priority_classes.py`: 52 nowe przypadki testowe.

Nie zmieniono `PriorityScheduler` ani `ResourceLeaseRegistry`. Niższa liczba
wygrywa; równe efektywne priorytety zachowują FIFO, także pomiędzy semantic i
legacy requestami. Praca aktywna nie jest wywłaszczana.

Jawny `X-AI-Priority` zachowuje liczbę w dotychczasowym zakresie -1000..1000 i ma
pierwszeństwo przed klasą. Przy tworzeniu lease analogicznie działa legacy JSON
`priority`; nagłówek nie zmienia API tworzenia lease. Aktywny lease zachowuje
priorytet swojego ticketu. Nie ma nowego nagłówka HTTP ani nazw domen w kontrakcie
klas. Settings nadal konfigurują legacy defaulty; explicit klasy używają tabeli.

Brak `priority_class` zachowuje dotychczasowe body i defaulty tras, w tym WVC=10,
interactive/Hermes=50, normal=100. Background=200 zachowuje numeryczną semantykę.
Nieprawidłowa klasa daje generyczne 400 przed admission, także z numeric override;
błąd nie powtarza request content. Status/logging nie otrzymują promptów.

Pełny kontrakt: [Component Contracts §7.1](../architecture/AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#71-semantic-priority-contract--stage-d1).

## Walidacja lokalna

Interpreter testów: `/home/harrypotter/AI-server/.venv/bin/python` (Python 3.14.4,
pytest 9.1.1), użyty tylko do uruchomienia testów. `PYTHONPATH=src` wskazywał kod
tego worktree; nie instalowano pakietów ani nie modyfikowano tego venv.

| Check | Wynik |
|---|---|
| D.1 + istniejące scheduler/Gateway API/leases/client headers | 68 PASS |
| Suite z pominięciem czterech modułów zależnych od TestClient | 295 PASS |
| Pozostałe niezależne corestate tests | 3 PASS |
| Python compile: src, tools/local_image, tools/local_video | PASS |
| Bash syntax: deploy/stage-a,b,c,d i aktywne video wrappers | PASS |
| git diff --check | PASS |
| Pełny pytest (316 collected) | NIEUKOŃCZONY — timeout 30 s w TestClient |
| Istniejący test_gateway_resource_api.py | NIEUKOŃCZONY — timeout 15 s w TestClient |
| Release build | NIEWYKONANY — wymagany clean committed source |
| Production smoke / rollback / runtime validation | NIEWYKONANE — poza autoryzacją |

Łącznie **298 różnych testów PASS**, 18 wymaga ponowienia przez supervisora.
Wyniku 68 nie należy dodawać do 295: jest podzbiorem tej liczby.

Nowe testy obejmują wszystkie mapowania i alias, każdą scheduled trasę (także
streaming), ordering wszystkich klas, FIFO wewnątrz klasy i z legacy liczbą,
lease ordering/FIFO, precedence numeric/lease, granice i nietypowe legacy liczby,
invalid class/type, błędne liczby, zachowanie custom Settings i body bez pola,
non-preemption oraz brak promptu w status/log capture. Istniejące testy chronią
queue limit, cancellation cleanup, TTL, lease sharing i WVC/Hermes defaulty.

Ograniczenie środowiska: synchroniczny Starlette `TestClient` zawiesza się przy
starcie portalu anyio, przed obsługą requestu. Faulthandler wskazał oczekiwanie
`start_task_soon` / `run_sync_from_thread`. Osobny minimalny przykład
`with TestClient(FastAPI())` bez aplikacji repo również przekroczył timeout 5 s.
Nie zmieniano zależności ani istniejącego harnessu, aby obchodzić ten problem.
Nowe testy używają `httpx.AsyncClient` + `ASGITransport` + lifespan aplikacji.

Polecenia odtwarzające udane runy (z powyższym interpreterem):

```bash
PYTHONPATH=src python -m pytest tests/test_gateway_priority_classes.py tests/test_gateway_scheduler.py tests/test_gateway_api.py tests/test_gateway_resource_leases.py tests/test_ollama_gateway_headers.py
PYTHONPATH=src python -m pytest --ignore=tests/test_gateway_resource_api.py --ignore=tests/test_analysis_delivery_api.py --ignore=tests/test_api.py --ignore=tests/test_corestate_extension.py
PYTHONPATH=src python -m pytest tests/test_corestate_extension.py -k 'not integrated_cm5_corestate_is_accepted_by_ingest'
```

## Handoff i granice etapu

Supervisor powinien przejrzeć diff, ponowić pełny pytest w działającym środowisku
TestClient, następnie przygotować commit i niezależną walidację release/produkcji.
Obecny builder wymaga clean committed tree, archiwizuje HEAD i nadal oznacza
manifest jako D.0; nie uruchamiano go dla niecommitowanych zmian ani nie
przedstawiono D.0 artefaktu jako walidacji D.1. Przed późniejszym release D.1
należy zweryfikować adekwatne oznaczenie fazy/kontraktu w metadanych wydania.

D.2 (Job model), D.3 (descriptors/routing), D.4 (unified admission),
D.5 (compatibility migration), D.6 (pełna produkcyjna walidacja Stage D)
pozostają poza implementacją. Nie rozpoczęto D.2.

Nie wykonano deploy, restart/stop usług, sudo, zmian sieci/secrets/produkcji,
zmian Qwen/Ollama/ComfyUI/GPU, patchowania Hermesa, commit/merge/push ani zmiany
brancha. Recovery evidence i tag D.0 pozostają zachowane. Zmiany są niecommitowane
w worktree; `.agent-result-d1` oznacza gotowość do niezależnej walidacji, nie
ukończenie produkcyjnego etapu.
