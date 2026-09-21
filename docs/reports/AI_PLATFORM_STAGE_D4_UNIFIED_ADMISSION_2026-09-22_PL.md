# AI Platform — Stage D.4 Unified admission

**Data:** 2026-09-22  
**Status:** READY FOR SUPERVISOR VALIDATION — implementation ready for supervisor validation  
**Zakres:** wyłącznie D.4; bez production validation/cutover.

## Implementacja

D.4 wykorzystuje istniejący `PriorityScheduler` i `ResourceLeaseRegistry`, bez
przepisania schedulera. Nowe `gateway/admission.py` definiuje niemutowalne
`WorkloadBinding(provider, node, capability)` i stałe profile admission.
Binding jest walidowany przez registry D.3 przed enqueue; HTTP assignment musi
należeć do dopuszczonego planu. JobState dodaje workload i zachowuje D.2 lifecycle,
identyfikatory, czasy, terminal history oraz reservation semantics.

Wszystkie dziewięć scheduled HTTP tras (w tym streaming i embeddings) buduje
jawny binding obecnego Ollama providera. Direct proxy helper ma zamkniętą listę
wyłącznie GET tags/models; brak domyślnego routingu nieznanej expensive trasy.
Nie ma zmiany modeli, URL backendu ani body poza dotychczasowym D.1 polem.

Lease może deklarować workload `llm`, `embeddings`, `media-image`, `media-video`
lub legacy `external` (default przy braku pola). Media plan obejmuje kolejno
Qwen i ComfyUI pod jednym slotem. Profile nie wybierają modeli ani workflow.
Explicit priorities i semantic precedence, WVC=10, FIFO, queue limit,
max_concurrency i brak preemption pozostają bez zmian.

Leased HTTP waliduje workload i odrzuca drugi równoległy use (409), zapobiegając
przekroczeniu admission przez współdzielenie jednego ticketu. Nowe localhost API
`POST /resource/leases/{lease_id}/uses` dopuszcza jedną zewnętrzną fazę ComfyUI;
DELETE z jej use_id kończy tylko tę fazę. Przestarzały use_id nie kończy nowej.
Nie tworzy dodatkowego joba ani slotu, nie zmienia reservation assignment na
ComfyUI i nie uznaje zwolnienia za sukces renderu. Publiczny status dodaje
workload bindings i aktualną external phase bez prompt content, body/modelu,
provider output lub use_id. Dotychczasowe legacy source/priority pola pozostają.

`ComfyUIAdapter.generate()` wymaga aktywnego lease przed workflow, stagingiem
plików i backend submission. Odmowa/unavailable RM/missing lease daje
`MediaProviderError`, bez direct fallback; error response pozostaje generyczne.
Health/describe/read-only preflight nie wymagają admission. `/wideo` repo wrapper
deklaruje media-video; `/foto` deklaruje media-image i obejmuje tym samym guardem
legacy generator po fazie Qwen. Repo helper ma opcjonalny workload i external-use
context; dotychczasowy caller bez nowego pola nadal działa. Nie zmieniono patcha
produktu Hermes ani kodu WAIT/START/delivery.

HTTP in_use nadal chroni przed idle TTL i wspiera deferred release. External
phase jest heartbeat-owned, bez nieusuwalnego HTTP pin: po śmierci workera TTL
nadal zwalnia rezerwację. Cancellation podczas tworzenia lease nie pozostawia
orphan scheduler slotu. Zwolnienie/reaping nie usuwa rekordu lease przed
zwolnieniem schedulera; cancellation oczekiwania na scheduler zachowuje reaper
owner. Istniejące recovery paths i artefakty nie zostały zmienione.

## Embeddings i granice architektury

Obecne Ollama embedding HTTP routes korzystają z tego samego modelu admission.
Kontrakt przyszłego EmbeddingProvider wymaga descriptor-validated embeddings
binding i wspólnego slotu przed wykonaniem. Nie wdrożono adaptera, embedding
modelu, Knowledge Service, vector DB, nowych provider types ani multi-node.
Sam wpis registry nie uprawnia przyszłego dispatchera do pominięcia admission.

