# AI Platform — Stage J recovery rerun

**Data:** 2026-09-24
**Status:** production gate rerun required

Podczas wznowienia Stage J zastano aktywny release J z istniejącymi immutable markerami poprzedniego cyklu. Kontrolny rollback J -> I oraz rollback smoke przeszły, ale ponowna reaktywacja na tym samym source SHA została poprawnie odrzucona przez write-once evidence (`60_reactivate.json` już istniał).

Nie usuwamy ani nie nadpisujemy wcześniejszych dowodów. Ten commit nadaje recovery rerun nowy source SHA, aby wykonać od Stage I pełny, świeży i audytowalny cykl: `preflight -> data backup/ingest/integrity -> build -> J -> I -> J -> finalize`.

Dane kanoniczne pozostają idempotentne; drugi przebieg PDF musi utworzyć 0 nowych wersji i 0 nowych chunków. Stary release i evidence pozostają zachowane do diagnostyki.
