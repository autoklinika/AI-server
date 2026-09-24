# AI Platform — EcuRepairService Domain Contract v1

**Status:** Stage L0 architecture contract
**Data:** 2026-09-24
**Domain ID:** `ecu-repair`
**Public API prefix:** `/api/v1/ecu-repair`

## 1. Cel

EcuRepairService ma być aktywną domeną AI Platform obsługującą rzeczywiste przypadki napraw ECU.
Kontrakt obejmuje dane warsztatowe, pliki, pomiary, binaria, evidence, diagnozę AI,
wynik naprawy i kontrolowaną publikację zatwierdzonej wiedzy.

Nie jest to kontrakt GUI ani kolejny wrapper RAG.

## 2. Granice

ERS:
- jest właścicielem przypadku naprawy i jego lifecycle;
- korzysta ze wspólnego PostgreSQL przez własne tabele `ers_*`;
- przechowuje bajty jako immutable SHA-256 objects;
- korzysta z Platform API/provider abstraction do AI;
- korzysta z istniejącego Resource Managera;
- korzysta wyłącznie z Knowledge Service API/contract do retrieval i publikacji;
- nigdy nie komunikuje się bezpośrednio z Qdrantem ani Ollamą.

CRT pozostaje przyszłym właścicielem aktywnej logiki CAN/UDS/J1939.
ERS może przechowywać wyniki i dowody pochodzące z CRT, ale nie duplikuje jego odpowiedzialności.

## 3. Source of truth

Trwały stan domeny:

`PostgreSQL ers_* + immutable Object Store`

Projekcje i źródła pomocnicze:

- Knowledge Service — wyszukiwanie i reusable knowledge po publikacji;
- Qdrant — wyłącznie odbudowywalna projekcja Knowledge;
- repo `autoklinika/EcuRepairService` — reference/source content i migration seed;
- GitHub — kod/dokumentacja, nigdy runtime database ani backup;
- cache/scratch — dane nietrwałe.

## 4. Identyfikacja i wersjonowanie

Techniczne PK nowych obiektów: PostgreSQL `UUID`.
Case ma dodatkowo `case_code` unikalny i niezmienny.

Format nowego numeru operatora:
`CASE-000001`, `CASE-000002`, ...

Legacy identifiers pozostają aliasami, bez renumeracji istniejących przypadków.

Każdy write do bieżącego case używa `row_version` do optimistic concurrency.
Dane evidence nie są nadpisywane; korekta tworzy nowy rekord i relację `supersedes`.

## 5. Case lifecycle

### 5.1. Status

Dozwolone statusy:

`draft | open | resolved | closed | cancelled`

Przejścia:
- `draft -> open`;
- `draft -> cancelled`;
- `open -> resolved`;
- `open -> cancelled`;
- `resolved -> open` przez korektę/reopen;
- `resolved -> closed`;
- `closed -> open` wyłącznie przez jawne `reopened`.

Brak hard-delete dla case, który opuścił `draft`.

### 5.2. Work state

Opcjonalne `work_state`:
`intake | diagnosing | awaiting_measurement | awaiting_parts | repairing | verifying | none`.

Work state nie zastępuje lifecycle i może się zmieniać bez fałszowania historii case.

### 5.3. Warunki zamknięcia

`resolved` wymaga wyniku naprawy/weryfikacji albo jawnego wyniku `unresolved`.
`closed` wymaga human approval. AI jest zawsze advisory-only.

## 6. Model podmiotu naprawy

Nie każdy przypadek dotyczy drogowego pojazdu. Dlatego nadrzędnym bytem jest `Asset`.

`asset_kind`:
`vehicle | machine | bench | other`

Vehicle jest specjalizacją Asset i może posiadać VIN/rejestrację.
Maszyna przemysłowa może posiadać numer seryjny bez VIN.
Bench oznacza przypadek ECU analizowany bez kompletnego pojazdu/maszyny.

Tabela `ers_assets` przechowuje trwałą tożsamość obiektu.
Tabela `ers_asset_revisions` przechowuje immutable obserwacje metadanych:
producent, model, VIN/SN, data produkcji, engine identity i metadata JSONB.

`ers_case_assets` wiąże case z assetem i rolą.

## 7. ECU i identity

