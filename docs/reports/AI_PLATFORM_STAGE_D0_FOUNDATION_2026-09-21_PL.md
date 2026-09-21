# AI Platform — Stage D.0 Foundation Cleanup

**Data:** 2026-09-21  
**Branch:** `feat/stage-d0-foundation`  
**Issue:** #37  
**Status:** production r2 active; WVC/Gateway and media/Telegram regressions PASS; rollback validation pending

## 1. Cel

D.0 zamyka luki P1 wskazane w audycie po Stage C przed zmianami Resource Manager v2.

## 2. Zmiany przygotowane w repo

- CI uruchamiane na PR do `main` i push do `main`, bez historycznych branch/path filtrów;
- full pytest, provider/contract tests, syntax/compile checks i release-build validation;
- `Settings.analysis_use_gateway=True` oraz `AI_BRIDGE_ANALYSIS_USE_GATEWAY=true` w desired env;
- direct Ollama pozostaje wyłącznie jawnym recovery/debug compatibility mode;
- canonical systemd units wskazują `/opt/ai-platform/current/services/...`;
- analysis unit wymaga `ai-gateway.service` i nie nadpisuje URL do Ollamy;
- `deploy/stage-d/` ma osobny builder/install/validate/activate/rollback; rollback obsługuje jawny znany-dobry `RELEASE_ID`, aby test odtwarzania nie zależał od ostatniego pośredniego release;
- Stage D builder dopuszcza zmiany Gateway/Resource Manager i zapisuje bogatszy manifest;
- canonical systemd ma idempotent install/restore bez automatycznego restartu usług;
- canonicalization usuwa również historyczne `90-production-source.conf` oraz `10-ai-gateway.conf`, które mogły nadpisywać release-managed `PYTHONPATH`/`ExecStart`; drop-iny są wcześniej zachowywane w baseline do jawnego restore;
- produkcyjny `AI_BRIDGE_ANALYSIS_USE_GATEWAY=true` ma osobną migrację z zachowaniem baseline i skryptem restore;
- Stage C tooling i historyczne drop-iny pozostają recovery evidence.

## 3. Granice D.0

D.0 nie wprowadza semantic priority classes, JobState, provider/node registry ani unified admission. To zakres D.1–D.4.

D.0 nie zmienia Qwen, Ollamy, ComfyUI ani Hermesa jako produktów i nie rozpoczyna Knowledge Service.

## 4. Produkcja

Commit zmian D.0 nie zmienia aktywnego runtime. Produkcja pozostaje na zwalidowanym Stage C release do czasu:

1. zielonego CI branch/PR,
2. zbudowania i instalacji D.0 release bez aktywacji,
3. walidacji final-path release,
4. zastosowania odwracalnej migracji Gateway-default w `/etc/ai-bridge/ai-bridge.env`,
5. instalacji canonical systemd,
6. kontrolowanego cutoveru przy idle Resource Managerze,
7. real smoke/E2E i sprawdzenia rollbacku.

## 5. Exit criteria

- wszystkie testy automatyczne PASS;
- Stage D release build PASS;
- production cutover + health PASS;
- WVC platform-path regression PASS; jeśli CM5/WVC jest fizycznie odłączony, brak świeżej telemetrii jest oczekiwany, a walidacja obejmuje kontrakt ingestu oraz realny request `ventilation` przez Gateway/Qwen;
- real media regression PASS: external Resource Manager lease held across Stage30 render, H.264 640x384/24 fps/25 frames, queues return idle, no service restarts;
- Telegram `/wideo` real user-path regression PASS;
- rollback PASS;
- issue #37 i dokumentacja zamknięte po realnej walidacji.
