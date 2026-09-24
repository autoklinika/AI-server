# AI Platform — Stage L1.2 — Shared ObjectStore + ERS Artifacts Dev Gate

**Data:** 2026-09-24
**Status:** DEV GATE PASS — PRODUCTION SCHEMA STILL 0003
**Baseline main:** `4f21211c9d16cc6a1530b011645ce4b3826b0b31`

## Cel

Wydzielić istniejący content-addressed store Stage J jako wspólną granicę platformową
oraz dodać ERS artifact persistence bez fizycznej migracji istniejących obiektów Knowledge.

Fizyczny layout pozostaje zgodny ze Stage J:
`<root>/sha256/<2>/<sha256>`.
## Shared ObjectStore

Dodano:
`src/ai_bridge/storage/object_store.py`.

Kontrakt:
- `put(bytes)`;
- `exists(sha256)`;
- `verify(sha256)`;
- `read(sha256)`;
- `verify_uri(uri, sha256)`.

Zapis jest atomowy, obiekt po publikacji dostaje tryb read-only,
a istniejący obiekt jest przed reuse ponownie weryfikowany SHA-256.
Nazwa pliku użytkownika nigdy nie jest częścią ścieżki object store.
## Knowledge compatibility

`knowledge.content_store.FileContentStore` pozostaje publicznie kompatybilnym
adapterem Stage J, ale implementacyjnie używa wspólnego `FileObjectStore`.

Knowledge document content opening również weryfikuje teraz:
- file URI;
- zgodność URI z content-addressed path;
- SHA-256;
- istnienie obiektu.

Nie zmieniono fizycznej ścieżki ani żadnego istniejącego `storage_uri`.

Read-only test na realnym canonical object Stage J:
- SHA-256 `313530d7055d615ac15447af307bf37484f5ffe9ced67dd4559ca32e90ff0ee1`;
- 1 676 497 B;
- `STAGE_J_OBJECT_COMPAT=PASS`.
## ERS artifact persistence

Dodano `ErsArtifactRepository` i `ErsArtifactService`.

Obsługiwane:
- utworzenie logicznego Artifact + immutable ArtifactVersion;
- server-side SHA-256;
- append kolejnej wersji;
- monotoniczne `version_no`;
- object dedup przy zachowaniu różnych artifact identities;
- `missing_original` z expected SHA-256/size bez tworzenia fałszywych bajtów;
- read z ponowną kontrolą hash + size;
- parent version + derivation type.

Przy tworzeniu kolejnej wersji repository blokuje rekord Artifact
(`SELECT ... FOR UPDATE` na PostgreSQL), aby serializować numer wersji.
## Walidacja

Targeted:
**15/15 PASS**.

Zakres:
- shared layout Stage J;
- dedup;
- immutable mode;
- missing/corrupt detection;
- legacy FileContentStore compatibility;
- filename/path isolation;
- ERS upload;
- dedup dwóch artifact identities;
- missing_original;
- artifact version chain;
- corrupted-object read fail-closed;
- Stage J canonical ingestion regression;
- Knowledge API regression.

Pełny AI Platform regression suite:
**PASS 100%**.
## Granica

Nie wykonano:
- production `alembic upgrade 0004`;
- uploadu ERS do production ObjectStore;
- migracji CASE-0001/CASE-0002 do Case Store;
- publicznego ERS API;
- rozszerzenia Stage K o ERS object-set manifest (L1.5).

Aktywny Stage J pozostaje bez zmian.

L1.2 jest gotowe do merge.
