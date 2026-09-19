# AI Server — Architecture & Runtime Audit v1

**Data rozpoczęcia:** 2026-09-19  
**Status:** IN PROGRESS — repo audit wykonany, runtime audit oczekuje na wynik kolektora read-only  
**Branch audytu:** `audit/ai-server-architecture-runtime-20260919`  
**Audytowany baseline main:** `824037b0e472da56babc6bf7b7e3a2c862ee18da`

## 1. Cel audytu

Celem nie jest odtworzenie obecnego Serwera AI 1:1, lecz przygotowanie bezpiecznej przebudowy zgodnej z założeniami pre-audit:

- platforma wielodomenowa,
- wymienialne komponenty,
- niezależność od konkretnego hosta,
- stabilne kontrakty / adaptery,
- centralne zarządzanie zasobami,
- osobna warstwa wiedzy,
- GUI/API-first,
- rozdzielenie stateful/stateless,
- GitHub jako source of truth,
- obowiązkowy cleanup po zakończonych testach.

Audyt ma najpierw ustalić stan rzeczywisty. **Na tym etapie niczego nie usuwamy ani nie migrujemy.**

## 2. Zakres

Audyt składa się z dwóch części:

1. **Repo audit** — kod, dokumentacja, CI, deployment, coupling i pozostałości po etapach rozwojowych.
2. **Runtime audit** — działający host: usługi, timery, procesy, porty, modele, deploymenty, konfiguracje, katalogi danych, worktree, backupy i potencjalne artefakty tymczasowe.

Runtime zbierany jest przez:

`tools/audit_ai_server_runtime_v1.sh`

Skrypt jest read-only i nie wykonuje restartów, instalacji, usuwania ani zmian konfiguracji.

---

# 3. Repo audit — stan obecny

## 3.1. Mocne strony / elementy do zachowania

### KEEP / baza do dalszej ewolucji

