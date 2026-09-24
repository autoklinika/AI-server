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

`nas-klinika.local` rozwiązuje się do `192.168.1.15` i jest osiągalny w LAN.
Otwarte są SMB 445/139. NFS 2049, rpcbind 111 i SSH 22 nie są dostępne.
Tailscale NAS ma wygasły node key; nie jest potrzebny do lokalnego transportu DR.
Docelowo K1 używa dedykowanego udziału SMB3 oraz dedykowanego konta backupowego.
AI Server montuje udział w osobnym punkcie, np. `/mnt/ai-platform-backup`.
Dokładna nazwa udziału nie jest zgadywana — musi wynikać z realnej konfiguracji NAS.

Warunki fail-closed przed zapisem:
- mount istnieje i `findmnt` raportuje zatwierdzony network FS;
- marker `.ai-platform-backup-target.json` ma właściwy purpose/schema;
- target przechodzi write/read probe;
- filesystem nie jest read-only i ma wystarczającą ilość miejsca;
- produkcyjny job nie może spaść awaryjnie na lokalny filesystem.

Awaria NAS oznacza FAIL joba, a nie zapis lokalny udający DR.

## 4. Format recovery set

Docelowy układ:
`AI-Server/sets/daily/<backup_id>/`
`AI-Server/sets/weekly/<backup_id>/`
`AI-Server/sets/manual/<backup_id>/`

Każdy set zawiera dump PostgreSQL, canonical objects, manifest, checksum manifestu
i marker `COMPLETE`. `.incomplete` nigdy nie jest kwalifikowany jako backup.

Pierwsza wersja jest samowystarczalna. Powiela immutable objects między setami,
ale maksymalnie upraszcza restore i dowód kompletności. Deduplikowany object pool
może zostać dodany później bez zmiany semantyki manifestu.
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

EcuRepairService: Git jest podstawowym kanałem odtworzenia source repo. Dla
niezależności od GitHub K5 powinien dodatkowo utrzymywać na NAS okresowy Git bundle
lub mirror. Nie backupujemy source-cache jako przypadkowego working tree.

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
- daily: 1 raz na dobę;
- weekly: 1 pełny recovery set tygodniowo;
- retention: 30 daily + 12 weekly;
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
