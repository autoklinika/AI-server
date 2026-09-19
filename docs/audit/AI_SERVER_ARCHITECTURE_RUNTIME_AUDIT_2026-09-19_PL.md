# AI Server — Architecture & Runtime Audit v1

**Data rozpoczęcia:** 2026-09-19  
**Status:** COMPLETE v1.1 — repo audit + runtime audit + supplemental runtime audit wykonane; firewall pozostaje niezweryfikowany z powodu braku nieinteraktywnego sudo  
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

# 5. Runtime audit — wynik z 2026-09-19

Kolektor read-only zakończył się poprawnie. Nie wykonał żadnych zmian na hoście.

## 5.1. Host i compute — KEEP

Stan hosta:

- Ubuntu 26.04 LTS,
- kernel 7.0.0-31-generic,
- AMD Ryzen AI 9 HX 470, 12C/24T,
- Radeon 890M / RADV,
- 128 GB fizycznej pamięci z ok. 30 GiB widocznymi dla CPU/OS przy obecnym dużym UMA,
- ok. 21 GiB pamięci systemowej dostępnej w chwili audytu.

**Klasyfikacja:** KEEP jako obecny node, ale host nie może być częścią kontraktu platformy.

## 5.2. Storage — dobry kierunek, ale wymagany nowy podział danych

Runtime ma dwa dyski 4 TB:

- system/root na SPCC 4 TB,
- dedykowany Lexar NM790 4 TB zamontowany jako `/srv/ai-data`.

`/srv/ai-data` używa ok. 5.6 GB, podczas gdy root używa ok. 168 GB. Modele Ollamy znajdują się poza wydzielonym data volume i stanowią znaczną część root.

**Klasyfikacja:** KEEP hardware/mount, MIGRATE data layout.

Docelowo trzeba jawnie zdefiniować klasy danych:

- persistent/backup-critical,
- regenerowalne modele/cache,
- job artifacts z TTL,
- logi,
- temporary/workspaces.

## 5.3. Network exposure — P1 do uporządkowania

W chwili audytu nasłuchują m.in.:

- `0.0.0.0:22` — SSH,
- `*:9090` — Cockpit,
- `0.0.0.0:8080` — AI Bridge,
- `0.0.0.0:8188` — ComfyUI,
- `*:11434` — Ollama,
- `127.0.0.1:11435` — AI Gateway,
- `127.0.0.1:8642` — Hermes.

Najważniejsza niezgodność: Ollama jest osiągalna poza localhost, podczas gdy Gateway jest lokalnym admission/resource managerem. Klient sieciowy może potencjalnie ominąć Gateway i jego kolejkę.

**Klasyfikacja:** MIGRATE — PRIORITY P1.

Po zaprojektowaniu polityki sieciowej należy ograniczyć bezpośredni dostęp do backendów inference. ComfyUI również powinno zostać ocenione pod kątem konieczności nasłuchu na wszystkich interfejsach. AI Bridge może wymagać LAN dla WVC, ale docelowo potrzebuje jawnej polityki auth/firewall.

## 5.4. Runtime services — część nie jest reprezentowana w repo

Aktywne/enable:

- Ollama,
- PostgreSQL,
- Docker,
- Tailscale,
- Cockpit,
- AI Bridge,
- AI Gateway,
- AI Bridge analysis timer,
- Hermes user service,
- ComfyUI,
- `ollama-preload.service`.

Runtime ma także custom:

- Ollama service i trzy drop-iny,
- `comfyui.service`,
- `ollama-preload.service`,
- AI Bridge production-source drop-ins,
- historyczny `ai-gateway.service.pre-stage2`.

Nie wszystkie te elementy mają odpowiadające desired-state definitions w `main`.

**Klasyfikacja:** MIGRATE.

Przed przebudową wszystkie wymagane custom units/drop-ins muszą zostać opisane w repo lub zastąpione docelowym deploymentem.

## 5.5. Brak failed systemd units — KEEP

W chwili audytu systemd nie raportuje failed units. Główne usługi AI są aktywne, a cykliczna analiza wentylacji zakończyła ostatni run kodem 0.

To potwierdza, że przebudowa powinna być migracją kontrolowaną z rollbackiem, a nie naprawą awaryjną.

## 5.6. Docker — aktywny, ale obecnie bez workloadów

Docker daemon jest aktywny, ale:

- brak działających kontenerów,
- brak custom volumes,
- tylko standardowe networks.

**Klasyfikacja:** REVIEW.

Docker może być wykorzystany w przyszłym desired-state deployment, ale obecnie nie jest wymagany przez aktywny runtime pokazany w audycie.

