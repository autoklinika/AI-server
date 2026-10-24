# AI Platform — Granite 4 1B Shadow: produkcyjna aktywacja 2026-10-25

**Host:** `harrypotter-AI-Series`, Ubuntu 26.04  
**Status:** **AKTYWNY / OBSERVE-ONLY** — po ręcznym cutover operatora, bez wdrożenia modelu jako routera produkcyjnego.  
**Czas uruchomienia Gateway:** 2026-10-25 00:16:23 CEST (potwierdzony systemd).  
**Automatyczne zakończenie obserwacji:** epoch `1792966582` = **2026-10-25 23:16:22 CET** (`2026-10-25T22:16:22Z`). W czasie 24-godzinnego okna następuje zmiana czasu CEST → CET.

## 1. Potwierdzone wykonanie operatora

Operator uruchomił:

```bash
sudo python3 /srv/ai-data/staging/granite-shadow-gateway-20261024/activate.py apply
```

Z terminala — kolejność gate'ów:

```text
FROZEN_INPUT_SHAS_PASS
RM_IDLE_AND_RTX_BGE_PASS
GRANITE_SHADOW_PREFLIGHT_PASS
RTX_GRANITE_MODEL_COPY_PASS
RTX_BGE_AND_GRANITE_TAGS_PASS
RTX_GRANITE_SHADOW_INSTALL_SMOKE_PASS
RM_IDLE_AND_RTX_BGE_PASS
RM_IDLE_AND_RTX_BGE_PASS
GRANITE_SHADOW_ACTIVE_24H_PASS until_epoch=1792966582
```

Oznacza to wykonanie kopii tagu i niezbędnych blobów Granite do **istniejącego** dedykowanego magazynu modeli RTX, realne sprawdzenie JSON na CUDA w granicach RM i cutover Gatewaya. Nie instalowano osobnego serwera Ollamy ani drugiego schedulera RM. Oryginalny release Stage O pozostaje bez zmian.

## 2. Niezależny audyt żywego hosta

Weryfikacja przez bezpośrednie odczyty systemd, Gateway `/status` i `/health`, RTX Ollama `/api/tags`, `/api/ps` i `nvidia-smi` około **00:19–00:20 CEST, 25.10.2026**:

| Kontrola | Odczyt |
|---|---|
| `ollama.service` / `ollama-rtx-small.service` | active / active |
| `ai-gateway.service` / `ai-bridge.service` | active / active |
| `comfyui.service` / `ai-platform-radio.service` | active / active |
| Gateway `/health` | `status=ok`, `ollama=ok` |
| RM: active / queued / leases | **0 / 0 / 0** |
| `gpu_residency.recovery_required` | `false` |
| Recovery marker `residency.blocked` | Nieobecny |
| `rtx_embedding_route` | `{"enabled":true,"model":"bge-m3"}` |
| RTX Ollama model tags | **`granite4:1b`, `bge-m3:latest`** |
| RTX `/api/ps` | Brak modeli rezydentnych przy bezczynności |
| GPU | RTX 5060 Ti, 4 MiB przy bezczynności |
| Shadow `enabled` / `mode` | `true` / `observe_only` |
| Shadow `executes_tools` | **false** |
| Shadow `logs_user_text` | **false** |
| Shadow `captured` / `observed` | **0 / 0** w chwili kontroli |
| Shadow `in_memory_pending` | 0 |

W zbadanym przedziale dziennika jądra nie znaleziono dopasowań Xid, PCIe AER ani resetów amdgpu. Nie jest to pełny długotrwały test stabilności GPU.

Aktywny overlay: `/opt/ai-platform/gateway-overlays/granite-shadow-20261024/src`; drop-in: `/etc/systemd/system/ai-gateway.service.d/zzzz-granite-shadow-20261024.conf`. `PYTHONPATH` procesu Gateway wskazywał nowy overlay i `AI_BRIDGE_GATEWAY_RTX_EMBED_URL=http://127.0.0.1:11436` pozostał ustawiony.

## 3. Granice akceptacji

- **PASS:** instalacja, rzeczywisty bounded inference Granite na RTX, odzyskanie idle RM, health Gateway, aktywność usług, niezmieniona trasa BGE-M3, przełącznik czasu, stan obserwatora.
- **JESZCZE NIE TESTOWANO:** poprawności Granite na nowym rzeczywistym ruchu. Liczniki `captured=0`, `observed=0` nie są benchmarkiem jakości. Nie było podstaw do akceptacji routingu produkcyjnego.
- **Obowiązuje:** `GPU_REUSE_SAFE=NOT_VERIFIED`, `N1=NOT_ADMITTED`, brak gwarancji OS-level wyłącznego dostępu do GPU. Shadow korzysta z istniejącego jednokolejkowego RM i wykonuje inferencję tylko w przeznaczonym dla niej oknie, ale ten mechanizm nie dowodzi blokowania wszystkich pozostałych lokalnych wejść.
- Shadow zapisuje metadane decyzji: czas, źródło, trasę, listę nazw narzędzi i opóźnienie; nie utrwala treści zapytania. **Nazwy wybranych narzędzi są etykietami i nie są wykonywane.**
- Pilot ma limit 32 próbek, przerwę co najmniej 180 sekund między przyjętymi obliczeniami oraz datę wygaśnięcia. Po jej osiągnięciu `enabled=false`; **drop-in i overlay nie usuwają się automatycznie**. Ewentualne wycofanie wymaga operatora.

## 4. Read-only monitoring i rollback

```bash
curl -fsS http://127.0.0.1:11435/status
curl -fsS http://127.0.0.1:11435/health
systemctl is-active ai-gateway ollama-rtx-small
nvidia-smi
```

Gdy RM jest idle, bez lease i markerów DIRTY, operator może przywrócić poprzedni aktywny overlay:

```bash
sudo python3 /srv/ai-data/staging/granite-shadow-gateway-20261024/activate.py rollback
```

Ten rollback nie został uruchomiony po udanej aktywacji, więc **rollback acceptance po cutover = NOT_EXECUTED**.

## 5. Powiązane testy

- [Benchmark małych routerów na RTX](ROUTER_RTX_DECISION_BENCHMARK_2026-10-24_PL.md).
- [Powtarzalność Granite 3×51, kalibracja i współrezydencja BGE](ROUTER_GRANITE1B_RTX_BGE_VALIDATION_2026-10-24_PL.md).
- [Nowe przypadki 48 / dwuetapowa selekcja narzędzi](ROUTER_GRANITE1B_NEW48_TOOL_ROUTING_DEV_2026-10-24_PL.md).

**Decyzja:** utrzymać ograniczony pilot shadow do wygaśnięcia, następnie ocenić zebrane metadane i niezależnie oznaczone rzeczywiste przykłady. Nie awansować Granite automatycznie do routingu produkcyjnego.
