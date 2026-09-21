# AI Platform — Stage D.0 Foundation Cleanup

**Data:** 2026-09-21  
**Branch:** `feat/stage-d0-foundation`  
**Issue:** #37  
**Status:** implementation in progress; production cutover not performed

## 1. Cel

D.0 zamyka luki P1 wskazane w audycie po Stage C przed zmianami Resource Manager v2.

## 2. Zmiany przygotowane w repo

- CI uruchamiane na PR do `main` i push do `main`, bez historycznych branch/path filtrów;
- full pytest, provider/contract tests, syntax/compile checks i release-build validation;
- `Settings.analysis_use_gateway=True` oraz `AI_BRIDGE_ANALYSIS_USE_GATEWAY=true` w desired env;
- direct Ollama pozostaje wyłącznie jawnym recovery/debug compatibility mode;
- canonical systemd units wskazują `/opt/ai-platform/current/services/...`;
- analysis unit wymaga `ai-gateway.service` i nie nadpisuje URL do Ollamy;
- `deploy/stage-d/` ma osobny builder/install/validate/activate/rollback;
- Stage D builder dopuszcza zmiany Gateway/Resource Manager i zapisuje bogatszy manifest;
- canonical systemd ma idempotent install/restore bez automatycznego restartu usług;
- Stage C tooling i historyczne drop-iny pozostają recovery evidence.

## 3. Granice D.0

D.0 nie wprowadza semantic priority classes, JobState, provider/node registry ani unified admission. To zakres D.1–D.4.

D.0 nie zmienia Qwen, Ollamy, ComfyUI ani Hermesa jako produktów i nie rozpoczyna Knowledge Service.

## 4. Produkcja

Commit zmian D.0 nie zmienia aktywnego runtime. Produkcja pozostaje na zwalidowanym Stage C release do czasu:

1. zielonego CI branch/PR,
2. zbudowania i instalacji D.0 release bez aktywacji,
3. walidacji final-path release,
4. instalacji canonical systemd,
5. kontrolowanego cutoveru przy idle Resource Managerze,
6. real smoke/E2E i sprawdzenia rollbacku.

## 5. Exit criteria

- wszystkie testy automatyczne PASS;
- Stage D release build PASS;
- production cutover + health PASS;
- WVC regression PASS;
- Telegram/media regression PASS;
- rollback PASS;
- issue #37 i dokumentacja zamknięte po realnej walidacji.
