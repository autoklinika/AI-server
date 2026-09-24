# AI Platform — Stage K Backup / Disaster Recovery Architecture

Data: 2026-09-24

## 1. Cel i granica bezpieczeństwa

Stage K nie jest projektem „kopii plików”. Kryterium akceptacji stanowi odtworzenie
Knowledge Service z kopii znajdującej się poza AI Serverem, bez użycia starego Qdranta
i bez modyfikacji produkcji podczas testu.

Dla Knowledge Service źródłem prawdy pozostają wyłącznie:
`PostgreSQL + canonical immutable object store`.
Qdrant jest projekcją danych i musi być odbudowywalny.

## 2. Stan faktyczny po K0

AI Server używa dwóch lokalnych SSD około 4 TB. `/srv/ai-data` jest osobnym ext4
na `/dev/nvme0n1p1`; podczas audytu miał około 3.5 TB wolnego miejsca.
NAS nie jest zamontowany przez `fstab`, systemd mount ani automount.

Aktywny Stage J: `/opt/ai-platform/releases/stage-j-3b456a56343a`.
Runtime source SHA: `3b456a56343a533d2d920e1e63dfe304530c865b`.
Dokumentacyjny main: `675872d16df413f03546bfca68b2d6e483056e14`.
PostgreSQL 18.6 używa bazy `ai_bridge`, schema `0003_knowledge_canonical`.
Rozmiar bazy podczas audytu wynosił około 474 MB.

Snapshot K2 zawierał dokładnie:
- `knowledge_sources`: 2;
- `knowledge_documents`: 32;
- `knowledge_document_versions`: 32;
- `knowledge_chunks`: 566;
- `knowledge_index_jobs`: 32;
- `ventilation_ingest_batches`: 42 447;
- `ventilation_telemetry_raw`: 96 563;
- `ventilation_analysis_runs`: 2 730.

Canonical store `/srv/ai-data/knowledge/canonical/objects` zawierał 32 obiekty,
26 388 772 B, content-addressed SHA-256.

Qdrant działa w Dockerze jako `ai-qdrant`, storage `/srv/ai-data/qdrant/storage`,
około 11 MB, collection `knowledge_dense_bge_m3_1024_v1`. Nie jest source of truth.

EcuRepairService source cache był czysty: HEAD
`b12de047e5a5238232177423cfaf0d2d05a3afe5`, origin `autoklinika/EcuRepairService`.

## 3. NAS i transport

Docelowy NAS to `GlobalNAS` / `globalnas.local`, który rozwiązuje się do
`192.168.1.79` i jest osiągalny w LAN. Otwarte są SMB 445/139.
K1 używa SMB3 oraz dedykowanego konta backupowego. AI Server montuje wskazany
udział GlobalNAS w osobnym punkcie. Nazwa istniejącego udziału SMB nie jest
zgadywana; anonimowe logowanie SMB działa, ale enumeracja udziałów kończy się
`STATUS_ACCESS_DENIED`.

Na zamontowanym udziale tworzony jest jeden nadrzędny katalog:
`AI_Platform/`.

Warunki fail-closed przed zapisem:
- mount istnieje i `findmnt` raportuje zatwierdzony network FS;
- marker `.ai-platform-backup-target.json` ma właściwy purpose/schema;
- target przechodzi write/read probe;
- filesystem nie jest read-only i ma wystarczającą ilość miejsca;
- produkcyjny job nie może spaść awaryjnie na lokalny filesystem.

Awaria NAS oznacza FAIL joba, a nie zapis lokalny udający DR.

## 4. Układ backupu według źródła

Backup na GlobalNAS jest rozdzielony według domen/źródeł. Root:
`AI_Platform/`.

Docelowa struktura v1:

```text
AI_Platform/
  _Shared/
    PostgreSQL/
      ai_bridge/
        daily/
        weekly/
        manual/
  Knowledge/
    canonical-objects/sha256/
    manifests/
    restore-evidence/
  WVC/
    manifests/
    restore-evidence/
  ERS/
    snapshots/
    manifests/
  Hermes/
    sqlite/
    state/
    memories/
    skills/
    pending/
    manifests/
  Platform/
    config/
    secrets/
    manifests/
  CRT/
    manifests/
```

Każda domena ma własny manifest i własną retencję. Wyjątkiem jest PostgreSQL
`ai_bridge`: jedna fizyczna, spójna kopia całej bazy znajduje się w
`_Shared/PostgreSQL/ai_bridge`, ponieważ ta sama baza zawiera jednocześnie dane
Knowledge i WVC. Nie dublujemy jej w obu domenach. Manifesty Knowledge i WVC
wskazują identyfikator wspólnego snapshotu DB.

