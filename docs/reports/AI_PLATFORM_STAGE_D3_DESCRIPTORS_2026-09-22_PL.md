# AI Platform — Stage D.3 Capability/provider/node descriptors

**Data:** 2026-09-22  
**Status:** READY FOR SUPERVISOR VALIDATION — implementation ready for supervisor validation  
**Zakres:** wyłącznie D.3; bez production validation/cutover.

## Implementacja i kontrakt

`src/ai_bridge/providers/registry.py` dodaje niemutowalne `NodeDescriptor`,
`CapabilityDescriptor`, `LogicalProviderDescriptor` i `DescriptorRegistry` v1.
Pierwsze bindings: `ollama-local` (llm), `comfyui-local` (media-generation),
`hermes-local` (agent), wszystkie na istniejącym `Settings.node_id`.
Registry waliduje ID, typy, wersję, duplikaty, referencje node/capability,
zgodność provider_type z capability oraz assignment provider/node/capability.
Nieznane pola są odrzucane; brak miejsca na prompt, URL, secrets i dowolne metadata.

Domyślny inventory jest częścią pakietu. Opcjonalne
`Settings.gateway_registry` / JSON `AI_BRIDGE_GATEWAY_REGISTRY` pozwala jawnie
zadeklarować ten sam inventory; przykład jest w `deploy/gateway-registry.example.json`.
Brak/null config korzysta z defaultów, niepoprawny config nie ma silent fallback.
Gateway przed utworzeniem klienta HTTP wymaga bieżących bindings i jednego
lokalnego node. Schemat może reprezentować przyszłe node'y, ale runtime D.3
odrzuca konfiguracje zmieniające topology/capabilities/provider bindings.
Nie ma discovery, routing, failover, dynamic reload ani multi-node execution.

`/status.registry` jest addytywnym snapshotem configured inventory; nie oznacza
providerów jako ready i nie uruchamia health probes. Stage C `ProviderDescriptor`
z adapterowego `describe()` pozostaje odrębnym runtime kontraktem, bez zmian.
Ollama streaming/embeddings w registry opisują istniejące Gateway proxy routes,
nie implementację Stage C stream adaptera ani zainstalowany embedding model.
Konfiguracja modeli, workflow, GPU i produktów pozostaje bez zmian.

Scheduler waliduje zaufane capability metadata przed enqueue i sprawdza parę
provider/node oraz capability przed zapisaniem assignment. Błąd pozostawia job
i ownership slotu bez zmian. Zwykłe Gateway HTTP korzysta z descriptor
`ollama-local` przy przejściu do running, w obu ścieżkach: streaming i non-streaming.
Assignment pozostaje w terminalnej historii D.2. Model, URL, payload i admission
zachowują dotychczasową semantykę; registry nie wybiera backendu.

Queued jobs i external leases pozostają bez assignment. Rezerwacja może obejmować
Qwen oraz ComfyUI, więc source/media/Hermes route nie dowodzi wykonania konkretnego
providera. Leased HTTP nadal korzysta z tej samej rezerwacji, bez dodatkowego joba.
D.4 unified admission, D.5 client migration i D.6 production validation pozostają
poza zakresem. Nie dodano Platform API.

Szczegóły: [Component Contracts §8.1](../architecture/AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#81-static-descriptors--stage-d3).
README, target architecture i migration plan wskazują D.3 jako bieżący krok.

## Testy implementacyjne

Interpreter: `/home/harrypotter/AI-server/.venv/bin/python`, użyty wyłącznie do
testów z `PYTHONPATH=src` tego worktree. Bez instalacji/zmian zależności.

- **89 testów D.3 PASS**: config roundtrip/immutability, checked-in example,
  niestandardowy local node, JSON Settings, nieznane ID/types/references,
  duplikaty, brak silent fallback, topology gates, atomowe odrzucenie assignment,
  wszystkie 9 tras HTTP ze streamingiem i bez, byte-for-byte payload,
  brak promptów w status/log, queued i external lease null assignment.
- **156 testów D.1/D.2 PASS** po integracji registry, w tym lifecycle,
  error/cancellation/stream cleanup, priority/FIFO oraz leased HTTP.
- Szerszy suite z pominięciem czterech modułów TestClient: **486 PASS** przed
  dodaniem dwóch końcowych testów config; te dwa weszły do końcowego runu D.3.
- **3 PASS** — niezależne testy corestate.
- Łącznie **491 różnych testów PASS**; focused D.1/D.2/D.3 są podzbiorami tej liczby.
- Python compile zmienionych modułów: PASS; `git diff --check`: PASS.

Polecenia:

```bash
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest tests/test_provider_registry_contracts.py
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest tests/test_gateway_jobs.py tests/test_gateway_priority_classes.py
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest --ignore=tests/test_gateway_resource_api.py --ignore=tests/test_analysis_delivery_api.py --ignore=tests/test_api.py --ignore=tests/test_corestate_extension.py
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest tests/test_corestate_extension.py -k 'not integrated_cm5_corestate_is_accepted_by_ingest'
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m compileall -q src/ai_bridge/providers/registry.py src/ai_bridge/gateway src/ai_bridge/settings.py
git diff --check
```

Pełny pytest **NIEUKOŃCZONY**: timeout 45 s. Izolowany istniejący
`tests/test_gateway_resource_api.py` także timeout 10 s; faulthandler po 5 s
wskazuje `TestClient.__enter__ -> start_task_soon -> run_sync_from_thread`,
przed requestem. To ten sam symptom co w sesjach implementacyjnych D.1/D.2.
Nie zmieniano harnessu ani zależności. Nowe testy używają AsyncClient/ASGITransport
i lifespan, bez rzeczywistych wywołań backendów.
**18 istniejących przypadków TestClient wymaga ponowienia przez supervisora.**

## Handoff, produkcja i recovery

Implementacja jest gotowa do niezależnej walidacji supervisora, nie COMPLETE.
Supervisor pozostaje właścicielem commitów, CI, buildów i dalszego wdrożenia.
Nie wykonano release build: builder wymaga clean committed source, a agent
edytuje wyłącznie working tree. Builder nadal ma historyczne D.0 phase/migration
metadata; jak w D.1/D.2, wymaga przygotowania metadata właściwego kandydata
przed produkcyjnym użyciem D.3. Config registry ma własny schema_version=1,
co nie stanowi aktualizacji wersji całego release manifest.

Nie wykonywano cutover, rollback, real smoke ani operacji usługowych. Brak zmian
w modelach/GPU/Ollama/ComfyUI/Hermes, sieci, secrets, workflows, .gitmodules
i recovery scripts/artifacts. Nie wykonano sudo/gh/commit/push/PR/merge.
Nowy registry jest statyczny, JobState nadal RAM-only, bez migracji storage.
Dotychczasowe release rollback paths i recovery evidence pozostają zachowane;
produkcyjne smoke/rollback/health muszą zostać zwalidowane osobno przez supervisora.

Marker `.agent-result-D3`: `READY_FOR_VALIDATION`.
