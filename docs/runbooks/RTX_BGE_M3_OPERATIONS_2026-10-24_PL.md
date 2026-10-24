# Runbook — BGE-M3 na RTX 5060 Ti / istniejący Gateway RM

**Data:** 2026-10-24  
**Stan:** wdrożenie BGE-M3 `PASS`; rollback produkcyjny `NOT_EXECUTED`.  
**Raport:** [RTX_BGE_M3_PRODUCTION_ACCEPTANCE_2026-10-24_PL.md](../reports/RTX_BGE_M3_PRODUCTION_ACCEPTANCE_2026-10-24_PL.md).

## Co działa

- `ollama.service`, `127.0.0.1:11434` — istniejący tor Qwen / Radeon.
- `ollama-rtx-small.service`, `127.0.0.1:11436` — tylko BGE-M3 / CUDA RTX.
- `ai-gateway.service`, `127.0.0.1:11435` — jeden RM, jedna kolejka; embedding BGE-M3 trafia na RTX.
- `comfyui.service` i `ai-platform-radio.service` pozostają na dotychczasowym torze.
- CUDA/Ollama nie musi trzymać BGE-M3 stale w VRAM: `OLLAMA_KEEP_ALIVE=10m`. Idle RTX o zużyciu ~4 MiB jest normalny.

## Szybki przegląd bez zmian stanu (read-only)

```bash
systemctl is-active ollama ollama-rtx-small ai-gateway ai-bridge comfyui ai-platform-radio
systemctl is-enabled ollama-rtx-small
curl -fsS http://127.0.0.1:11435/health
curl -fsS http://127.0.0.1:11435/status
curl -fsS http://127.0.0.1:11436/api/tags
curl -fsS http://127.0.0.1:11436/api/ps
curl -fsS http://127.0.0.1:11434/api/ps
nvidia-smi --query-gpu=name,memory.used,utilization.gpu --format=csv,noheader
test ! -e /var/lib/ai-platform-gpu/residency.blocked && echo RM_FENCE_CLEAR
```

W `/status` wymagane: `rtx_embedding_route.enabled=true`, `model=bge-m3`; w stanie spoczynku `active_count=0`, `queued_count=0`, `resource_leases.lease_count=0`, `gpu_residency.recovery_required=false`. Legacy `gpu_residency.state=llm` nie jest oznaczeniem konkretnego GPU.

Nie wykonuj wywołania inferencji bez sprawdzenia aktualnego przydziału RM, producentów zadań oraz stanu drivera. W przypadku incydentu GPU obowiązuje [GPU_RESIDENCY_RECOVERY](GPU_RESIDENCY_RECOVERY.md), a nie ręczny reset sterownika.

## Ścieżka administracyjna i rollback

Skrypt instalacyjny na serwerze:
```bash
sudo bash /srv/ai-data/staging/rtx-small-migration-20261024/apply-rtx-bge.sh check
```

Instalacja **już została wykonana** 24.10.2026; **nie uruchamiać ponownie `apply`** na istniejącym wdrożeniu. W celu przywrócenia trasy BGE do pierwotnej Ollamy, tylko po zatrzymaniu nowych żądań i weryfikacji `RM_IDLE`, 0 leases oraz braku `DIRTY`:
```bash
sudo bash /srv/ai-data/staging/rtx-small-migration-20261024/apply-rtx-bge.sh rollback
```

Skrypt usuwa *tylko* swój drop-in Gateway, przywraca poprzednią ścieżkę kodu przez restart Gateway i wyłącza dedykowaną usługę RTX. Nie usuwa oryginalnych modeli Ollamy ani skopiowanych blobów BGE-M3. Następnie konieczny jest ręczny odczyt `/health`, `/status` i kontrola, że BGE-M3 nie jest już kierowany na `:11436`. **Rollback nie został sprawdzony w faktycznej produkcji** — nie zakładać PASS bez dowodu.

Jeżeli preflight, lease lub recovery fence blokuje zmianę, **nie** obchodź blokady ręcznie i nie usuń markerów. Przy awarii przed rollbackiem zabezpiecz logi, statusy i identyfikatory procesów.

## Co zmieniono / czego nie zmieniono

Instalator:
1. kopiuje manifest + bloby samego BGE-M3 do `/srv/ai-data/platform/rtx-small/ollama-models`;
2. instaluje `/etc/systemd/system/ollama-rtx-small.service`;
3. instaluje oddzielny overlay `/opt/ai-platform/gateway-overlays/rtx-bge-m3-20261024/src` (skopiowany z ostatniego zaakceptowanego overlay Vision RADIO, z niewielką zmianą);
4. dodaje `/etc/systemd/system/ai-gateway.service.d/zz-rtx-bge-m3.conf`;
5. testuje CUDA 1024D oraz identyczność bezpośredniego wektora i wektora przez RM.

Bez zmian: oryginalne `ollama.service` i jego modele, Qwen 27B, ComfyUI, Vision RADIO, Knowledge Qdrant 1024D, Stage O release/symlink. **Brak OS-wide GPU deny i brak zatwierdzonego N1 multi-GPU grant**.

## Planowane działania, osobno od produkcji

- Benchmark GLiNER i innych lekkich routerów na RTX: **decyzja produkcyjna niepodjęta**; oceniać routing PL/EN, multi-label, selection/tool-policy, latencję i false positive.
- Test Knowledge/RAG end-to-end po migracji na danych rzeczywistych i porównanie AMD↔RTX — **jeszcze nieodebrane**.
- W przyszłej aktualizacji Gateway przenieść małą zmianę routingową z overlay hosta do kodu źródłowego przez zwykły PR + CI, z kontrolą aktualnego produkcyjnego źródła i rollbacku. Nie instalować starego obrazu z `main` w przekonaniu, że zawiera fizyczny route RTX.
