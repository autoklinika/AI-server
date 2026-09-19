# AI Platform — Stage B Final Report

**Data:** 2026-09-19  
**Stage:** Security hardening without behavior change  
**Issue:** #33  
**Status:** PASS

## 1. Cel

Stage B miał ograniczyć ekspozycję backendów AI i wprowadzić jawny host network policy bez zmiany funkcjonalności użytkowej.

Cel został osiągnięty.

## 2. Ollama

Przed zmianą:

`*:11434`

Po zmianie:

`127.0.0.1:11434`

AI Gateway nadal korzysta z Ollamy lokalnie i health zwraca `ollama=ok`.

Wprowadzono:

- `deploy/systemd/stage-b/ollama.service.d/zz-localhost-only.conf`
- `deploy/stage-b/apply_ollama_localhost.sh`
- `deploy/stage-b/rollback_ollama_localhost.sh`

## 3. ComfyUI

Przed zmianą:

`0.0.0.0:8188`

Po zmianie:

`127.0.0.1:8188`

Endpoint `/system_stats` działa po localhost.

Wprowadzono:

- `deploy/systemd/stage-b/comfyui.service.d/zz-localhost-only.conf`
- apply/rollback scripts Stage B.

## 4. AI Bridge

Początkowo:

`0.0.0.0:8080`

Po analizie Tailscale chain `ts-input` AI Bridge został ograniczony do:

`192.168.1.55:8080`

Dzięki temu:

- WVC/LAN zachowuje dostęp,
- AI Bridge nie jest dostępny pod adresem Tailscale,
- nie modyfikujemy chainów zarządzanych przez Tailscale.

Stage A operational health checks zostały zaktualizowane do LAN address.

## 5. Host firewall

UFW został włączony.

Polityka:

- default deny incoming,
- default allow outgoing,
- default deny routed.

Jawne wyjątki:

LAN:
- 22/tcp SSH,
- 8080/tcp AI Bridge,
- 9090/tcp Cockpit.

Tailscale:
- 22/tcp SSH,
- 9090/tcp Cockpit,
- 41641/udp transport.

Przy pierwszym włączeniu zastosowano 2-minutowy systemd failsafe. Po pozytywnej walidacji failsafe został anulowany.

Rollback:

`deploy/stage-b/rollback_host_firewall.sh`

## 6. Walidacja z laptopa

LAN:

- 22: PASS reachable
- 8080: PASS reachable
- 9090: PASS reachable
- 11434: PASS blocked
- 11435: PASS blocked
- 8188: PASS blocked

Tailscale:

- 22: PASS reachable
- 9090: PASS reachable
- 8080: początkowo reachable z powodu `ts-input`; po LAN-only bind AI Bridge — PASS blocked.

## 7. Post-hardening runtime

Zweryfikowane listenery:

- AI Bridge — `192.168.1.55:8080`
- ComfyUI — `127.0.0.1:8188`
- Ollama — `127.0.0.1:11434`
- AI Gateway — `127.0.0.1:11435`

Hermes nadal działa jako lokalny proces gateway.

## 8. Smoke tests

PASS:

- AI Bridge health,
- AI Gateway health,
- Ollama API tags,
- ComfyUI system_stats,
- Hermes -> AI Gateway models route,
- Resource Manager status,
- media backend local route,
- LAN/Tailscale external reachability policy,
- wszystkie kluczowe usługi active.

## 9. Brak zmiany funkcjonalności

Stage B nie zmienił:

- modelu Qwen,
- providerów,
- Hermes logic,
- ComfyUI workflows/models,
- AI Gateway scheduler semantics,
- WVC domain API,
- Telegram/Discord UX.

Zmiany dotyczą wyłącznie bindów i polityki sieciowej hosta.

## 10. Uwagi

UFW posiada standardowe systemowe reguły before-input dla wybranych multicastów mDNS/SSDP. Nie wystawiają one backendów AI. Usługi hostowe takie jak Avahi mogą zostać poddane osobnemu review w przyszłości.

## 11. Definition of Done

- Ollama localhost-only: PASS
- ComfyUI localhost-only: PASS
- AI Gateway localhost-only: PASS
- AI Bridge LAN-only: PASS
- host firewall deny-by-default: PASS
- administracja LAN/Tailscale zachowana: PASS
- wymagane API domenowe zachowane: PASS
- backend bypass z LAN zablokowany: PASS
- smoke tests: PASS
- rollback scripts: PRESENT
- produkcyjne zachowanie AI zachowane: PASS

**Stage B technical implementation: COMPLETE.**

Następny etap zgodnie z Migration Plan:

**Stage C / Etap 3 — Provider abstraction.**