Canonical objects są immutable i content-addressed. Na NAS utrzymujemy jeden
przyrostowy pool `Knowledge/canonical-objects/sha256/`; kolejne backupy nie
kopiują ponownie już istniejących obiektów. Manifest recovery setu wskazuje
dokładny zestaw SHA-256 wymagany do restore.

Marker `COMPLETE` oraz checksumy publikowane są dopiero po pełnej weryfikacji.
`.incomplete` nigdy nie jest kwalifikowany jako backup.
## 5. PostgreSQL i spójność

Backup obejmuje całą bazę `ai_bridge`, nie tylko Knowledge, dzięki czemu zachowuje
również centralną historię WVC.

`pg_dump --format=custom` działa na eksportowanym snapshotcie transakcji
`REPEATABLE READ READ ONLY`. Manifest zawiera nazwę bazy, wersję PostgreSQL,
Alembic schema version, exact table counts oraz checksum i rozmiar dumpu.
Dump musi przejść `pg_restore -l` przed publikacją setu.

## 6. Canonical object store

Manifest DB jest granicą spójności. Backup kopiuje obiekty wskazane przez
`knowledge_document_versions` z tego samego snapshotu.

Każdy obiekt musi istnieć, mieć poprawną ścieżkę content-addressed, rozmiar zgodny
z DB i SHA-256 zgodny z nazwą. Jest hashowany przed i po kopiowaniu.
Brak jednego obiektu dyskwalifikuje cały recovery set.

## 7. Qdrant

Snapshot Qdrant nie jest potrzebny do K2/K4. Może zostać dodany jako opcjonalny
fast-recovery cache, ale nie może wpływać na Definition of Done.
K4 zaczyna z pustym Qdrantem i wykonuje pełny reindex z odtworzonego source of truth.
## 8. Dane domenowe poza Knowledge

WVC: centralne dane trwałe są w `ai_bridge`, więc są pokryte przez K2.

EcuRepairService: system backupu Stage K nie używa GitHub ani żadnego zewnętrznego
repozytorium jako elementu DR. Dane ERS są kopiowane z lokalnego źródła na AI Serverze
do `AI_Platform/ERS/` jako niezależny snapshot z manifestem i checksumami.
Zakres obejmuje dane przypadków, dokumentację, źródła i inne nieodtwarzalne artefakty;
metadane VCS nie są wymagane do poprawnego restore danych ERS.

Hermes: do ochrony kwalifikują się trwałe SQLite/state stores, konfiguracja bez
sekretów, własne skills oraz pending state. Aktywne SQLite backupujemy przez SQLite
backup API, nie surowym kopiowaniem pliku z aktywnym WAL. `.env` należy do K3.

CRT: przed wejściem przyszłej domeny na produkcję musi ona zadeklarować source of
truth, backup class, RPO/RTO i restore validation.

Świadomie nie backupujemy jako danych krytycznych modeli Ollama możliwych do
ponownego pobrania, cache HuggingFace/Hermes, `.venv`, node/runtime binaries,
build artifacts ani Qdranta jako wymaganego źródła.

## 9. Secrets / K3

Rozpoznane lokalizacje obejmują m.in. `/etc/ai-bridge/ai-bridge.env`,
`/etc/ai-gateway/ai-gateway.env` i `/srv/ai-data/hermes/.env`.
Ich wartości nie są logowane ani zapisywane w manifestach.
Na serwerze są `gpg` i `openssl`; `age` i `sops` nie są zainstalowane.
K3 użyje osobnego zaszyfrowanego recovery bundle. Preferowany jest model
asymetryczny: serwer ma tylko materiał potrzebny do szyfrowania, a prywatny klucz
recovery jest przechowywany offline/offsite, poza AI Serverem i NAS.

## 10. Retencja i częstotliwość

Baseline:
- PostgreSQL `ai_bridge`: daily, 30 daily + 12 weekly;
- Knowledge canonical objects: przyrostowo do jednego immutable pool; bez
  wielokrotnego kopiowania identycznych SHA-256;
- ERS: daily po zmianie danych lub minimum daily snapshot manifest; retencja
  ustalana niezależnie od Knowledge/WVC;
- Hermes durable state: daily;
- manual: przed/po ryzykownych migracjach lub dużym ingestion; bez automatycznego
  kasowania evidence na wczesnym etapie K.