`ers_ecus` reprezentuje fizyczny sterownik.
`ers_case_ecus` nadaje rolę: `original | donor | replacement | target | reference`.

Identity nie jest jednym nadpisywanym rekordem.
`ers_ecu_identity_observations` zapisuje w czasie m.in.:
- manufacturer/family/model;
- hardware number/revision;
- assembly part number;
- ECU serial;
- MCU/ASIC markings;
- communication metadata.

Software/calibration identity jest osobną obserwacją w `ers_ecu_software_observations`.
Może zawierać: software number, calibration number, boot ID, coding/dataset ID i czas obserwacji.

To rozdzielenie jest wymagane, ponieważ programowanie może zmienić software/calibration
bez zmiany fizycznego ECU.

## 8. Symptom, fault i DTC

`ers_symptoms` przechowuje obserwowany objaw oraz operating context.
Symptom nie jest root cause.

`ers_dtcs` przechowuje surowy kod i jego kontekst. Model wspiera co najmniej:
- OBD/UDS DTC;
- J1939 SPN/FMI/OC;
- status active/history/pending, jeżeli został rzeczywiście zaobserwowany;
- freeze-frame lub odwołanie do source evidence.

DTC jest obserwacją zachowania sterownika, nie automatyczną diagnozą fizycznej przyczyny.

## 9. Measurements

`ers_measurements` jest append-only i przechowuje typ, kanał, wartość, jednostkę,
czas pomiaru, operating context, metodę, narzędzie i provenance.

Wartość może być numeric, text albo JSON dla złożonych wyników.
Duże serie czasowe, oscyloskopy i eksporty są artefaktami; measurement wskazuje
konkretny zakres lub timestamp w takim artefakcie.

## 10. PostgreSQL schema v1

Planowana pierwsza migracja Stage L1 tworzy tabele z prefiksem `ers_`.

### 10.1. Core

`ers_cases`
- `id UUID PK`;
- `case_code VARCHAR UNIQUE NOT NULL`;
- `legacy_case_code VARCHAR NULL UNIQUE`;
- `title TEXT`;
- `status VARCHAR NOT NULL`;
- `work_state VARCHAR NULL`;
- `row_version BIGINT NOT NULL`;
- `opened_at/resolved_at/closed_at`;
- `created_at/updated_at`;
- `created_by/updated_by`;
- `metadata JSONB NOT NULL`.

`ers_case_events`
- append-only;
- `case_id`, `event_seq`, `event_type`;
- previous/new status lub work state;
- `actor_id`, `request_id`, `correlation_id`;
- `occurred_at`, `payload JSONB`;
- UNIQUE(`case_id,event_seq`).

### 10.2. Asset/Vehicle

`ers_assets` — stabilna tożsamość obiektu.
`ers_asset_revisions` — immutable rewizje identyfikacji.
`ers_case_assets` — relacja case -> asset z rolą.

Vehicle jest reprezentowany jako `asset_kind=vehicle`; maszyna jako `machine`.

### 10.3. ECU

`ers_ecus` — fizyczne ECU.
`ers_case_ecus` — role ECU w case.
`ers_ecu_identity_observations` — immutable hardware/serial/MCU observations.
`ers_ecu_software_observations` — immutable software/calibration/boot/coding observations.

Każda obserwacja może wskazywać `provenance_id` i evidence.

### 10.4. Diagnostyka warsztatowa

`ers_symptoms` — obserwowane objawy.
`ers_dtcs` — surowe DTC/SPN/FMI/OC i status.
`ers_measurements` — immutable measurements.
`ers_diagnostic_steps` — chronologiczne observation/test/result/next-step.
`ers_hypotheses` — hipotezy wraz ze statusem:
`proposed | supported | contradicted | rejected | confirmed`.
`ers_hypothesis_evidence` — evidence z polarity:
`support | contradict | context`.

Confidence hipotezy jest oceną roboczą, nie faktem i nie zastępuje weryfikacji.

### 10.5. Naprawa i wynik

`ers_repair_actions` — planowane/wykonane działania naprawcze, append-only.
`ers_case_results` — outcome, root-cause statement, verification i status potwierdzenia.

Korekta wyniku nie nadpisuje starego wyniku. Nowy rekord wskazuje `supersedes_result_id`.

## 11. Artifact model

