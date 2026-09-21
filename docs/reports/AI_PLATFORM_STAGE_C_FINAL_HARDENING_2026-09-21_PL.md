# AI Platform — Stage C final hardening before merge

**Data:** 2026-09-21  
**Branch:** `stage-c/provider-abstraction`  
**Status:** implementation prepared; runtime validation pending

## 1. Zakres audytu

Po zakończeniu C.1–C.4 wykonano przegląd granic provider abstraction przed merge do `main`.

Sprawdzono:

- błędy HTTP/SSE w `HermesAdapter`,
- semantykę `allowed_toolsets`,
- identyfikację node/provider descriptors,
- kontrakt artefaktów media i lokalnego `output_dir`,
- granicę między provider exceptions a przyszłym Platform API.

## 2. Hermes streaming HTTP error

W strumieniowym `httpx.stream()` body odpowiedzi błędnej nie jest automatycznie konsumowane.

Poprzedni kod po `raise_for_status()` próbował odczytać `response.text` już w obsłudze wyjątku. Dla nieodczytanego streamu mogło to wygenerować wtórny `ResponseNotRead` i ukryć rzeczywisty błąd Hermesa.

Hardening:

- body błędu jest odczytywane wewnątrz otwartego stream context,
- dopiero potem tworzony jest znormalizowany `RuntimeError`,
- dodano test regresyjny z nieodczytanym streaming body HTTP 503.

## 3. allowed_toolsets

Aktualny kontrakt `AgentTurnRequest` zachowuje `allowed_toolsets`, ponieważ przyszłe AgentProvider mogą wspierać per-request narrowing.

Obecny Hermes API Server nie udostępnia tego mechanizmu przez używany interfejs.

Decyzja:

- nie udajemy egzekwowania ograniczeń,
- dla niepustego `allowed_toolsets` `HermesAdapter` kończy się fail-closed przez `NotImplementedError`,
- pusta lista oznacza użycie toolsetów skonfigurowanych po stronie providera/platform API server.

Nie rozszerzamy cicho uprawnień narzędzi.

## 4. node_id

Adapter nie może zakładać fizycznego hosta.

Poprzednio `OllamaAdapter`, `HermesAdapter` i `ComfyUIAdapter` miały domyślnie zaszyte `ai-node-01`.

Hardening:

- adaptery mają `node_id: str | None = None`,
- deployment identity jest konfigurowana w `Settings.node_id`,
- aktualny default deploymentu pozostaje `ai-node-01`,
- WVC composition root przekazuje skonfigurowany node do `OllamaAdapter`,
- Stage30 composition root przekazuje skonfigurowany node do `ComfyUIAdapter`,
- przykład env dokumentuje `AI_BRIDGE_NODE_ID=ai-node-01`.

To pozwala później uruchomić provider na innym node bez zmiany kodu adaptera.

## 5. Media output_dir / ObjectRef

`MediaGenerationRequest.output_dir` pozostaje w Stage C wewnętrznym parametrem provider execution.

Jest to świadomy kontrakt przejściowy dla obecnego lokalnego workflow, nie docelowy kontrakt klienta.

Zasada dla kolejnych etapów:

- Platform API nie może zwracać lokalnej ścieżki hosta jako trwałego kontraktu,
- po wprowadzeniu StorageBackend duże artefakty mają być reprezentowane przez `ObjectRef`,
- migracja `MediaArtifact.uri` do storage/object reference musi być wykonana na granicy Platform API/StorageBackend, a nie przez przeciek ComfyUI filesystem do domen.

Stage C nie wdraża StorageBackend i dlatego nie wykonuje tej migracji teraz.

## 6. Error normalization

Adaptery normalizują błędy produktowe na własnej granicy, ale pełny model błędów platformowych:

- `provider_unavailable`,
- `capability_unavailable`,
- `deadline_exceeded`,
- itd.

należy do przyszłego Platform API.

Stage C nie tworzy jeszcze Platform API, więc nie dodajemy tutaj nowej hierarchii publicznych API errors.

## 7. Kryteria finalnej walidacji

Przed merge wymagane:

1. targeted provider/hardening tests PASS,
2. full suite PASS,
3. release build/install validation PASS,
4. aktywny release health PASS,
5. WVC ingest 200 PASS,
6. media preflight PASS,
7. Telegram /wideo regression PASS,
8. Hermes/ComfyUI nieplanowane restarty = brak,
9. Resource Manager idle po testach,
10. git status clean.