- repo ma normalny pakiet Python w `src/ai_bridge`,
- istnieją wydzielone katalogi `api`, `core`, `storage`, `adapters`, `analysis`, `gateway`,
- konfiguracja aplikacji jest oparta o `pydantic-settings`,
- baza jest abstrahowana przez SQLAlchemy; development może używać SQLite, produkcja PostgreSQL,
- istnieją migracje Alembic,
- system ma testy pytest,
- istnieje izolowany `ai-gateway` i centralny scheduler/admission control,
- istnieją endpointy health/status i diagnostyczne nagłówki gatewaya,
- systemd units mają część dobrych zabezpieczeń (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem`),
- sekrety nie są przechowywane w przykładowych env; repo zawiera placeholdery,
- istnieją raporty wdrożeniowe i rollback scripts,
- istniejące ADR-003 i ADR-005 są zgodne kierunkowo z przyszłą platformą wielodomenową.

Wniosek: obecnego kodu nie należy wyrzucać. Znaczna część może zostać **MIGRATE/REFACTOR**, zamiast pisać platformę całkowicie od zera.

## 3.2. Documentation drift

README nadal opisuje:

- stan hosta z 08.08.2026,
- AI Bridge jako „kolejny etap”,
- wczesny etap projektu.

Jednocześnie repo zawiera:

- AI Bridge 0.4.0,
- produkcyjny AI Gateway,
- centralny Resource Manager / queue,
- integrację Hermesa,
- lokalny image/video stack.

**Klasyfikacja:** MIGRATE / UPDATE.

Po audycie potrzebny jest jeden aktualny dokument `CURRENT_STATE` lub generowany inventory. README nie może być jednocześnie historycznym checkpointem i bieżącym opisem produkcji.

## 3.3. Kolizja numeracji ADR

Repo posiada co najmniej:

- `ADR-005_AI_GATEWAY_SCHEDULER_PL.md`
- `ADR-005_VENTILATION_AI_ANALYSIS_EXECUTION_PL.md`

Numer ADR nie jest unikalny.

**Klasyfikacja:** MIGRATE.

Po audycie należy uporządkować indeks ADR i nadać stabilne identyfikatory.

## 3.4. Silne powiązanie z jednym hostem/użytkownikiem

W kodzie deploymentowym i unitach występują na sztywno m.in.:

- użytkownik/grupa `harrypotter`,
- `/opt/ai-bridge`,
- `/opt/ai-gateway`,
- `/srv/ai-data/hermes`,
- `/usr/local/libexec/ai-server`,
- lokalne adresy/porty,
- w części rollbacków historyczny adres hosta.

To utrudnia:

- migrację na nowy serwer,
- multi-node,
- odtworzenie na innym użytkowniku,
- automatyczny bootstrap.

**Klasyfikacja:** MIGRATE.

Docelowo wartości host-specific powinny pochodzić z konfiguracji/deployment manifestu, nie z kodu biznesowego.

## 3.5. Silne powiązanie z Ollamą i Qwenem

Aktualne `Settings` zawiera bezpośrednio:

- `ollama_url`,
- `ollama_model=qwen3.6:35b`.

Istnieje dedykowany `OllamaClient`, a część narzędzi/testów ma na sztywno nazwy modeli `qwen3.6:35b*`.

To jest poprawne dla obecnej implementacji, ale nie spełnia przyszłej zasady:

> aplikacja prosi o capability, a nie o konkretny produkt/model.

**Klasyfikacja:** MIGRATE.

Potrzebna przyszła warstwa `LLMProvider` / model registry / capability routing. Ollama ma zostać adapterem, a nie kontraktem platformy.

## 3.6. AI Gateway jest dobrym fundamentem, ale nadal jest implementacją v1

Pozytywne elementy:

- centralny admission control,
- kolejka priorytetowa,
- resource leases,
- HTTP compatibility,
- health/status,
- oddzielenie od Hermesa.

Ograniczenia:

- v1 jest silnie oparty o upstream Ollama,
- priorytety zawierają domenę `ventilation` jako first-class config,
- model zasobów nie jest jeszcze pełnym capability/resource schedulerem,
- image/video są dołączane przez dodatkowe mechanizmy lease/patch, a nie przez jednolity kontrakt workerów.

**Klasyfikacja:** KEEP + EVOLVE.

Nie usuwać. To kandydat do ewolucji w przyszły Resource Manager.

## 3.7. Nagromadzenie artefaktów etapowych

Repo zawiera dużą liczbę:

- `stageXX` installerów,
- cutover scripts,
- rollback scripts,
- patcherów Hermesa,
- wersjonowanych generatorów/prompt compilerów,
- testów nazwanych według etapów,
- raportów poszczególnych stage.

Przykłady: stage23–stage30 dla local video/image oraz wiele wcześniejszych cutoverów.

Część może być nadal potrzebna do odtworzenia produkcji lub rollbacku, więc **na etapie audytu niczego nie kasujemy**.

**Klasyfikacja:** REVIEW -> później KEEP / ARCHIVE / DELETE.

Po runtime audit należy ustalić, które wersje są rzeczywiście wdrożone. Po finalnej migracji stare jednorazowe artefakty powinny zostać usunięte zgodnie z globalną Development Hygiene Policy.

## 3.8. Skrypty instalacyjne zależą od historycznych branchy

W kilku produkcyjnych/operacyjnych skryptach występuje np.:

`BRANCH="feat/ai-gateway-scheduler"`

lub inne stare branche etapowe.

To oznacza, że „source of truth = main” nie jest jeszcze konsekwentnie realizowane.

**Klasyfikacja:** MIGRATE.

Finalne install/deploy nie powinno wymagać starych feature branchy.

## 3.9. CI/CD jest zbyt związane z historią etapów

Jedyny widoczny workflow nosi nazwę `AI Gateway tests` i zawiera:

- listę wielu historycznych branchy feature/stage,
- bardzo długą ręcznie utrzymywaną listę stage scripts,
- pełny `pytest`, ale trigger push nie obejmuje ogólnie `main`.

**Klasyfikacja:** MIGRATE.

Docelowo CI powinno być oparte o stabilne komponenty i kontrakty, a nie numery etapów.

## 3.10. Deployment nie jest jeszcze desired-state

Aktualny deployment jest głównie zestawem imperatywnych skryptów:

- install,
- cutover,
- patch,
- rollback.

To dobrze wspierało bezpieczne eksperymentowanie, ale przyszła platforma wymaga powtarzalnego sposobu określenia:

> taki ma być docelowy stan hosta.

**Klasyfikacja:** MIGRATE.

Po audycie należy wybrać prosty mechanizm bootstrap/deployment (bez wprowadzania nadmiernej złożoności).

## 3.11. Dane stateful są częściowo wydzielone, ale brakuje pełnego DR

W repo są już:

- PostgreSQL,
- Alembic,
- `/var/lib/ai-bridge`,
- `/srv/ai-data`,
- oddzielne deployment dirs.

Brakuje jednak jednej formalnej polityki:

- backup,
- restore,
- weryfikacja backupu,
- RPO/RTO,
- migracja hosta,
- odtworzenie wszystkich usług na czystej maszynie.

**Klasyfikacja:** MISSING — zaprojektować po runtime audit.

## 3.12. Security architecture jest niepełna

Pozytywne:

- sekrety poza repo,
- localhost dla AI Gateway,
- podstawowy systemd hardening.

Brakuje docelowej platformowej specyfikacji:

- service-to-service auth,
- użytkownicy/role GUI,
- permissions per domain,
- secret management,
- audit log,
- polityka ekspozycji do LAN/VPN.

**Klasyfikacja:** MISSING.

## 3.13. Observability jest częściowa

Obecnie są:

- journal/systemd,
- `/health`,
- `/status`,
- diagnostyczne nagłówki requestów.

Brakuje spójnej warstwy platformowej:

- metrics,
- tracing/correlation IDs,
- dashboard health,
- alerting,
- historia jobów,
- resource utilization per capability/node.

**Klasyfikacja:** MIGRATE / EXTEND.

---

# 4. Wstępna mapa klasyfikacji

| Obszar | Wstępna decyzja |
|---|---|
| Python package / API / SQLAlchemy / Alembic | KEEP / REFACTOR |
| adapter wentylacji i logika domenowa | KEEP, wydzielić jako domenę WVC |
| AI Gateway / scheduler | KEEP / EVOLVE |
| Ollama client | MIGRATE do provider adapter |
| Qwen hardcoding | MIGRATE do model registry/capability |
| Hermes integration | MIGRATE do AgentProvider adapter |
| PostgreSQL | KEEP kandydat, potwierdzić po audycie |
| stage scripts | REVIEW / ARCHIVE / DELETE po runtime |
| rollback backups | REVIEW po runtime |
| README / część raportów „current state” | UPDATE / ARCHIVE |
| stare feature-branch pins | DELETE/MIGRATE po potwierdzeniu |
| obecne systemd units | MIGRATE do parametrów/deployment manifestu |
| current CI workflow | REFACTOR |
| backup/restore platformy | MISSING |
| security platformy | MISSING |
| unified observability | MISSING |
| knowledge-service / RAG | MISSING — projektować po audycie |
| AI Control Center GUI | MISSING — późniejszy etap |

---

# 5. Runtime audit — dane wymagane przed decyzjami

Kolektor ma potwierdzić:

- rzeczywisty OS/kernel/hardware,
- aktualny RAM/UMA/GPU,
- dyski i mounty,
- faktyczne usługi systemd i user-systemd,
- timery/cron,
- otwarte porty,
- Docker/containers,
- wersje Ollama/models,
- realne deploymenty `/opt`,
- repo/branch/dirty state,
- Hermes commit/branch/runtime,
- katalogi stateful,
- nazwy aktywnych zmiennych konfiguracyjnych bez wartości,
- worktree/test directories,
- stare backupy i stage artifacts,
- failed units.

Dopiero wtedy można sklasyfikować każdy element jako:

`KEEP / MIGRATE / DEPRECATE / DELETE`.

---

# 6. Zakaz cleanupu przed zakończeniem audytu

Globalna zasada cleanupu po testach nadal obowiązuje, ale audyt istniejącego środowiska jest wyjątkiem proceduralnym:

- nie kasujemy artefaktu tylko dlatego, że wygląda na stary,
- najpierw ustalamy, czy jest częścią aktywnego runtime lub wymaganym rollbackiem,
- po sklasyfikowaniu i po migracji zbędne artefakty usuwamy natychmiast.

---

# 7. Następny krok

Uruchomić na produkcyjnym Serwerze AI kolektor:

```bash
cd ~/AI-server
git fetch origin audit/ai-server-architecture-runtime-20260919
git show origin/audit/ai-server-architecture-runtime-20260919:tools/audit_ai_server_runtime_v1.sh \
  | bash > ~/ai-server-runtime-audit-2026-09-19.txt
```

Następnie przekazać plik `~/ai-server-runtime-audit-2026-09-19.txt` do analizy.

**Nie commitować surowego outputu runtime do publicznego repo.** Może zawierać prywatne adresy IP, hostnames, nazwy usług i strukturę infrastruktury. Do repo trafi wyłącznie zredagowany raport końcowy.