`ers_artifacts` jest logicznym artefaktem case:
- `artifact_kind`: photo, pdf, binary, log, can_capture, scope_trace,
  measurement_export, text, other;
- title/role;
- original filename;
- relation do case/ECU/asset;
- created metadata.

`ers_artifact_versions` jest immutable:
- `artifact_id`;
- `version_no`;
- `object_sha256`;
- `byte_size`;
- `media_type`;
- `availability`: `available | missing_original | quarantined`;
- `acquired_at`;
- `provenance_id`;
- opcjonalne `parent_artifact_version_id` i `derivation_type`.

Dla `available` object musi istnieć i przejść SHA-256 verification.
`missing_original` pozwala zachować historyczny expected hash/size bez tworzenia fikcyjnych bajtów.

Raw originals są backup-critical. Thumbnail, preview i inne odtwarzalne pochodne są regenerable.

## 12. Binary Artifact model

Każdy binary artifact jest zwykłym ArtifactVersion z dodatkowym rekordem
`ers_binary_artifacts`.

Minimalne pola:
- `memory_kind`: flash, eeprom, mcu_internal_flash, external_nvm, calibration, readback, other;
- device/chip marking;
- `base_address`;
- `address_length`;
- `full_or_partial`;
- endianness/bus width, jeżeli znane;
- read method/tool;
- acquisition notes;
- provenance.

Analizy binarne są wersjonowane i immutable:

`ers_binary_analysis_runs`
- input artifact version;
- `analysis_profile` i wersja;
- tool/version;
- parameters JSONB;
- status;
- summary/result JSONB;
- created_at.

`ers_binary_comparisons`
- left/right artifact version;
- compare profile/version;
- compared range;
- identical bytes;
- changed bytes;
- similarity ratio;
- result summary.

`ers_binary_changed_ranges`
- comparison ID;
- `start_offset`, `end_offset`;
- changed byte count;
- opcjonalna klasyfikacja/annotation.

`ers_binary_regions`
- analysis run;
- offset range;
- entropy;
- repeat information;
- extracted strings/identity observations;
- profile-specific metadata.

Hexdump windows są domyślnie generowane on-demand. Mogą zostać zapisane jako derived evidence,
ale nie duplikujemy całej binarki w PostgreSQL.

Stage L2 nie wykonuje automatycznego tuningu, checksum correction ani modyfikacji firmware.

## 13. Provenance i evidence

`ers_provenance_records` jest append-only i opisuje pochodzenie danych:
- origin type/URI/ref;
- actor;
- acquisition method;
- tool i tool version;
- acquired_at;
- request/correlation ID;
- metadata.

`ers_provenance_edges` tworzy łańcuch `derived_from`, `copied_from`, `measured_from`,
`extracted_from` albo `supersedes`.

`ers_evidence` reprezentuje konkretny dowód używany w diagnozie.

`authority`:
- `workshop_observation`;
- `manufacturer_documentation`;
- `measured_data`;
- `derived_analysis`;
- `user_statement`;
- `knowledge_retrieval`;
- `ai_inference`.

Evidence ma `locator JSONB` pozwalający wskazać np. stronę/sekcję PDF,
offset/range binarki, timestamp logu, measurement ID albo artifact version.

Dla typów o natywnym rekordzie używamy bezpośrednich relacji:
- evidence -> artifact version;
- evidence -> measurement;
- evidence -> diagnostic step;
- evidence -> Knowledge citation.

Knowledge evidence przechowuje stabilne:
`document_id, version_id, chunk_id, page/section`.
Nie przechowuje Qdrant point ID jako domenowej tożsamości.

Relacje evidence do hypothesis/fact/result zachowują polarity:
`support | contradict | context | verifies`.

## 14. Diagnostic step i hypothesis workflow

Chronologia diagnozy nie jest edytowaną narracją.
Każdy krok zapisuje:
1. observation/input;
2. hypothesis lub cel testu;
3. wykonany test;
4. wynik;
5. decyzję/next step.

Odrzucone tropy pozostają w historii.
AI może proponować hipotezy i testy, ale promocja do potwierdzonego root cause
wymaga operatora i evidence weryfikacyjnego.

## 15. AI diagnosis run

