# Handoff — AI Platform Stage A

**Data:** 2026-09-19  
**Status:** READY TO START IN A NEW CONVERSATION  
**Repo:** `autoklinika/AI-server`  
**Source of truth:** `main`

## 1. Punkt startowy

Audit v1.2 został zakończony, a post-audit Target Architecture v1 została scalona do `main`.

Aktualny commit architektury w `main`:

`9ebfb63d6595f43786cd39309e7833e65452d4b4`

Nie rozpoczynamy kolejnej rozmowy od historii eksperymentów. Nowa rozmowa ma zacząć od dokumentów docelowych.

## 2. Dokumenty obowiązkowe do przeczytania przed pracą

W tej kolejności:

1. `docs/architecture/README.md`
2. `docs/architecture/AI_PLATFORM_TARGET_ARCHITECTURE_V1_PL.md`
3. `docs/architecture/AI_PLATFORM_COMPONENT_CONTRACTS_V1_PL.md`
4. `docs/architecture/AI_PLATFORM_MIGRATION_PLAN_V1_PL.md`
5. `docs/audit/AI_SERVER_ARCHITECTURE_RUNTIME_AUDIT_2026-09-19_PL.md`
6. `docs/DEVELOPMENT_HYGIENE_POLICY_PL.md`

Historyczne stage reports i stare skrypty są materiałem pomocniczym, a nie źródłem docelowej architektury.

## 3. Następny etap

**Stage A — Recovery Baseline + Reproducible Release Foundation**

Cel Stage A:

- nie zmieniać funkcjonalności użytkowej,
- nie zmieniać modelu Qwen,
- nie wymieniać Hermesa,
- nie przepisywać AI Gateway,
- najpierw zapewnić reprodukowalny deployment i bezpieczny recovery point.

## 4. Zakres Stage A

1. Zweryfikowany backup PostgreSQL.
2. Backup krytycznych danych/config/state.
3. Capture pełnego diffu dirty Hermesa.
4. Inventory aktywnych custom systemd units/drop-ins.
5. Release manifest:
   - git SHA,
   - release ID,
   - config schema,
   - migration version,
   - provider/model config version.
6. Wersjonowany deployment, np.:
   ```text
   /opt/ai-platform/releases/<release-id>/
   /opt/ai-platform/current -> releases/<release-id>
   ```
7. Build/release stamp dostępny diagnostycznie.
8. Reprodukowalny deploy z GitHub.
9. Zweryfikowany rollback do poprzedniego release.
10. Cleanup artefaktów utworzonych przez Stage A po pozytywnych testach.

## 5. Ważne fakty z audytu

- obecna produkcja działa stabilnie,
- AI Gateway jest dobrym fundamentem i pozostaje,
- PostgreSQL zawiera zachowaną telemetrię WVC,
- WVC jest obecnie odłączony,
- Hermes ma dirty checkout i branch divergence; NIE resetować bez capture diff,
- AI Bridge ma starszy deployment niż lokalny checkout,
- Ollama i ComfyUI są dostępne w LAN; security hardening jest późniejszym etapem P1,
- istnieje dużo historycznych worktree/stage/backup artifacts; NIE usuwać ich przed nowym verified recovery point,
- host firewall jest obecnie otwarty (`INPUT accept`),
- cleanup po testach jest globalną, obowiązującą zasadą workflow.

## 6. Zakazane działania na początku Stage A

Nie wolno:

- resetować/aktualizować Hermesa przed zapisaniem jego pełnego diffu,
- usuwać starych backupów/worktree przed utworzeniem nowego recovery point,
- zmieniać modelu,
- wymieniać Ollamy/Hermesa/ComfyUI,
- zmieniać zachowania WVC,
- wdrażać RAG/Knowledge Service,
- zaczynać GUI,
- robić security cutover razem z fundamentem release.

Stage A ma być zmianą infrastruktury deployment/recovery, nie funkcji AI.

## 7. Definition of Done Stage A

Stage A jest zakończony dopiero, gdy:

- backup jest wykonany i restore test PASS,
- Hermes diff jest bezpiecznie zachowany,
- produkcja ma jednoznaczny release/build ID,
- deployment można odtworzyć z GitHub,
- working checkout nie jest wymagany do działania produkcji,
- rollback jest przetestowany,
- health/smoke tests PASS,
- nie ma nowego nieplanowanego dirty state,
- wszystkie tymczasowe artefakty Stage A są posprzątane,
- raport Stage A i decyzje są zapisane w repo.

## 8. Jak rozpocząć nową rozmowę

W nowej rozmowie użytkownik może napisać dokładnie:

> **Kontynuujemy projekt Serwer AI. Zaczynamy Stage A. Przeczytaj handoff `docs/handoffs/AI_PLATFORM_STAGE_A_HANDOFF_2026-09-19_PL.md` oraz wskazane w nim dokumenty z repo `autoklinika/AI-server`. Najpierw sprawdź aktualny stan `main`, a potem poprowadź Stage A zgodnie z Migration Plan. Nie zmieniaj jeszcze funkcjonalności produkcji.**

Po takim poleceniu nie trzeba odtwarzać historii tej rozmowy ręcznie.

## 9. Organizacja kolejnych etapów

Każdy większy etap powinien kończyć się:

1. raportem w repo,
2. aktualizacją odpowiednich ADR/architecture docs,
3. cleanupem,
4. zamknięciem issue etapu,
5. utworzeniem handoffu do kolejnego etapu, jeśli kolejna praca ma zacząć się w nowej rozmowie.

To ma być stały wzorzec pracy przy długich etapach projektu.