## 5.7. Ollama i modele — KEEP backend tymczasowo, MIGRATE kontrakt

Ollama 0.32.14 jest aktywna.

Zainstalowane są m.in.:

- qwen3.6 35B w kilku profilach,
- qwen3.8 27B,
- stary `muse-glimmer`,
- mały `qwen:latest`.

Aktywny stale w pamięci jest:

`qwen3.6:35b-hermes64k-gpu`, 23 GB, 100% GPU, context 65536, `Forever`.

**Klasyfikacja:**

- Ollama runtime: KEEP teraz / adapter później,
- Qwen: KEEP jako bieżący model, nie jako kontrakt,
- stare/duplikowane modele: REVIEW po migracji,
- preload/residency: REVIEW pod kątem przyszłego model registry i schedulera.

## 5.8. GitHub source of truth — P1

Produkcyjny katalog `~/AI-server`:

- local HEAD: `20d62498b9528dfdeae80adf6db6cc10e382343f`,
- branch: `main`,
- local status względem lokalnego `origin/main`: clean.

Zewnętrzny GitHub `main` podczas audytu:

`824037b0e472da56babc6bf7b7e3a2c862ee18da`.

Commit lokalnego hosta istnieje w repo, ale jest przodkiem aktualnego GitHub main; GitHub main jest 26 commitów dalej. Lokalny tracking ref był więc nieodświeżony po fetchu konkretnej gałęzi audit.

**Klasyfikacja:** MIGRATE — PRIORITY P1.

Po zamknięciu audytu i przed przebudową trzeba:

1. odświeżyć remote refs,
2. potwierdzić, że main hosta można bezpiecznie fast-forwardować,
3. oddzielić runtime deployment od working checkout,
4. wprowadzić deployment stamp zawierający dokładny commit/build version.

## 5.9. Produkcyjny deployment nie jest identyfikowalny jednym SHA

`/opt/ai-bridge` i `/opt/ai-gateway` nie są repozytoriami Git.

Widać też różne momenty/wersje plików oraz późniejsze patchowanie produkcji przez instalatory. Nie ma jednego trwałego manifestu mówiącego:

> dokładnie ten commit + te adaptery + te patch'e = aktualna produkcja.

**Klasyfikacja:** MIGRATE — PRIORITY P1.

Docelowy deployment musi być reprodukowalny i wersjonowany.

## 5.10. Hermes — największy przykład patch-in-place

Hermes działa z:

- repo `/srv/ai-data/hermes/hermes-agent`,
- HEAD `79445a496c86a19332ad786494b8384d2167e2d0`,
- branch `main`,
- stan `ahead 1, behind 1`,
- trzy zmodyfikowane pliki robocze:
  - `agent/turn_api_request.py`,
  - `gateway/run_inbound.py`,
  - `gateway/run_turn_runner.py`.

Oznacza to, że produkcja zależy od kodu, którego stan nie jest czystym checkoutem jednego upstream commit.

**Klasyfikacja:** MIGRATE — PRIORITY P1.

Przed jakimkolwiek resetem/upgrade Hermesa należy zachować i opisać diff. Docelowo integracja platformy nie może wymagać ręcznego patchowania kodu Hermesa; Hermes powinien być wymiennym `AgentProvider`.

## 5.11. Worktree clutter — potwierdzony dług technologiczny

Repo ma co najmniej 11 dodatkowych worktree związanych z dawnymi testami/stage:

- alert-v2,
- discord queue,
- foto stage28,
- local video stage23,
- LTX stage24/25/26/27,
- queue-final-test,
- storage-stage4,
- video-stage29.

Dodatkowo w HOME istnieją katalogi:

- `AI-server-local-artifacts-...`,
- `AI-server-local-leftovers-...`.

**Klasyfikacja:** DELETE po kontroli referencji i backupów.

To jest bezpośredni przykład, dlaczego globalna Development Hygiene Policy jest obowiązkowa.

## 5.12. Backup/stage clutter w /opt i Hermes

Istnieją:

- `/opt/ai-gateway.pre-stage2`,
- `/opt/ai-gateway.pre-stage3`,
- liczne `config.yaml.pre-*`,
- backupy stage23–stage30,
- kilka generacji Discord voice/queue backup,
- migration archives/old trees.

Część była kiedyś ważnym rollbackiem. Obecnie tworzą trudny do interpretacji stan.

**Klasyfikacja:** REVIEW -> ARCHIVE/DELETE.