Szczegółowe profile, HTTP błędy, status i lifecycle:
[Component Contracts §7.3](../architecture/AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#73-unified-admission--stage-d4).
README, target architecture i migration plan wskazują bieżący krok D.4.
Starsze paragrafy D.2/D.3 opisują historyczny zakres swoich etapów; §7.3 jest
addytywnym kontraktem D.4.

## Testy implementacyjne

Interpreter: `/home/harrypotter/AI-server/.venv/bin/python`, tylko uruchamianie
z `PYTHONPATH=src` tego worktree. Bez instalacji/zmian zależności, bez realnych
backendów i bez wysyłania powiadomień. Testy transportów używają mocków/ASGI.

- **49 nowych testów D.4 PASS**: profile i descriptor validation, wszystkie
  scheduled routes, atomowe invalid admission, privacy, Qwen -> ComfyUI pod
  jednym lease z oczekującym embeddingiem, serializacja HTTP/external use,
  stale phase cleanup, queue limit, queued claim rejection, cancellation,
  heartbeat/TTL po worker crash, direct helper guard, adapter fail-closed,
  finally cleanup oraz legacy image wrapper/helper.
- **537 PASS** — suite z pominięciem czterech modułów TestClient.
- **3 PASS** — niezależne corestate tests.
- Łącznie **540 różnych testów PASS**; focused/new tests są podzbiorami tej liczby.
- Po końcowej normalizacji błędu admission do `MediaProviderError`:
  **57 PASS** — nowe D.4 tests + media provider contract tests.
- Python compile zmienionych pakietów/helperów: PASS.
- `git diff --check`: PASS.

Dostosowano dwa istniejące harnessy: explicit lista pól JobState dopuszcza nowe
workload; izolowane Stage C media contract tests wstrzykują mock admission,
podczas gdy D.4 testy niezależnie sprawdzają obowiązkowy realny guard.

Polecenia:

```bash
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest tests/test_gateway_unified_admission.py tests/test_media_admission.py tests/test_media_provider_contracts.py
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest --ignore=tests/test_gateway_resource_api.py --ignore=tests/test_analysis_delivery_api.py --ignore=tests/test_api.py --ignore=tests/test_corestate_extension.py
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest tests/test_corestate_extension.py -k 'not integrated_cm5_corestate_is_accepted_by_ingest'
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m compileall -q src/ai_bridge/gateway src/ai_bridge/providers tools/hermes_resource_queue.py tools/local_image/hermes_foto_dispatch_global.py tools/local_video/hermes_video_dispatch_global.py
git diff --check
```

Pełny pytest **NIEUKOŃCZONY**: timeout 25 s. Osobny istniejący
`test_gateway_resource_api.py` timeout 10 s, faulthandler po 5 s:
`TestClient.__enter__ -> start_task_soon -> run_sync_from_thread`, przed requestem.
To odpowiada ograniczeniu implementacyjnych sesji D.1–D.3; nie zmieniono harnessu
ani zależności. **18 istniejących przypadków TestClient wymaga supervisora.**

## Handoff, produkcja i rollback

Implementacja gotowa do walidacji supervisora; nie oznacza zamknięcia etapu ani
potwierdzenia działania na produkcji. Supervisor posiada commit/build/CI i merge.

Nie wykonano release build: builder wymaga clean committed source. Dotychczasowe
Stage D tooling nadal raportuje D.0 phase/migration i ma D.0 runtime guardy.
To historyczne recovery tooling, nie gotowy produkcyjny kandydat D.4. Nie zmieniano
go ani `.github/workflows`, `.gitmodules`, systemd, sekretów lub konfiguracji hosta.
Nie wykonano sudo, gh, commit, push, PR, deploy, restart, cutover ani rollback.

Przy późniejszym przygotowaniu produkcji potrzebna jest zgodna wersja Gateway,
packaged ComfyUI adaptera oraz zmienionych repo media wrapperów/helpera.
Nowy guard ze starym Gateway fail-closed (brak uses API). Instalacja samych
source packages nie potwierdza aktualizacji kopii helperów w libexec; supervisor
musi uwzględnić ten inventory i przywracanie dopasowanego zestawu przy rollbacku.
Nie dodano nowego patch-in-place Hermesa. D.0 r2 i Stage C r3 pozostają zachowanymi
recovery punktami, bez nowej walidacji ich rollbacku w tej sesji.

Zakres gwarancji to supported Gateway i managed media entry points. Historyczne
low-level generatory/recovery tooling i jawny direct-Ollama recovery mode nie są
usuwane ani migrowane w D.4; nie stanowią nowego publicznego interfejsu. Admission
nie jest granicą bezpieczeństwa wobec operatora mającego bezpośredni dostęp do
localhost backendów. Zewnętrzny worker nadal odpowiada za heartbeat przez cały
render. TTL/release zwalnia rezerwację, **nie anuluje zdalnego renderu ComfyUI**;
nie ma nowego product cancellation/restart/recovery protokołu. Po utracie workera
może pozostać wykonanie w backendzie jak w bazowym kontrakcie external leases.
Realne crash/TTL/media-idle scenariusze wymagają D.6 production validation.

D.5 compatibility migration i D.6 real WVC/Telegram/Discord/media smoke,
concurrency, runtime health oraz rollback pozostają osobnymi etapami.
