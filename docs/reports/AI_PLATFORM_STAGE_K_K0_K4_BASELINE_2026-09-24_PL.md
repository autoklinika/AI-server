# AI Platform — Stage K K0/K2/K4 baseline

Data: 2026-09-24
Status: DEVELOPMENT BASELINE — NAS DR NOT YET ACCEPTED

## Zakres

Wykonano read-only inventory produkcyjnego AI Servera, zbudowano fail-closed
format lokalnego recovery setu i wykonano pełny izolowany restore validation.
Aktywny Stage J nie został przełączony ani zmodyfikowany.

## K0 — ustalenia

- `/srv/ai-data` jest lokalnym ext4 na osobnym SSD; nie jest NAS.
- Docelowy NAS to `GlobalNAS` / `globalnas.local` / `192.168.1.79`.
- SMB 445/139 jest dostępne.
- Anonimowa sesja SMB jest możliwa, ale listowanie udziałów zwraca
  `STATUS_ACCESS_DENIED`.
- Na AI Serverze brak konfiguracji mount SMB i `cifs-utils`.
- Docelowy root backupu na wskazanym udziale: `AI_Platform/`.
- PostgreSQL `ai_bridge` jest źródłem trwałych danych Knowledge oraz WVC.
- canonical objects są pod `/srv/ai-data/knowledge/canonical/objects`.
- Qdrant jest mały i w pełni odbudowywalny.
- istniejące lokalne backupy/evidence zachowano bez kasowania.
## K2 — lokalny recovery set

Utworzono validation-only recovery set:
`/srv/ai-data/backups/stage-k/k2-validation/AI-Server/sets/manual/20260924T122434Z`.

Offline verification:
- PostgreSQL dump: 36 523 933 B;
- canonical objects: 32;
- canonical bytes: 26 388 772;
- Knowledge versions: 32;
- Knowledge chunks: 566;
- status: PASS.

Ten set nie jest kopią DR, ponieważ znajduje się na tym samym AI Serverze.

## K4 — realny restore validation

Pierwsza próba bezpiecznie zakończyła się FAIL przed restore z powodu limitu
długości Unix-domain socket PostgreSQL w głębokiej ścieżce evidence.
Poprawiono wyłącznie izolowany socket path na `/tmp`; produkcja nie została dotknięta.
Po poprawce K4 odtworzył:
- pusty, izolowany PostgreSQL;
- cały `ai_bridge`;
- 32 canonical objects;
- świeży pusty Qdrant;
- 32 index jobs przez pełny reindex;
- dokładnie 566 punktów Qdrant.

Końcowy deterministyczny rerun:
`/srv/ai-data/backups/stage-k/restore-validation/20260924T122434Z-20260924T123102Z-404060`

Wynik:
- duration: 108.32 s;
- Search results: 8;
- search backend: `knowledge-primary`;
- RAG claims: 1;
- RAG citations: 1;
- source content SHA-256 zweryfikowany;
- production Qdrant points przed: 566;
- production Qdrant points po: 566;
- source Qdrant snapshot used: false;
- status: PASS.
## K2 — walidacja układu per-source

Po decyzji o rozdzieleniu backupów według źródła przetestowano nowy układ
`AI_Platform/`:

- wspólny PostgreSQL: `_Shared/PostgreSQL/ai_bridge/`;
- Knowledge: `Knowledge/canonical-objects/` + `Knowledge/manifests/`;
- WVC: `WVC/manifests/`;
- ERS/Hermes/Platform/CRT mają osobne namespace'y zgodnie z architekturą.

Backup `20260924T130426Z` przeszedł offline verification. Osobny manifest WVC
przeszedł PASS i zawierał liczniki 42 447 ingest batches, 96 563 telemetry raw
oraz 2 730 analysis runs.

Pełny K4 na tym nowym formacie zakończył się PASS:
- pusty izolowany PostgreSQL;
- pusty izolowany Qdrant;
- 32 canonical objects;
- 566 punktów po pełnym reindex;
- Search: 8 wyników;
- RAG: 1 grounded claim / 1 citation;
- source opening i SHA-256: PASS;
- production Qdrant: 566 przed i 566 po;
- duration: 109.003 s.

Drugi backup `20260924T130735Z` potwierdził deduplikację canonical pool:
`copied_objects=0`, `reused_objects=32`.

## Wniosek

Mechanizm danych K2/K4 został praktycznie udowodniony lokalnie:
`PostgreSQL + canonical objects -> empty PostgreSQL restore -> empty Qdrant -> reindex -> Search/RAG/source opening`.

Stage K pozostaje otwarty. Do production acceptance brakuje co najmniej:
- K1 realnego transportu na GlobalNAS i utworzenia rootu `AI_Platform/`;
- K3 szyfrowanego recovery bundle;
- automatyzacji, retencji i monitoringu;
- powtórzenia pełnego K4 na recovery secie pobranym z NAS.
