# AI Platform — Architecture Index

**Status:** POST-AUDIT v1  
**Data:** 2026-09-19

## Dokumenty nadrzędne

1. **Target Architecture**
   - `AI_PLATFORM_TARGET_ARCHITECTURE_V1_PL.md`
   - docelowy model platformy, granice odpowiedzialności, security, data, deployment, Resource Manager, provider layer i GUI.

2. **Component Contracts**
   - `AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md`
   - stabilne kontrakty dla providerów, domen, Resource Managera, Knowledge Service, storage i tooli.

3. **Migration Plan**
   - `AI_PLATFORM_MIGRATION_PLAN_V1_PL.md`
   - etapowa migracja obecnej produkcji do architektury docelowej wraz z rollbackami i Definition of Done.

4. **Audit**
   - `../audit/AI_SERVER_ARCHITECTURE_RUNTIME_AUDIT_2026-09-19_PL.md`
   - rzeczywisty stan repo i runtime, klasyfikacja KEEP/MIGRATE/DEPRECATE/DELETE oraz problemy P1/P2.

---

## Relacja do dokumentu PRE_AUDIT

Dokument:

`PRE_AUDIT_AI_PLATFORM_ARCHITECTURE_PRINCIPLES_2026-09-16_PL.md`

był materiałem roboczym przed audytem.

Po audycie v1.2 jego rolę przejmują trzy dokumenty wymienione powyżej.

PRE_AUDIT nie jest już źródłem decyzji docelowych i po włączeniu pakietu architektury do `main` powinien zostać oznaczony jako **SUPERSEDED** lub pozostać wyłącznie historycznie na branchu pre-audit.

---

## Obowiązujące wcześniejsze ADR

### ADR-003 — AI Bridge jako wspólna platforma

Zachowujemy zasadę wspólnej infrastruktury + adapterów domenowych.

Target Architecture rozwija tę decyzję:
- całość nazywamy `AI Platform`,
- `AI Bridge` staje się elementem przejściowym/usługą, a nie nazwą całego systemu.

### ADR-004 — telemetria i retencja WVC

Pozostaje obowiązujący.

Audit potwierdził zachowanie centralnej telemetrii.

### ADR-005 — AI Gateway / scheduler

Pozostaje fundamentem przyszłego Resource Managera.

Target Architecture rozszerza scheduler z ruchu Ollama na wszystkie kosztowne capabilities.

---

## Dokumenty historyczne

Raporty `stageXX`, stare cutovery, rollbacki i wcześniejsze checkpointy opisują historię wdrożeń.

Nie powinny być traktowane jako current architecture, chyba że dokument nadrzędny jawnie do nich odsyła.

---

## Source of truth po migracji

Hierarchia:

```text
Target Architecture
        ↓
Component Contracts
        ↓
ADRs konkretnych wyborów technicznych
        ↓
Migration/Deployment docs
        ↓
Code + desired-state configuration
        ↓
Runtime release/build stamp
```

W przypadku sprzeczności historyczny stage report nie może nadpisywać nowszej decyzji architektonicznej.

---

## Aktualny etap

Stage A, Stage B i Stage C są zakończone i zwalidowane.

**Stage D.0 — Foundation cleanup** jest technicznie zakończony i zwalidowany na produkcji. Aktywny runtime to `stage-d0-foundation-20260921-r2`; rollback do Stage C r3 i ponowna aktywacja r2 zostały realnie sprawdzone.

`main` jest chroniony rulesetem `main-protection`; PR musi mieć zielony `platform-ci` i być aktualny względem `main`.

Stage D.0 został zmergowany do `main` w PR #38. Aktualnym krokiem Stage D jest **D.1 — semantic priority classes**.

Szczegółowy handoff: `../reports/AI_PLATFORM_STAGE_D0_FOUNDATION_2026-09-21_PL.md`.

---

## Addendum 2026-09-24 — Stage L / EcuRepairService

Dla nowej aktywnej domeny ERS obowiązują dodatkowo:

- `AI_PLATFORM_ERS_DOMAIN_CONTRACT_V1_PL.md` — model domenowy, schema ownership,
  lifecycle, artifacts, binaries, evidence, diagnosis, Knowledge publication i gate'y L0–L5;
- `adr/ADR-007_STAGE_L0_ERS_DOMAIN_SOURCE_OF_TRUTH_2026-09-24_PL.md` —
  source of truth i granice ERS;
- `../reports/AI_PLATFORM_STAGE_L0_ERS_READ_ONLY_AUDIT_2026-09-24_PL.md` —
  stan zastany i klasyfikacja danych.

Stage L0 jest etapem dokumentacyjnym i nie zmienia aktywnego runtime Stage J.
