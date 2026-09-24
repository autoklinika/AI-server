# AI Platform — Stage L0 — EcuRepairService read-only audit

**Data:** 2026-09-24
**Status:** READ-ONLY AUDIT COMPLETE
**Zakres:** ERS source/repo, Knowledge Service, PostgreSQL, canonical objects, Stage K DR
**Zmiany produkcyjne:** brak

## 1. Baseline

- AI-server `main`: `a77bdd2f1319c90c7d09cb0fe7b922a328c5c6ec`.
- Aktywny runtime: `/opt/ai-platform/releases/stage-j-3b456a56343a`.
- Stage J pozostaje aktywnym runtime i nie został zmieniony.
- Stage K pozostaje aktywną warstwą backup/DR i nie został zmieniony.
- Audyt wykonano na żywym serwerze wyłącznie read-only.

## 2. EcuRepairService — repo/source cache

Lokalne źródło:
`/srv/ai-data/knowledge/source-cache/EcuRepairService`

Origin:
`https://github.com/autoklinika/EcuRepairService.git`

HEAD:
`b12de047e5a5238232177423cfaf0d2d05a3afe5`

Repo zawiera 65 plików poza `.git`: 32 Markdown, 16 PDF, 13 JPEG, 3 TXT i 1 JSONL.

## 3. Stan working tree ERS

Working tree nie jest clean. Jedyną wykrytą zmianą jest nieśledzony plik:

`cases/CASE-0002-SCANIA-EMS-S6-DC1210-ECU-CLONE/first_block_analysis.md`

Plik jest cennym evidence technicznym i nie został zmodyfikowany ani usunięty.
Stage K już obejmuje go snapshotem ERS, mimo że nie należy jeszcze do Git.

Skutek operacyjny: obecne importery J3/J4 fail-closed odrzucą ten checkout,
ponieważ wymagają clean/read-only source cache.

## 4. Cases

### CASE-0001

Golden case jest kompletnym, rozwiązanym przypadkiem:
- GAYK HRE 3000 USP / Hatz 3H50TICD / Bosch EDC17C81;
- DTC SPN 107 FMI 3, OC 34;
- realny derate około 1300 rpm zamiast około 2400 rpm;
- root cause: uszkodzony przewód przy złączu Bosch 0 281 007 439;
- wynik naprawy potwierdzony warsztatowo;
- 13 oryginalnych zdjęć jest fizycznie obecnych w repo.

### CASE-0002

Scania EMS S6 dokumentuje prawdziwy workflow replacement/cloning:
- ORI DC1210 i donor DC1213;
- wspólny hardware `1726100`;
- oba MCU: `MPC555LF8MZP40`, revision M;
- Flash: 458752 B / 0x70000;
- EEPROM 25C256: 32768 B / 0x8000;
- donor po operacji uruchamia się i komunikuje na stole;
- read-back: 0x0000–0x7FFF pozostaje donor, 0x8000–0x6FFFF jest zgodne z ORI.

Repo zawiera checksumy, rozmiary i analizę, ale nie zawiera oryginalnych binarek.
Repo nie zawiera też sześciu oryginalnych zdjęć CASE-0002; ma tylko indeks i SHA-256.

Przeszukanie `/srv/ai-data` i `/home/harrypotter` nie znalazło tych plików case.
Dlatego L1 nie może udawać pełnej migracji CASE-0002. Musi obsłużyć
`missing_original` z oczekiwanym SHA-256/rozmiarem, a późniejszy import ma
zaakceptować plik tylko po zgodności hasha.

## 5. Knowledge Service — stan produkcyjny

PostgreSQL zawiera:
- 2 `knowledge_sources`;
- 32 `knowledge_documents`;
- 32 `knowledge_document_versions`;
- 566 `knowledge_chunks`;
- 32 `knowledge_index_jobs`, wszystkie `completed`.

ERS jest obecnie reprezentowany przez dwa logiczne źródła o tym samym URI repo:
- `source_type=github` dla Markdown;
- `source_type=documentation` dla PDF.

Wynika to z deterministycznego ID Knowledge, które uwzględnia `source_type`.
Nie jest to awaria J, ale L3 nie powinien powielać tego wzorca dla runtime case publications.

Wszystkie obecne 32 dokumenty mają source revision:
`0ee98b94705b691d7347c8a6a5676ac63159e359` z 2026-09-16.

Obecny ERS HEAD jest z 2026-09-24. Produkcyjny Knowledge nie obejmuje więc m.in.:
- CASE-0002;
- Scania EMS S6;
- NXP MPC555 notes;
- trzech nowych PDF NXP;
- semiconductor corpus metadata;
- bieżących zmian dokumentacyjnych.

To jest kontrolowany lag publikacji, a nie powód do bezpośredniego zapisu do Qdranta.

## 6. PostgreSQL