Nie kasować przed:
- zachowaniem diffów aktywnej produkcji,
- utworzeniem nowego verified backupu,
- potwierdzeniem docelowego deploymentu.

## 5.13. Job/output retention — brak polityki

`/srv/ai-data` zawiera:

- wiele historycznych `hermes-video-jobs`,
- wiele `hermes-foto-jobs`,
- ComfyUI output,
- cache i media.

Łączny data volume nie jest jeszcze duży, ale nie ma widocznej wspólnej polityki TTL/retention.

**Klasyfikacja:** MIGRATE.

Docelowy Job Service/Object Storage powinien mieć jawne klasy retention i cleanup.

## 5.14. Configuration sprawl

Konfiguracja występuje równolegle w:

- `/etc/ai-bridge`,
- `/etc/ai-gateway`,
- `/opt/ai-bridge/.env`,
- `/srv/ai-data/hermes/.env`,
- wielu YAML/JSON cache/state files,
- historycznych backupach konfiguracji.

**Klasyfikacja:** MIGRATE.

Trzeba oddzielić:

- desired config,
- secrets,
- runtime state,
- cache,
- backup.

## 5.15. Permissions

Pozytywnie:

- Hermes root ma mode 700,
- `/etc/ai-bridge` ma 750,
- `/var/lib/ai-bridge` ma 750.

Do przeglądu:

- `/opt/ai-bridge` i `/opt/ai-gateway` są 775,
- `/etc/ai-gateway` jest 755.

**Klasyfikacja:** REVIEW / HARDEN.

## 5.16. Tailscale — KEEP jako warstwa administracyjna

Tailscale działa i obecny serwer oraz laptop są online. Jest to dobry kandydat dla administracyjnego plane, niezależny od publicznego/LAN API aplikacji.

**Klasyfikacja:** KEEP, ale polityka dostępu powinna trafić do security architecture.

---


## 5.17. Supplemental audit v1.1 — ComfyUI i Ollama preload

ComfyUI jest aktywną usługą systemową i uruchamia się z parametrem:

`--listen 0.0.0.0 --port 8188`.

Jest więc świadomie wystawione na wszystkie interfejsy hosta. Nie jest to tylko przypadkowy efekt konfiguracji aplikacji.

`ollama-preload.service` jest również aktywne/enabled i uruchamia lokalny helper `/usr/local/sbin/ollama-preload-qwen36`. Unit/preload helper nie ma odpowiednika w aktualnym `main` repozytorium AI-server.

**Klasyfikacja:**

- ComfyUI: KEEP jako bieżący backend media, MIGRATE do wymiennego worker/provider adaptera; exposure P1,
- Ollama preload/residency: REVIEW/MIGRATE do model registry/resource policy; desired-state definition musi trafić do repo.

## 5.18. Firewall — UNKNOWN

Kolektor nie mógł odczytać reguł UFW/nftables bez interaktywnego sudo.

To oznacza, że sam fakt nasłuchu `0.0.0.0/*` nie wystarcza do stwierdzenia realnej dostępności spoza hosta, ale jest wystarczający do oznaczenia polityki sieciowej jako P1 do weryfikacji.

**Klasyfikacja:** SECURITY ACTION REQUIRED.

## 5.19. Storage usage — modele są głównym konsumentem

Rozmiary w chwili audytu:

- `/srv/ai-data`: ~5.6 GB,
- Hermes: ~5.4 GB,
- ComfyUI output: ~108 MB,
- AI Bridge DB/data dir: minimalny filesystem footprint poza PostgreSQL,
- `/opt/ai-bridge`: ~114 MB,
- `/opt/ai-gateway`: ~85 MB,
- każdy stary `/opt/ai-gateway.pre-stage*`: ~85 MB,
- Ollama model store: ~58 GB.

Wniosek: obecny problem storage nie jest pojemnościowy. Ważniejsza jest klasyfikacja danych i reprodukowalność. Modele Ollamy są regenerowalne i powinny być traktowane inaczej niż dane użytkowe/telemetria.

## 5.20. PostgreSQL / WVC — brak bieżącej telemetrii jest obecnie oczekiwany

Baza `ai_bridge`:

- PostgreSQL 18.6,
- rozmiar ~318 MB,
- ok. 104 rekordów `ventilation_analysis_runs`,
- statystyki `ventilation_ingest_batches` i `ventilation_telemetry_raw` wskazują ~0 live rows.

**Kontekst operacyjny:** WVC jest obecnie odłączony, więc brak nowych danych telemetrycznych jest stanem oczekiwanym i nie oznacza sam w sobie awarii ingestu.

