# AI Platform — Stage D.5 Compatibility migration

**Data:** 2026-09-22  
**Status:** READY FOR SUPERVISOR VALIDATION — implementation ready for supervisor validation  
**Zakres:** wyłącznie D.5; bez production validation/cutover. D.6 nie rozpoczęto.

## Implementacja

Minimalna migracja istniejących klientów na kontrakty D.1–D.4:

- WVC `analysis/main.py` wybiera istniejący namespace `/clients/ventilation`
  zamiast generic `/api/chat`. Dzięki temu realny caller zapisuje JobState
  domain=wvc, capability=reasoning. Już namespaced URL nie jest dublowany.
  Jawny numeric priority z Settings (także niestandardowy), model, schema,
  timeout, analiza, output i advisory-only behavior pozostają bez zmian.
- Repo `hermes_resource_queue.acquire_resource` adaptuje dokładne źródła
  `telegram-chat` / `discord-chat` do workload `llm`, jeśli caller nie podał
  workload. To istniejące call sites patcha Hermes v4; nie dodano nowego patcha
  produktu. Jawny workload ma pierwszeństwo, nieznany legacy worker nadal ma
  `external`. Publiczny Gateway nie zgaduje workload na podstawie source.
- Foto/video prompt compilers wymagają loopback Gateway port 11435. Poprzedni
  warunek dopuszczał dowolny loopback port, także direct Ollama :11434; ten
  konfiguracyjny bypass został zamknięty. Stage30 I2V deleguje walidację URL do
  tego samego bazowego kompilatora co T2V. Nie zmieniono modeli/promptów/workflow.

D.4 już obejmuje wszystkie scheduled HTTP routes i managed media wykonanie
wspólnym admission. D.5 zachowuje ten fundament, bez przebudowy schedulera,
leases lub registry. Nie dodano Platform API ani funkcji późniejszych etapów.

## Compatibility i recovery inventory

| Ścieżka | Stan po D.5 |
|---|---|
| Native Ollama/OpenAI + `/clients/ventilation/*`, `/clients/hermes/*` | Zachowane; ten sam wire payload, upstream status/stream, numeric priority i addytywne JobState. |
| Telegram multiuser | Osobne lease/job i dokładny target chat/thread; brak zmian sesji/delivery. |
| Discord text/voice | Ten sam helper, target/thread, callback queued/active i release-after-HTTP. |
| WAIT/START | Dotychczasowy tekst i próg; brak notices przy immediate admission; best-effort delivery i first-call-only notices pozostają. |
| `/foto`, `/wideo` | Te same media-image/media-video profiles, lease headers i jeden slot przez Qwen -> ComfyUI; D.4 external-use guard bez zmian. |
| WVC recovery | `analysis_use_gateway=false` nadal jawnie wybiera `ollama_url`; brak automatycznego direct fallback po awarii Gateway. |
| Legacy external workers | Brak workload nadal obsługiwany jako external; explicit workload zawsze wygrywa. |
| Hermes helper/UX failure | Istniejący fallback patcha v4 prowadzi do scheduled Gateway HTTP, nie direct backendu. |
| Media compiler failure | Dotychczasowy kontrakt błędu/fallback: foto zatrzymuje render, video wymaga jawnego komunikatu przed original-prompt fallback. Brak direct-Qwen fallback. |
| Recovery tooling | Historyczne generatory, artefakty, skrypty release/rollback i D.0/Stage C recovery points zachowane. |

Nie zmieniono user-facing ACK, output media, target resolution, modeli, GPU,
Ollamy, ComfyUI, konfiguracji hosta ani produktu Hermes. Nowe metadata nie
przenoszą promptu. Testy privacy dotyczą Gateway status/JobState/log capture;
D.5 nie jest audytem ani migracją historycznych media job artifact/log formats.

