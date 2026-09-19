# AI Platform — Network Policy v1

**Status:** ACTIVE  
**Data:** 2026-09-19  
**Zakres:** AI Server host network exposure after Stage B

## 1. Zasada

Host stosuje politykę:

- inbound: deny by default,
- outbound: allow,
- backendy AI są lokalne i nie stanowią API dla LAN,
- administracja jest dostępna przez LAN i Tailscale,
- AI Bridge pozostaje osiągalny wyłącznie z LAN jako istniejący endpoint domenowy WVC.

## 2. Interfejsy

- LAN/Wi-Fi: `192.168.1.55/24`
- Tailscale: `100.112.82.87/32`

## 3. Dozwolony ruch przychodzący

### LAN `192.168.1.0/24`

- TCP 22 — SSH
- TCP 8080 — AI Bridge / WVC domain API
- TCP 9090 — Cockpit

### Tailscale

- TCP 22 — SSH
- TCP 9090 — Cockpit
- UDP 41641 — transport Tailscale

AI Bridge nie jest wystawiony na adresie Tailscale.

## 4. Bind policy usług

- AI Bridge: `192.168.1.55:8080`
- AI Gateway: `127.0.0.1:11435`
- Ollama: `127.0.0.1:11434`
- ComfyUI: `127.0.0.1:8188`
- Hermes gateway: `127.0.0.1:8642`
- PostgreSQL: `127.0.0.1:5432`

Backendy inference/media nie są bezpośrednio osiągalne z LAN ani przez Tailscale.

## 5. UFW

Aktywna polityka:

```text
default incoming: deny
default outgoing: allow
default routed: deny
```

Reguły użytkownika utrzymywane są przez:

`deploy/stage-b/apply_host_firewall.sh`

Rollback:

`deploy/stage-b/rollback_host_firewall.sh`

## 6. Tailscale i kolejność firewall

Tailscale instaluje własny chain `ts-input`, który jest wykonywany przed chainami UFW i akceptuje ruch z `tailscale0`.

Dlatego bezpieczeństwo usług na adresie Tailscale nie może polegać wyłącznie na regułach UFW. Backend AI musi również posiadać poprawny bind:

- localhost-only dla backendów wewnętrznych,
- LAN-only dla AI Bridge.

Ta zasada jest obowiązująca dla kolejnych usług platformowych.

## 7. Multicast systemowy

Standardowe reguły `ufw-before-input` systemu dopuszczają ograniczony ruch multicast, m.in. mDNS/SSDP.

Nie stanowi to ekspozycji backendów AI. Stage B nie zmienia usług systemowych Avahi/CUPS; ich zasadność może być oceniona osobno podczas dalszego hardeningu hosta.

## 8. Zweryfikowane zachowanie

Z klienta LAN:

- `192.168.1.55:22` — reachable
- `192.168.1.55:8080` — reachable
- `192.168.1.55:9090` — reachable
- `192.168.1.55:11434` — blocked
- `192.168.1.55:11435` — blocked
- `192.168.1.55:8188` — blocked

Przez Tailscale:

- `100.112.82.87:22` — reachable
- `100.112.82.87:9090` — reachable
- `100.112.82.87:8080` — blocked po wprowadzeniu LAN-only bind AI Bridge.

## 9. Reguła dla przyszłych usług

Nowa usługa nie może domyślnie nasłuchiwać na `0.0.0.0` / `::`.

Każdy nowy endpoint musi jawnie określić jedną z klas:

- localhost/private service,
- LAN domain API,
- Tailscale administration,
- public — tylko po osobnym security review.