`ers_diagnosis_runs` jest immutable record wykonania:
- `case_id`;
- case revision/event boundary i input fingerprint;
- context builder version;
- diagnosis schema version;
- requested capability;
- Platform request/job ID;
- started/completed timestamps;
- status;
- validated structured result JSONB;
- execution metadata zwrócone przez Platformę;
- failure/insufficiency metadata.

Domena nie ustawia nazwy Ollama/Qwen/modelu jako części normalnego requestu.
Execution metadata służy wyłącznie reprodukowalności i audytowi.

AI result nie modyfikuje automatycznie faktów case.
Operator może jawnie zaakceptować/promować propozycję do hypothesis,
diagnostic step lub repair action; powstaje wtedy case event z provenance.

## 16. Diagnosis result schema v1

Minimalny wynik strukturalny:

```json
{
  "schema_version": 1,
  "advisory_only": true,
  "observed_facts": [],
  "hypotheses": [],
  "recommended_next_tests": [],
  "repair_proposals": [],
  "insufficient_context": false,
  "insufficiency_reason": null,
  "source_refs": []
}
```

Każdy `observed_fact` zawiera statement i `evidence_refs[]`.
Każda hypothesis zawiera statement, status, confidence, supporting evidence
i contradicting evidence.

Confidence jest wartością 0..1 lub null, ale nie jest probabilistycznym dowodem prawdy.
Nie może zastąpić evidence ani human verification.

`recommended_next_tests` zawiera:
- test/measurement;
- rationale;
- prerequisites/safety notes;
- expected outcomes;
- branch decisions, np. `if outcome=A -> next X; if B -> next Y`;
- evidence/source refs.

`repair_proposals` zawiera proposal, rationale, prerequisites, risks i evidence refs.
Proposal pozostaje propozycją do momentu jawnego wykonania/akceptacji.

Każdy claim wymagający wiedzy zewnętrznej ma resolvable source/evidence refs.
Nieznany ref, brak wymaganego cytowania lub invalid schema powodują fail-closed.

## 17. Automotive Context Builder

Docelowy input diagnosis nie jest surowym promptem operatora.

Pipeline:

`case snapshot + measurements + binary analyses + artifacts + Knowledge retrieval
-> automotive context builder -> structured-generation capability -> validated diagnosis`

Context builder jest wersjonowany i deterministyczny dla tego samego input snapshot.
Musi zachować rozdział:
- observed facts;
- manufacturer facts;
- prior-case evidence;
- derived binary facts;
- hypotheses;
- missing/unknown data.

Nie wolno przedstawiać hipotezy jako pomiaru lub faktu OEM.

## 18. ERS -> Knowledge publication

Publikacja jest jawna i idempotentna.

Nowy logiczny Knowledge source:
- domain: `ecu-repair`;
- namespace: `ecu-repair`;
- source_type: `repair-case`;
- source URI: `ers://ecu-repair/cases`.

Każdy case ma stabilny document URI:
`ers://ecu-repair/cases/<case-uuid>`.

Nowa zatwierdzona publikacja tego samego case tworzy nowy DocumentVersion,
nie nowy logiczny dokument.

`ers_case_publications` przechowuje:
- publication ID;
- case ID;
- immutable case snapshot boundary;
- rendered content SHA-256;
- approved_by/approved_at;
- publication status;
- publication schema version.

`ers_knowledge_publication_links` przechowuje zwrócone przez Knowledge:
`source_id, document_id, version_id, index_job_id, state`.

ERS nie zapisuje bezpośrednio do tabel `knowledge_*` ani do vector backendu.

Publication snapshot zawiera wyłącznie zatwierdzone dane przeznaczone do reusable knowledge.
Bieżące draft hypotheses, prywatne notatki i niezatwierdzone wyniki AI nie są publikowane automatycznie.

Correction tworzy nową publication/version i relację supersedes.
Historyczne wersje pozostają audytowalne.

## 19. API surface v1

Minimalne route'y L1:

```text
POST   /api/v1/ecu-repair/cases
GET    /api/v1/ecu-repair/cases/{case_id}
PATCH  /api/v1/ecu-repair/cases/{case_id}
POST   /api/v1/ecu-repair/cases/{case_id}/events

POST   /api/v1/ecu-repair/cases/{case_id}/artifacts
GET    /api/v1/ecu-repair/artifacts/{artifact_id}
GET    /api/v1/ecu-repair/artifacts/{artifact_id}/content

POST   /api/v1/ecu-repair/cases/{case_id}/measurements
POST   /api/v1/ecu-repair/cases/{case_id}/dtcs
POST   /api/v1/ecu-repair/cases/{case_id}/diagnostic-steps
POST   /api/v1/ecu-repair/cases/{case_id}/hypotheses
POST   /api/v1/ecu-repair/cases/{case_id}/repair-actions
POST   /api/v1/ecu-repair/cases/{case_id}/results
```

