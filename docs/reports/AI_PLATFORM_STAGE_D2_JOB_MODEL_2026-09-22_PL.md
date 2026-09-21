# AI Platform — Stage D.2 Job model

**Data:** 2026-09-22  
**Status:** READY FOR SUPERVISOR VALIDATION — implementation ready for supervisor validation  
**Zakres:** wyłącznie D.2; brak production validation/cutover.

## Implementacja

Dodano niemutowalny `JobState` i zaufany wewnętrzny `JobMetadata` w
`src/ai_bridge/gateway/jobs.py`. Rekord zawiera request_id/job_id, domain,
capability, priority_class, state, assignment provider/node oraz pięć czasów UTC.
Nie ma pól na prompt, request body, output, model, wyjątki ani source.
UUID4 identyfikatory są niezależne od legacy sekwencji schedulera i restartów.
Wewnętrzny adapter może przekazać wspólny request_id do kilku jobów; D.2 nie
wprowadza publicznego request envelope ani idempotency semantics.

Istniejący `PriorityScheduler` zachowuje heap, numeric ordering, FIFO,
max_concurrency, queue limit i brak preemption. Metadane nie sterują admission.
Jawna klasa D.1 jest zachowana także przy numeric override; bez klasy dokładne
mapowanie liczby daje klasę, nietypowe legacy liczby dają null.

Nowy model jest addytywny: legacy numeric job_id, active/queued, priority, source,
wait_ms, queue_position i liczniki pozostają. Active/queued i lease describe mają
zagnieżdżony `job`; scheduler snapshot ma `recent_jobs` z ostatnimi 128 terminalnymi
rekordami w RAM. Legacy job_status po release nadal zwraca None. Nie ma storage,
resume po restarcie ani nowego `/api/v1/jobs`.

Gateway zapisuje running przed wywołaniem istniejącego upstreamu i kończy job
przy success, HTTP 4xx/5xx, transport error, cancellation lub stream error/close.
Finalizacja streamu zwalnia slot także wtedy, gdy upstream close rzuci wyjątek.
Wspólna finalizacja zastępuje powielone bloki zwalniania w proxy_scheduled.
Logi błędów nie zawierają tekstu wyjątku upstreamu. Dodatkowe nagłówki
`X-AI-Request-Id` / `X-AI-Job-Id` wskazują JobState; historyczne nagłówki pozostają.
Stały assignment HTTP to `ollama-local` / istniejące Settings.node_id, bez registry.

External lease nadal opisuje rezerwację slotu (`external-reservation`), nie
pełne wykonanie media. Aktywny lease ma lifecycle admitted, nie running, i null
assignment. Jego completed znaczy zwolnienie rezerwacji, nie sukces ComfyUI/Qwen.
Leased HTTP używa tego samego ID/priority i begin/end_use; nie tworzy nowego joba.
Release queued -> cancelled, release active -> completed, idle TTL -> expired.
Reaper kwalifikuje idle/TTL i zwalnia rezerwację pod blokadą registry, aby nie
wybrać expired na podstawie nieaktualnego heartbeat/in_use. Nie zmieniono polityki
TTL ani ochrony używanego lease.

Pełna tabela przejść, timestamp semantics, mapowanie tras i compatibility:
[Component Contracts §7.2](../architecture/AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#72-job-model--stage-d2).
README, target architecture i migration plan wskazują aktualny krok D.2.

## Testy lokalne

Interpreter: `/home/harrypotter/AI-server/.venv/bin/python`, tylko uruchamianie
z `PYTHONPATH=src` wskazującym ten worktree. Bez instalacji/zmian zależności.

- **104 nowe testy D.2 PASS**: macierz lifecycle, brak dowolnych pól content,
  UTC timestamps i cofnięcie zegara, korelacja/UUID, bounded history,
  queue full, queued cancellation, cancellation after dispatch,
  running cancellation rzeczywistego tasku HTTP i streamu, HTTP error/transport,
  unexpected exception, stream read/close, lease release/deferred release/TTL,
  in-use TTL protection, zachowanie leased HTTP success/error/stream,
  privacy status/log oraz wszystkie dziewięć scheduled tras.
- **399 PASS** — suite z pominięciem czterech modułów zależnych od TestClient.
- **3 PASS** — niezależne testy corestate z pominięciem przypadku TestClient.
- Łącznie **402 różnych testów PASS**; D.2/focused tests są podzbiorem tej liczby.
- Python compile dla zmienionego pakietu Gateway: PASS.
- `git diff --check`: PASS.

Polecenia:

```bash
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest tests/test_gateway_jobs.py
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest --ignore=tests/test_gateway_resource_api.py --ignore=tests/test_analysis_delivery_api.py --ignore=tests/test_api.py --ignore=tests/test_corestate_extension.py
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest tests/test_corestate_extension.py -k 'not integrated_cm5_corestate_is_accepted_by_ingest'
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m compileall -q src/ai_bridge/gateway
git diff --check
```

Pełny pytest **NIEUKOŃCZONY**: timeout 40 s. Osobny istniejący
`test_gateway_resource_api.py` także timeout 10 s; faulthandler po 5 s wskazuje
`TestClient.__enter__ -> start_task_soon -> run_sync_from_thread`, przed requestem.
To odpowiada ograniczeniu sesji implementacyjnej D.1. Nie zmieniano harnessu ani
zależności. Nowe testy używają AsyncClient + ASGITransport + lifespan i obejmują
również zachowanie obu istniejących scenariuszy lease HTTP.
**18 istniejących przypadków TestClient wymaga ponowienia przez supervisora.**

## Handoff i granice walidacji

Implementacja jest gotowa do niezależnej walidacji supervisora, nie COMPLETE.
Supervisor pozostaje właścicielem commitów, CI, buildów i dalszego wdrożenia.

Nie wykonano builda release: builder wymaga clean committed source, a agent
zgodnie z zakresem edytuje tylko working tree. Istniejące tooling nadal ma
D.0 phase/migration metadata; jak w raporcie D.1, nie jest to poprawny kandydat
produkcyjny D.2 bez późniejszego przygotowania metadata przez supervisora.
Nie zmieniano deployment tooling ani jego historycznych recovery guardów.

Nie wykonano smoke na produkcji, cutover, rollback ani operacji usługowych.
Nie zmieniono Qwen, GPU, produktów Ollama/ComfyUI, Hermesa, infrastruktury,
sekretów, workflows ani .gitmodules. Brak commit/push/PR/gh/sudo.
Recovery evidence i dotychczasowe rollback paths pozostają zachowane;
JobState jest RAM-only i nie wymaga migracji danych do rollbacku release.
D.3 descriptors/routing, D.4 unified admission, D.5 migration i D.6 production
validation pozostają poza implementacją.