W produkcyjnej bazie `ai_bridge` nie ma obecnie tabel transakcyjnych ERS.
Są wyłącznie tabele WVC i Knowledge.

Wniosek: L1 wymaga osobnej migracji Alembic z tabelami `ers_*`.
Nie wolno używać `knowledge_*` jako tabel case store.

## 7. Canonical object storage

Knowledge przechowuje immutable content-addressed objects pod kontrolą SHA-256.
Zapis jest atomowy, a integralność obiektu jest weryfikowana względem hasha.

Ten mechanizm nadaje się do ponownego użycia przez ERS przez wspólny platformowy kontrakt ObjectStore.
Nie projektujemy drugiego, niezależnego magazynu plików tylko dla ERS.

## 8. Stage K — ERS backup

K3 backupuje bieżące drzewo source-cache ERS, z wyłączeniem Git metadata i cache.
Snapshot zawiera wszystkie 65 plików, w tym nieśledzony `first_block_analysis.md`.

Ostatnio sprawdzony restore validation:
- `ers_files=65`;
- `production_modified=false`;
- status `PASS`.

Backup nie może zabezpieczyć pliku, którego nie ma w source-cache.
Dlatego brakujące binaria i zdjęcia CASE-0002 pozostają realną luką danych.

## 9. Automotive Semiconductor Corpus v0

Repo zawiera manifest/checksumy, ale nie 22 PDF-y corpus v0.
Fizyczna paczka robocza nadal istnieje wyłącznie pod:

`/tmp/ers_automotive_semiconductor_corpus_v0_20260924`

Zawiera 22 PDF-y OEM, extracted text, page extracts i render checks.
Nie jest ingested do Knowledge i nie jest objęta K3 ERS backup.

Klasyfikacja L0: `PROMOTE_REQUIRED`.
Nie wolno uznać `/tmp` za trwałe source of truth ani usuwać paczki przed
przeniesieniem do kontrolowanego durable source/canonical flow.

## 10. Kluczowe luki przed L1

1. Brak transactional Case Store.
2. Brak trwałego magazynu raw CASE-0002 artifacts na serwerze.
3. Knowledge jest starszy od aktualnego ERS repo.
4. Dirty ERS source-cache blokuje obecny importer fail-closed.
5. Brak formalnego ERS publication contract do Knowledge.
6. Stage K K3 chroni repo tree, ale nie przyszłe runtime artifacts ERS.
7. Brak strukturalnego diagnosis schema i evidence graph.

## 11. Klasyfikacja istniejącego ERS

| Obszar | Decyzja L0 | Docelowa rola |
|---|---|---|
| `sources/` | KEEP | reference/OEM source content |
| `components/` | KEEP | curated reference knowledge |
| `ecus/` | KEEP | curated ECU reference knowledge |
| `engines/` | KEEP | curated platform/engine reference knowledge |
| `machines/` | KEEP | curated machine reference knowledge |
| `tools/` | KEEP | tool capabilities/limitations |
| `docs/` | KEEP | standardy, research i dokumentacja |
| `cases/` | MIGRATE + KEEP history | seed do Case Store; repo nie będzie runtime DB |
| CASE-0001 JPEG | MIGRATE | raw immutable case artifacts |
| Hatz/NXP PDF | KEEP + canonical reference | OEM docs/Knowledge source |
| CASE-0002 raw binaries | MISSING ORIGINAL | import dopiero po hash verification |
| CASE-0002 raw photos | MISSING ORIGINAL | import dopiero po hash verification |
| semiconductor corpus /tmp | PROMOTE_REQUIRED | durable source/canonical flow |
| Knowledge chunks/Qdrant | REGENERABLE | retrieval projection |

Nie wykonano żadnego przeniesienia ani usunięcia podczas L0.

## 12. Wniosek audytu

Obecny ERS jest dobrym, jakościowym corpus/reference repo, ale nie posiada mechanizmów
wymaganych dla aktywnej domeny transakcyjnej.

Najważniejsza granica Stage L:
- Case Store odpowiada za prawdę operacyjną;
- Object Store odpowiada za immutable bytes;
- Knowledge odpowiada za publikowane reusable knowledge/retrieval;
- Qdrant pozostaje odbudowywalnym indeksem;
- Platform API/Resource Manager/provider abstraction odpowiadają za AI execution.

Audyt nie wykazał potrzeby zmiany aktywnego Stage J.
L0 może zostać zamknięte dokumentacyjnie bez deployu produkcyjnego.

Dalsza implementacja jest zdefiniowana w:
- `docs/architecture/adr/ADR-007_STAGE_L0_ERS_DOMAIN_SOURCE_OF_TRUTH_2026-09-24_PL.md`;
- `docs/architecture/AI_PLATFORM_ERS_DOMAIN_CONTRACT_V1_PL.md`.