ADR-004 nadal zakłada pełną szczegółową centralną historię przez minimum 12 miesięcy po uruchomieniu normalnej pracy systemu. Dlatego przed migracją warto zweryfikować stan historycznych danych, ale nie traktujemy obecnego braku przyrostu jako problemu P1.

**Klasyfikacja:** VERIFY / P2.

Do sprawdzenia read-only przy okazji v1.2:

- dokładne `COUNT(*)`,
- najstarszy/najnowszy timestamp danych historycznych,
- czy wcześniejsze dane zostały zachowane zgodnie z ADR-004.

Brak bieżącego ingestu podczas odłączenia WVC jest prawidłowy.

## 5.21. Hermes drift — skala potwierdzona

Dirty checkout Hermesa zawiera 245 dodatkowych linii w 3 plikach produkcyjnych.

Dodatkowo lokalny Hermes ma jeden commit nieobecny w `origin/main`, a `origin/main` ma jeden commit nieobecny lokalnie.

To oznacza równocześnie:

- branch divergence,
- local source patching,
- ryzyko utraty integracji przy zwykłym pull/reset/upgrade.

**Klasyfikacja:** MIGRATE — PRIORITY P1.

Przed zmianą Hermesa należy zapisać pełny patch/diff poza publicznym repo lub w kontrolowanym prywatnym artefakcie i odtworzyć funkcjonalność jako adapter/integrację bez patch-in-place.

## 5.22. Produkcyjne helpery media — wersjonowanie historyczne w runtime

`/usr/local/libexec/ai-server` zawiera równolegle pliki bazowe i stage26/stage29/stage30, m.in.:

- prompt compiler bazowy + stage30,
- generator bazowy + stage29 + aktywny generator,
- dispatcher bazowy + stage26 + stage30 + aktywny dispatcher,
- global resource queue helper.

To potwierdza, że aktywna produkcja jest złożeniem wielu etapów, a nie jednym release artifact.

**Klasyfikacja:** MIGRATE; po nowym release packaging stare wersje DELETE/ARCHIVE zgodnie z Development Hygiene Policy.

## 5.23. Deployed hashes — AI Gateway zgodny z lokalnym working tree, AI Bridge nie

Dla kluczowych plików Gatewaya hash `/opt/ai-gateway` jest zgodny z lokalnym checkoutem `~/AI-server`.

Natomiast `/opt/ai-bridge` ma inne hash'e `pyproject.toml` i `settings.py` niż lokalny checkout.

Wniosek: AI Gateway da się obecnie lepiej przypisać do stanu źródła niż AI Bridge. AI Bridge jest starszym deploymentem i wymaga jednoznacznego release/build stamp.

**Klasyfikacja:** MIGRATE — PRIORITY P1.

## 5.24. Uprawnienia plików konfiguracyjnych

Pozytywne:

- główne sekrety AI Bridge i Hermes mają restrykcyjne uprawnienia.

Do poprawy:

- `/etc/ai-gateway/ai-gateway.env` ma mode 644. Obecnie plik nie musi zawierać sekretów, ale docelowa polityka config/secrets nie powinna opierać bezpieczeństwa na tym założeniu.

**Klasyfikacja:** HARDEN/MIGRATE.


# 6. Finalna klasyfikacja v1.1

