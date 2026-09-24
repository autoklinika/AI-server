# AI Platform — Stage J recovery rerun

**Data:** 2026-09-24
**Status:** production gate rerun required

Podczas wznowienia Stage J zastano aktywny release J z istniejącymi immutable markerami poprzedniego cyklu. Kontrolny rollback J -> I oraz rollback smoke przeszły, ale ponowna reaktywacja na tym samym source SHA została poprawnie odrzucona przez write-once evidence (`60_reactivate.json` już istniał).

Nie usuwamy ani nie nadpisujemy wcześniejszych dowodów. Ten commit nadaje recovery rerun nowy source SHA, aby wykonać od Stage I pełny, świeży i audytowalny cykl: `preflight -> data backup/ingest/integrity -> build -> J -> I -> J -> finalize`.

Dane kanoniczne pozostają idempotentne; drugi przebieg PDF musi utworzyć 0 nowych wersji i 0 nowych chunków. Stary release i evidence pozostają zachowane do diagnostyki.

## Messaging boundary recovery hardening

Rollback smoke ujawnił wyścig po restarcie Hermes: `gateway_state.json` raportował kanały jako connected, ale pierwszy realny outbound mógł jeszcze trafić w krótkie okno niedostępności. Telegram i Discord zostały następnie zweryfikowane osobnymi probe'ami jako sprawne. Stage J gate dodaje ograniczony retry messaging boundary oraz recoverable smoke evidence, bez kasowania wcześniejszych markerów i bez osłabiania fail-closed dla trwałych błędów.