Każdy backup natychmiast przechodzi offline integrity verification.
Pełny izolowany restore validation powinien działać co najmniej raz w tygodniu.

## 11. RPO / RTO

Docelowy RPO dla `ai_bridge` + canonical objects: <= 24 h przy daily backup.
Przed ryzykowną zmianą wymagany jest manual recovery set.

Zmierzony 2026-09-24 lokalny K4 dla obecnego corpus: 108.32 s od rozpoczęcia
izolowanego restore do PASS Search/RAG/source opening. To nie jest jeszcze pomiar
odtworzenia całego utraconego hosta.

Operacyjny target:
- Knowledge data plane: RTO <= 1 h po przygotowaniu bazowego hosta/runtime;
- pełny AI Server DR: RTO <= 4 h do czasu replacement-host drill.
## 12. Definition of Done

Stage K kończy się dopiero gdy recovery set pobrany z NAS:
1. przejdzie checksum/integrity;
2. odtworzy PostgreSQL do pustego środowiska;
3. odtworzy canonical objects;
4. przejdzie DB ↔ object store verification;
5. odbuduje pusty Qdrant przez reindex;
6. przejdzie Knowledge Search;
7. przejdzie RAG;
8. zwróci claim-level citations;
9. otworzy source content z poprawnym SHA-256;
10. wykaże brak użycia starego Qdranta;
11. pozostawi komplet evidence i monitoring status.

Dopóki test nie używa kopii z NAS, Stage K nie jest PRODUCTION COMPLETE.

## 13. Acceptance status — 2026-09-24

K1 przeszedł produkcyjny gate na `GlobalNAS` / `//globalnas.local/AI_Platform`. Pierwszy rzeczywisty backup NAS `20260924T152707Z` przeszedł integralność dla Knowledge i WVC. Pełny K4 z tego backupu zakończył się PASS po 110.318 s, z pustym PostgreSQL i pustym Qdrantem, pełnym reindexem do 566 punktów, Search/RAG/citations/source opening oraz bez użycia snapshotu starego Qdranta.

Szczegółowe evidence: `docs/reports/AI_PLATFORM_STAGE_K_NAS_RECOVERY_ACCEPTANCE_2026-09-24_PL.md`.

K1 = PASS. K2 Knowledge/WVC = PASS. K4 Knowledge = PASS. Stage K pozostaje otwarty dla K3 i K5.

## 14. K3 acceptance — 2026-09-24

K3 durable data/config przeszedł rzeczywisty backup na GlobalNAS i izolowany restore validation. Finalny backup ID `20260924T165315Z` obejmuje osobne domeny ERS, Hermes i Platform config. Wszystkie trzy manifesty wskazują commit `12b27ba1e8f77e0acefeccbe82ea8cd582ac7c87`.

Hermes aktywne SQLite są backupowane przez SQLite Backup API do lokalnego frozen DB, przechodzą `quick_check` i SHA-256, a dopiero potem trafiają na CIFS.

Secrets są odseparowane od jawnych snapshotów. Bundle `20260924T164644Z` używa `age` z zaakceptowanym recipientem SSH Ed25519. Plaintext nie trafia na NAS ani do pliku pośredniego. Prywatny klucz pozostaje poza AI Serverem i GlobalNAS.

K3 durable data/config = PASS. K3 encrypted secrets backup = PASS. External-key decrypt drill jest częścią K5 replacement-host validation.

Szczegóły: `docs/reports/AI_PLATFORM_STAGE_K_K3_RECOVERY_ACCEPTANCE_2026-09-24_PL.md`.

## 15. Production completion — 2026-09-24

Finalny K5 runtime gate wykonał daily i weekly service przez user-systemd z `main` SHA `146804a58bde03b2b8092e2794c117215d15e6c5`. Oba zakończyły się `Result=success`. Weekly odbudował Knowledge z GlobalNAS do pustego PostgreSQL/Qdrant i przeszedł Search/RAG/citations/source opening; K3 restore przeszedł ERS/Hermes/Platform config wraz z 5/5 SQLite Hermes.

Produkcja ma enabled daily, weekly i hourly monitor timers; `Linger=yes`. Finalny monitor ma `issues=[]` i `status=PASS`.

Szczegóły: `docs/reports/AI_PLATFORM_STAGE_K_PRODUCTION_ACCEPTANCE_2026-09-24_PL.md`.

**Stage K = PRODUCTION COMPLETE dla backup/DR data plane.** Recovery-key lifecycle dla secrets pozostaje deferred/non-blocking hardeningiem.