PATCH używa optimistic concurrency przez `row_version`/ETag semantics.

Dodatkowe route'y kolejnych substage:

```text
POST /api/v1/ecu-repair/binaries/{artifact_version_id}/analyses
POST /api/v1/ecu-repair/binary-comparisons

POST /api/v1/ecu-repair/cases/{case_id}/diagnoses
GET  /api/v1/ecu-repair/diagnoses/{diagnosis_id}

POST /api/v1/ecu-repair/cases/{case_id}/publications
GET  /api/v1/ecu-repair/cases/{case_id}/publications
```

Publiczne odpowiedzi domeny nie zawierają nazw Qdrant/Ollama ani ścieżek storage.

## 20. ObjectStore boundary

Stage L ma wydzielić minimalny platformowy interfejs:

```text
put(bytes) -> {sha256, byte_size, uri}
verify(sha256) -> ok/error
open(sha256) -> stream
exists(sha256) -> bool
```

Pierwsza implementacja może wykorzystać istniejący content-addressed backend Knowledge
bez fizycznego przenoszenia obiektów.

Wydzielenie interfejsu musi pozostawić kompatybilność Stage J:
Knowledge nadal działa przez swój kontrakt i nie wymaga migracji istniejących dokumentów.

Fizyczna ścieżka Object Store jest konfiguracją deploymentu, nie częścią ERS API.

## 21. Backup/DR contract

Stage K pozostaje właścicielem backup/restore.

PostgreSQL:
- istniejący pełny dump `ai_bridge` obejmie tabele `ers_*`;
- manifest ERS ma raportować counts i schema version dla tabel domeny.

Objects:
- Stage K enumeruje wszystkie `available` ERS ArtifactVersions;
- każdy referenced object jest hash-verified przed backupem;
- backup ma własny ERS object-set manifest;
- restore odtwarza obiekty do izolowanego ObjectStore i sprawdza każdy hash;
- brak Qdranta nie może blokować restore Case Store.

Gate DR musi udowodnić:
`empty PostgreSQL + empty ERS object target -> restore -> case/artifact integrity PASS`.

Restore validation nie modyfikuje produkcji.

## 22. Retention

Raw case evidence, original photos, original binaries, measurements użyte jako evidence,
case events i zatwierdzone results nie podlegają automatycznej krótkiej retencji.

Regenerable:
- thumbnails;
- hexdump render;
- entropy windows, jeśli wynik da się odtworzyć;
- vector indexes;
- cache.

Derived artifact może zostać oznaczony jako trwały evidence; wtedy przechodzi do backup-critical.

## 23. Migracja obecnego repo ERS

### 23.1. Pozostaje jako reference/source content

- `sources/**`;
- `components/**`;
- `ecus/**`;
- `engines/**`;
- `machines/**`;
- `tools/**`;
- dokumentacja research/standards w `docs/**`.

Repo pozostaje wartościowym curated corpus i źródłem dla Knowledge.

### 23.2. Seed do aktywnego Case Store

`cases/**` jest materiałem migracyjnym.

CASE-0001:
- można przenieść structured metadata, symptoms, DTC, diagnosis steps, root cause,
  repair/result i istniejące 13 JPEG;
- zdjęcia przechodzą do Object Store z ponowną weryfikacją SHA-256.

CASE-0002:
- można przenieść metadane ECU, checksumy, rozmiary, wyniki porównań i read-back analysis;
- brakujące raw binaries/photos otrzymują `availability=missing_original`;
- nie tworzymy plików zastępczych;
- późniejszy upload jest akceptowany wyłącznie po zgodności SHA-256 i rozmiaru.

### 23.3. OEM PDFs

Hatz/NXP PDF-y pozostają reference documents.
Jeżeli są już canonicalized przez Knowledge, ERS może cytować Knowledge
`document_id/version_id/chunk_id` zamiast tworzyć kopię logiczną dokumentu.