| Obszar | Decyzja | Priorytet |
|---|---|---|
| Host Minisforum | KEEP jako obecny node | P3 |
| /srv/ai-data na osobnym NVMe | KEEP / uporządkować layout | P2 |
| AI Bridge domain logic | KEEP / REFACTOR | P2 |
| PostgreSQL + Alembic | KEEP | P2 |
| AI Gateway scheduler/resource leases | KEEP / EVOLVE | P1 |
| Ollama | KEEP jako provider v1 | P2 |
| Qwen | KEEP jako model v1 | P3 |
| Hermes | KEEP tymczasowo / MIGRATE do AgentProvider | P1 |
| ComfyUI | KEEP tymczasowo / adapter worker | P2 |
| Git working checkout jako element deploymentu | DEPRECATE | P1 |
| patch-in-place Hermes | DEPRECATE | P1 |
| hardcoded user/paths/host | MIGRATE | P1 |
| bezpośredni Ollama dostęp sieciowy | MIGRATE / ograniczyć | P1 |
| ComfyUI 0.0.0.0 exposure | REVIEW / ograniczyć jeśli zbędne | P1 |
| AI Bridge LAN exposure | REVIEW + auth/firewall | P1 |
| stage worktrees | DELETE po kontroli | P2 |
| stare /opt pre-stage backups | ARCHIVE/DELETE po nowym backupie | P2 |
| stare Hermes stage backups | ARCHIVE/DELETE po nowym backupie | P2 |
| historyczne job dirs | RETENTION/CLEANUP | P2 |
| duplicate/old Ollama models | REVIEW/CLEANUP | P3 |
| Docker daemon bez workloads | REVIEW | P3 |
| README current-state drift | UPDATE | P2 |
| duplicate ADR numbering | FIX | P2 |
| branch-pinned installers | DEPRECATE/MIGRATE | P1 |
| stage-oriented CI | REFACTOR | P2 |
| security architecture | CREATE | P1 |
| backup/restore/DR | CREATE | P1 |
| central telemetry archive zgodnie z ADR-004 | VERIFY history; WVC obecnie odłączony | P2 |
| firewall / exposure policy | VERIFY / CREATE | P1 |
| Ollama preload unit/helper | MIGRATE do desired-state/model policy | P2 |
| production helper packaging | MIGRATE do release artifact | P1 |
| desired-state deployment | CREATE | P1 |
| model/provider registry | CREATE | P1 |
| knowledge-service | CREATE później | P2 |
| platform observability | CREATE/EXTEND | P2 |
| AI Control Center | CREATE później | P3 |

---

# 7. Docelowa strategia przebudowy

Audyt nie wskazuje na potrzebę „formatowania serwera i zaczynania od zera”.

Rekomendowany kierunek:

```text
STABILIZUJ SOURCE OF TRUTH
        ↓
ZAPROJEKTUJ KONTRAKTY
        ↓
WYDZIEL PLATFORM CORE
        ↓
OWIŃ OBECNE BACKENDY ADAPTERAMI
        ↓
WPROWADŹ DESIRED-STATE DEPLOYMENT
        ↓
PRZENIEŚ WVC / HERMES / MEDIA
        ↓
DODAJ KNOWLEDGE SERVICE
        ↓
DODAJ KOLEJNE DOMENY
        ↓
GUI
```

Nie zmieniamy jednocześnie modelu, agenta, bazy, schedulera i deploymentu. Migracja ma być etapowa i odwracalna.

---

# 8. Pozostałe punkty weryfikacyjne po audycie

Supplemental audit v1.1 zebrał wymagane metadane. Pozostały dwa punkty, które nie blokują zamknięcia audytu architektonicznego, ale muszą zostać rozwiązane przed migracją produkcji:

1. firewall/UFW/nftables — wymaga odczytu z sudo,
2. dokładna weryfikacja centralnej telemetrii PostgreSQL — `COUNT(*)` i zakres timestampów.

Pełny diff Hermesa również należy przechwycić przed jego aktualizacją lub resetem, ale nie musi być publikowany w publicznym repo.

---

# 9. Zasada cleanupu po audycie

Po ustaleniu aktywnych zależności wykonamy osobny cleanup plan.

Kolejność:

1. snapshot / verified backup,
2. capture aktywnych diffów,
3. klasyfikacja artefaktu,
4. usunięcie worktree/test dirs,
5. usunięcie obsolete stage backups,
6. polityka TTL dla jobs/output,
7. kontrola `git worktree list`, `git status`, systemd i storage.

Cleanup będzie częścią Definition of Done migracji.

---

# 10. Wniosek audytu v1

Obecny Serwer AI jest funkcjonalny i nie ma failed units, ale jego produkcyjny stan powstał etapowo przez wiele bezpiecznych eksperymentów. Główne ryzyka nie dotyczą dziś działania modeli, lecz **reprodukowalności i utrzymywalności platformy**:

1. runtime nie jest jednoznacznie odwzorowany przez GitHub main,
2. Hermes jest patchowany w miejscu i ma dirty checkout,
3. część backendów jest bezpośrednio dostępna w sieci i może omijać centralny Resource Manager,
4. istnieje dużo historycznych worktree/backup/stage artifacts,
5. deployment jest imperatywny i nie posiada jednego desired-state manifestu,
6. konfiguracja/state/cache są rozproszone,
7. brakuje platformowych kontraktów providerów, DR, security i observability.

To są dokładnie problemy, które nowa architektura ma rozwiązać.

**Decyzja:** Audit v1.1 jest zamknięty na poziomie architektury/runtime inventory. Można przejść do finalizacji dokumentu pre-audit i projektowania Target Architecture. Nie rozpoczynać jeszcze szerokiej przebudowy produkcji przed rozwiązaniem punktów P1 i przygotowaniem planu migracji.