Pełna decyzja kontraktowa:
[Component Contracts §7.4](../architecture/AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md#74-compatibility-migration--stage-d5).
README, migration plan i target architecture wskazują D.5 jako bieżący krok.

## Lokalna walidacja implementacyjna

Interpreter: `/home/harrypotter/AI-server/.venv/bin/python`, wyłącznie uruchamianie
z `PYTHONPATH=src` tego worktree. Bez instalacji/zmiany zależności. Mockowane
backendy, ASGI in-process i mockowane notifications; brak realnych usług/renderów
lub wiadomości Telegram/Discord.

- **53 nowe testy D.5 PASS** w `tests/test_compatibility_migration.py`:
  legacy/canonical HTTP aliases, sukces/HTTP 400/500, streaming bytes, tool payload,
  upstream headers, numeric priorities, v2 metadata i privacy; read-only aliases
  podczas zajętego slotu; WVC entrypoint/root/namespaced/recovery/custom priority;
  helper ze starymi callerami przeciw realnej aplikacji ASGI; jednoczesna kolejka
  dwóch Telegram userów, Discord i WVC, priorytet WVC, niezależne lease,
  WAIT/START/thread targets i voice callback; llm profile odrzuca media execution;
  explicit/legacy workload compatibility; odrzucenie direct media inference przed
  network call; foto/video I2V lease headers i cleanup na sukcesie/błędzie workera.
- **590 PASS** — suite z pominięciem czterech modułów zależnych od TestClient.
- **3 PASS** — niezależne corestate tests.
- Łącznie **593 różnych testów PASS**; 53 D.5 jest podzbiorem tej liczby.
- Python compile zmienionych modułów i nowych testów: PASS.
- D.0 foundation suite w szerokim runie obejmuje bash syntax deployment scripts.
- `git diff --check`: PASS.

Polecenia odtwarzające:

```bash
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest tests/test_compatibility_migration.py
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest --ignore=tests/test_gateway_resource_api.py --ignore=tests/test_analysis_delivery_api.py --ignore=tests/test_api.py --ignore=tests/test_corestate_extension.py
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m pytest tests/test_corestate_extension.py -k 'not integrated_cm5_corestate_is_accepted_by_ingest'
PYTHONPATH=src /home/harrypotter/AI-server/.venv/bin/python -m compileall -q src/ai_bridge/analysis/main.py tools/hermes_resource_queue.py tools/local_image/hermes_foto_prompt_compiler.py tools/local_video/qwen_prompt_compiler.py tests/test_compatibility_migration.py
git diff --check
```

Pełny pytest **NIEUKOŃCZONY**: timeout 30 s; faulthandler po 10 s pokazuje
`TestClient.__enter__ -> start_task_soon -> run_sync_from_thread` w fixture
`tests/conftest.py`, przed obsługą requestu. Ten sam symptom sesji D.1–D.4.
**18 istniejących testów wymaga ponowienia przez supervisora.** Nie zmieniono
istniejącego harnessu/dependencies. Nowy D.5 harness używa AsyncClient/ASGITransport;
bridge synchronicznego helpera używa osobnego thread i bounded polling, ponieważ
próba użycia default executor również zawieszała się przy zamykaniu event loop
w sandboxie. To zmiana wyłącznie nowego test harnessu, nie runtime queue behavior.

## Handoff i granice produkcyjne

Implementacja jest gotowa do niezależnej walidacji supervisora, nie COMPLETE.
Nie wykonano production smoke, cutover, rollback, restart/start/stop usług,
sudo, gh, commit/push/PR/merge, zmian workflows/.gitmodules, secrets lub sieci.
Nie odczytywano credential/token files ani nie modyfikowano `/opt` lub `/var/lib`.

Nie uruchamiano release build, który wymaga clean committed source. Supervisor
pozostaje właścicielem commitów/CI/build/merge. Istniejący Stage D builder i guardy
nadal mają D.0 phase/migration metadata: jak w D.1–D.4, nie są gotowym kandydatem
produkcyjnym D.5 bez osobnego przygotowania wydania.

Przyszły zgodny inventory obejmuje Gateway, packaged ComfyUI adapter, repo
resource helper, oba global media wrappers i prompt compilers foto/video
(w tym bazowy compiler używany przez Stage30). Build package nie aktualizuje
kopii libexec. Wdrożenie i rollback wymagają dopasowanego zestawu; sam nowy helper
nie dowodzi aktualizacji produkcyjnych klientów. Nie zwiększono patch-in-place
Hermesa. D.0 r2 / Stage C r3 i dotychczasowe rollback paths pozostają zachowane.

D.4 limitations nadal obowiązują: worker odpowiada za heartbeat, TTL/release
zwalnia rezerwację i nie anuluje remote ComfyUI renderu. Brak nowego protokołu
crash/cancel/recovery. Realne WVC/Telegram/Discord/media, runtime health oraz
rollback wymagają późniejszej autoryzowanej walidacji D.6; nie rozpoczęto jej.

Marker `.agent-result-D5`: `READY_FOR_VALIDATION`.