### 23.4. Automotive Semiconductor Corpus v0

Metadata w repo pozostaje source manifest.
Fizyczne PDF-y znajdujące się obecnie tylko w `/tmp` mają status `PROMOTE_REQUIRED`.

Przed cleanup `/tmp` należy:
1. zweryfikować manifest i SHA-256;
2. przenieść źródła do durable controlled source/canonical flow;
3. objąć je backupem albo canonical Knowledge ingestion;
4. zachować reuse/license metadata.

Nie jest to część L0 deployment.

## 24. Security i safety

- brak sekretów w repo/case metadata;
- artifact content jest dostępny tylko przez chronioną granicę Platform API;
- nazwa pliku klienta nie steruje ścieżką storage;
- hash jest liczony po stronie serwera;
- payload size i media type są walidowane;
- executable/unknown files mogą być przechowywane jako evidence, ale nie są uruchamiane;
- AI jest advisory-only;
- aktywne komendy diagnostyczne/programujące pozostają poza L1–L4, dopóki osobny kontrakt ich nie dopuści.

## 25. Finalny podział Stage L

### L0 — Domain Contract / Architecture

#### L0.1 — Read-only audit
Gate:
- repo/source inventory;
- Knowledge/PostgreSQL inventory;
- object/backup inventory;
- zero production mutation.

#### L0.2 — Source-of-truth ADR
Gate:
- zaakceptowane granice PostgreSQL/ObjectStore/Knowledge/Qdrant/Git;
- jawna mutability/versioning policy;
- lifecycle i human approval policy.

#### L0.3 — Domain/schema/API contract
Gate:
- encje i relacje zdefiniowane;
- artifact/binary/evidence/diagnosis schema zdefiniowane;
- API namespace i concurrency contract zdefiniowane.

#### L0.4 — Migration/DR contract
Gate:
- klasyfikacja istniejących danych;
- plan CASE-0001/CASE-0002;
- Stage K extension contract;
- rollback = docs-only.

#### L0.5 — Documentation gate
Gate:
- `git diff --check`;
- review;
- commit, PR, CI, merge;
- brak deployu runtime.

### L1 — Case Store

#### L1.1 — Persistence foundation
- Alembic `ers_*`;
- repositories;
- IDs, constraints, audit events;
- unit/integration tests.

#### L1.2 — Shared ObjectStore + artifacts
- promote reusable content-addressed interface;
- upload/hash/verify/open;
- missing-original semantics;
- no regression Knowledge.

#### L1.3 — Case API/lifecycle
- create/read/update;
- asset/ECU metadata;
- symptoms/DTC/measurements/steps;
- lifecycle invariants and optimistic concurrency.

#### L1.4 — Legacy seed migration
- deterministic importer from current ERS repo;
- dry-run first;
- CASE-0001 complete seed;
- CASE-0002 metadata seed with explicit missing originals;
- idempotency test.

#### L1.5 — ERS DR extension
- PostgreSQL table counts in Stage K manifest;
- ERS object-set manifest;
- isolated restore of case + object integrity.

#### L1.6 — Production gate
- Stage J compatibility smoke;
- rollback to pre-L1 release;
- reactivation;
- no Knowledge publication required yet.

### L2 — Binary Artifact Service

#### L2.1 — Binary metadata/reader
- binary artifact metadata;
- bounded byte-window/hexdump;
- offset/base-address semantics.

#### L2.2 — Deterministic analysis
- SHA-256/size;
- entropy windows;
- repeated regions;
- printable/identity observations;
- versioned analysis profile.

#### L2.3 — Structured comparison
- changed byte count;
- similarity;
- contiguous changed ranges;
- offset-aware comparison;
- ORI/donor/readback roles.

#### L2.4 — CASE-0002 regression
- reproduce known Flash/EEPROM statistics;
- reproduce 0x0000–0x7FFF donor / 0x8000–0x6FFFF ORI result;
- no modification of input artifacts.

#### L2.5 — Parser extension contract
- family-specific parsers behind interface;
- generic analyzer remains default;
- no automatic tuning/chiptuning/checksum patching.

### L3 — ERS <-> Knowledge

#### L3.1 — Publication snapshot
- human-approved immutable publication;
- deterministic render and hash.

