# AI Platform — Stage K NAS Recovery Acceptance

Data: 2026-09-24
Status: K1 PASS / K2 Knowledge+WVC PASS / K4 Knowledge PASS

## Zakres

Wykonano pierwszy rzeczywisty backup Stage K poza AI Serverem na GlobalNAS oraz pełną izolowaną walidację odtworzenia Knowledge Service z tej kopii.

Aktywny produkcyjny Stage J nie został przełączony ani zmodyfikowany.

## K1 — GlobalNAS transport

Docelowy udział: `//globalnas.local/AI_Platform`

Mount AI Server: `/mnt/AI_Platform`

Zweryfikowane parametry:
- filesystem: CIFS;
- SMB: 3.1.1;
- konto: dedykowane `ai_backup`;
- guest access: denied;
- trwały mount przez `/etc/fstab`;
- credentials poza repo w `/etc/ai-platform/stage-k/globalnas.credentials`;
- marker targetu: `.ai-platform-backup-target.json`;
- około 7.1 TB wolnego miejsca podczas acceptance.

Skrypt instalacyjny i rollback: `deploy/stage-k/configure_globalnas.sh`.

## K2 — pierwszy rzeczywisty recovery set na NAS

Backup ID: `20260924T152707Z`

Knowledge manifest: `/mnt/AI_Platform/Knowledge/manifests/manual/20260924T152707Z`

WVC manifest: `/mnt/AI_Platform/WVC/manifests/manual/20260924T152707Z`

Wspólny PostgreSQL: `/mnt/AI_Platform/_Shared/PostgreSQL/ai_bridge/manual/20260924T152707Z/ai_bridge.dump`

Offline verification Knowledge:
- PostgreSQL dump: 36 523 933 B;
- canonical objects: 32;
- canonical bytes: 26 388 772;
- knowledge versions: 32;
- knowledge chunks: 566;
- status: PASS.

Offline verification WVC:
- ventilation_ingest_batches: 42 447;
- ventilation_telemetry_raw: 96 563;
- ventilation_analysis_runs: 2 730;
- status: PASS.

## K4 — realny restore z GlobalNAS

Evidence: `/srv/ai-data/backups/stage-k/restore-validation/20260924T152707Z-20260924T152716Z-422690`

Test wykonał:
1. offline verification backupu z GlobalNAS;
2. start pustego, izolowanego PostgreSQL;
3. restore całego `ai_bridge`;
4. odtworzenie 32 canonical objects wskazanych przez manifest;
5. kontrolę DB ↔ canonical object store;
6. start świeżego, pustego Qdranta;
7. pełny reindex 32 dokumentów;
8. odbudowę dokładnie 566 punktów;
9. Knowledge Search;
10. RAG;
11. claim-level citations;
12. source opening i SHA-256;
13. kontrolę produkcyjnego Qdranta przed i po teście.

Wynik:
- duration: 110.318 s;
- Qdrant started empty: true;
- source Qdrant snapshot used: false;
- reindex: 32 completed / 0 failed;
- Qdrant points: 566;
- Search results: 8;
- RAG claims: 1;
- RAG citations: 1;
- production Qdrant: 566 -> 566;
- status: PASS.

## Wniosek

Dla Knowledge Service został praktycznie udowodniony łańcuch DR:

`GlobalNAS -> PostgreSQL + canonical objects -> empty PostgreSQL -> empty Qdrant -> reindex -> Search/RAG/source opening`

Qdrant pozostaje odbudowywalną projekcją i nie jest wymaganym elementem backupu.

K1 jest zaakceptowany. K2 jest zaakceptowany dla Knowledge/WVC. K4 jest zaakceptowany dla Knowledge na rzeczywistym backupie NAS.

Stage K jako całość pozostaje otwarty do zakończenia K3 i K5: ERS, Hermes durable state, recovery config i szyfrowane secrets, scheduling, retencja, monitoring, alarmowanie oraz finalny runbook.

`StarletteDeprecationWarning` podczas TestClient nie wpływało na wynik walidacji i pozostaje technical debt niezwiązanym z poprawnością DR.