#### L3.2 — Knowledge publisher boundary
- `repair-case` source;
- stable case document URI;
- no direct Knowledge DB/Qdrant access.

#### L3.3 — Reindex/idempotency
- repeated publication of same snapshot is no-op;
- new publication creates new Knowledge DocumentVersion;
- reindex remains rebuildable.

#### L3.4 — Retrieval/citations/open-source gate
- published case searchable;
- RAG claim citations resolve;
- source opening działa;
- unpublished/draft data nie pojawia się w Knowledge.

#### L3.5 — Legacy reference ingestion hygiene
- source-cache revision jest immutable/clean;
- bieżący dirty checkout nie jest potajemnie indeksowany;
- obecne legacy Knowledge sources pozostają kompatybilne.

### L4 — Automotive Diagnosis Workflow

#### L4.1 — Context Builder
- deterministic input snapshot;
- case/measurements/binary evidence;
- Knowledge retrieval;
- missing-data model.

#### L4.2 — Structured diagnosis
- schema v1;
- evidence resolver;
- supporting/contradicting evidence;
- next-test branches;
- fail-closed invalid citations/schema.

#### L4.3 — Platform execution
- capability request przez Platform API/provider abstraction;
- istniejący Resource Manager;
- zero bezpośredniego model endpoint.

#### L4.4 — Tools
- read-only case tools;
- bounded binary tools;
- Knowledge search/open;
- measurement lookup;
- brak aktywnego programowania ECU.

#### L4.5 — Evaluation dataset
- frozen snapshots istniejących cases;
- expected facts/evidence/next tests;
- negative cases i insufficient-context cases;
- regression scoring niezależny od konkretnego modelu.

#### L4.6 — Model-change benchmark
Benchmark porównuje modele przez ten sam Context Builder, tools i schema.
Zmiana modelu nie wymaga zmiany ERS.

Fine-tuning/LoRA jest rozważany dopiero wtedy, gdy benchmark pokaże powtarzalną,
mierzalną lukę jakościową względem RAG + structured prompting + tools.

### L5 — Production Gate

Realny przypadek ECU end-to-end:
1. create case;
2. asset/ECU identity;
3. symptoms/DTC/measurements;
4. upload photos/PDF/logs;
5. upload binary artifacts;
6. binary analysis/comparison;
7. Knowledge retrieval;
8. structured diagnosis z evidence;
9. zapis human-reviewed result;
10. human-approved publication;
11. Knowledge search/RAG/citations/source opening;
12. Stage K backup;
13. isolated restore do pustego PostgreSQL/ObjectStore + Knowledge reindex;
14. rollback poprzedniego runtime;
15. rollback smoke;
16. reactivate;
17. final smoke;
18. report, cleanup, commit, PR, CI, merge i post-merge verification.

## 26. Warunek rozpoczęcia L1

L1 nie zaczyna się od migracji produkcyjnej.
Najpierw L0 documentation gate musi być merged i jednoznacznie określać
source of truth, schema boundary, ObjectStore, lifecycle, publication i DR.

To jest Definition of Ready dla implementacji ERS Domain Platform.

## 27. Schema inventory i kolejność migracji

Nie tworzymy wszystkich tabel w jednym big-bang migration.

### L1 core schema

- `ers_cases`
- `ers_case_events`
- `ers_assets`
- `ers_asset_revisions`
- `ers_case_assets`
- `ers_ecus`
- `ers_case_ecus`
- `ers_ecu_identity_observations`
- `ers_ecu_software_observations`
- `ers_symptoms`
- `ers_dtcs`
- `ers_measurements`
- `ers_diagnostic_steps`
- `ers_hypotheses`
- `ers_hypothesis_evidence`
- `ers_repair_actions`
- `ers_case_results`
- `ers_provenance_records`
- `ers_provenance_edges`
- `ers_evidence`
- `ers_artifacts`
- `ers_artifact_versions`

### L2 binary schema

- `ers_binary_artifacts`
- `ers_binary_analysis_runs`
- `ers_binary_comparisons`
- `ers_binary_changed_ranges`
- `ers_binary_regions`

### L3 publication schema

- `ers_case_publications`
- `ers_knowledge_publication_links`

### L4 diagnosis schema

- `ers_diagnosis_runs`

Breaking zmiana semantyki tabel wymaga nowej wersji kontraktu/migracji.
