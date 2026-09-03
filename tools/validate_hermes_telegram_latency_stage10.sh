#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_SOURCE="${HERMES_HOME}/hermes-agent"
HERMES_PYTHON="${HERMES_SOURCE}/venv/bin/python"
PYTHON="/opt/ai-bridge/.venv/bin/python"
GATEWAY="http://127.0.0.1:11435"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$PYTHON" ] || { say "FAIL: production Python missing: $PYTHON"; exit 1; }
[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -d "$HERMES_SOURCE" ] || { say "FAIL: Hermes source missing: $HERMES_SOURCE"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ai-gateway.service is not active"; exit 1; }
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: hermes-gateway.service is not active"; exit 1; }

section "STAGE-10 REAL TELEGRAM LATENCY AFTER REASONING-OFF"
say "Read-only observation: no configuration changes and no service restarts."
say "This uses the same long Telegram-A prompt as Stage 5, but does not inject ventilation."

section "PRECHECK REASONING-OFF"
"$HERMES_PYTHON" - "$HERMES_CONFIG" "$HERMES_SOURCE" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
sys.path.insert(0, sys.argv[2])
value = (cfg.get("agent") or {}).get("reasoning_effort")
print("raw agent.reasoning_effort:", repr(value), "type:", type(value).__name__)
if not isinstance(value, str) or value.strip().lower() != "none":
    raise SystemExit("FAIL: Hermes reasoning_effort is not literal string 'none'")
from hermes_constants import resolve_reasoning_config
model_cfg = cfg.get("model") or {}
if isinstance(model_cfg, dict):
    model = str(model_cfg.get("default") or model_cfg.get("model") or "")
else:
    model = str(model_cfg)
resolved = resolve_reasoning_config(cfg, model)
print("resolved reasoning_config:", repr(resolved))
if not isinstance(resolved, dict) or resolved.get("enabled") is not False:
    raise SystemExit(f"FAIL: installed Hermes runtime did not resolve reasoning disabled: {resolved!r}")
print("PASS: Hermes reasoning is disabled")
PY

"$PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=2) as r:
    s = json.load(r)
if s.get("max_concurrency") != 1:
    raise SystemExit(f"FAIL: expected max_concurrency=1, got {s.get('max_concurrency')}")
if s.get("active_count") or s.get("queued_count"):
    raise SystemExit("FAIL: AI Gateway is not idle: " + json.dumps(s, ensure_ascii=False))
print("PASS: AI Gateway idle, max_concurrency=1")
PY

section "REAL TELEGRAM TEST"
"$PYTHON" - <<'PY'
from __future__ import annotations

import json
import time
import urllib.request

STATUS_URL = "http://127.0.0.1:11435/status"


def get_status() -> dict:
    with urllib.request.urlopen(STATUS_URL, timeout=2) as r:
        return json.load(r)


def find_active_hermes(status: dict, exclude: set[int] | None = None):
    exclude = exclude or set()
    for row in status.get("active") or []:
        if row.get("source") == "hermes" and int(row.get("priority", -9999)) == 50:
            jid = int(row["job_id"])
            if jid not in exclude:
                return row
    return None


def find_queued_hermes(status: dict, exclude: set[int] | None = None):
    exclude = exclude or set()
    for row in status.get("queued") or []:
        if row.get("source") == "hermes" and int(row.get("priority", -9999)) == 50:
            jid = int(row["job_id"])
            if jid not in exclude:
                return row
    return None


def wait_for(fn, timeout: float, label: str, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = get_status()
        result = fn(last)
        if result:
            return result, last, time.monotonic()
        time.sleep(interval)
    raise SystemExit(f"FAIL: timeout waiting for {label}; last={json.dumps(last, ensure_ascii=False)}")

initial = get_status()
if initial.get("active_count") or initial.get("queued_count"):
    raise SystemExit("FAIL: scheduler stopped being idle before test start")

print("STEP 1/2 — Telegram user A")
print("From FIRST Telegram account send exactly:")
print("  Napisz opis architektury lokalnego serwera AI w około 500 słowach. Nie używaj narzędzi.")
print("Waiting for Hermes job A...")
row_a, _, t_a_detect = wait_for(lambda s: find_active_hermes(s), 180, "Telegram A active job")
job_a = int(row_a["job_id"])
print(f"PASS: A active job={job_a} priority=50 wait_ms={row_a.get('wait_ms')}")

print()
print("STEP 2/2 — Telegram user B")
print("Immediately from SECOND Telegram account send exactly:")
print("  Napisz dokładnie: TELEGRAM_B_OK")
print("Waiting for B to enter queue behind A...")
row_bq, _, t_b_queued = wait_for(
    lambda s: find_queued_hermes(s, {job_a}),
    120,
    "Telegram B queued job",
)
job_b = int(row_bq["job_id"])
print(f"PASS: B queued job={job_b} priority=50")

# Observe A -> B -> idle. Polling timestamps are local observer times;
# B's scheduler wait_ms is authoritative once it becomes active.
t_a_end = None
t_b_start = None
t_b_end = None
b_wait_ms = None
last_status = None
deadline = time.monotonic() + 900
while time.monotonic() < deadline:
    now = time.monotonic()
    st = get_status()
    last_status = st
    active = st.get("active") or []
    active_ids = {int(r["job_id"]): r for r in active}

    if t_a_end is None and job_a not in active_ids:
        # Do not declare A finished while B is still queued and no active job
        # has been observed yet unless scheduler is genuinely transitioning.
        t_a_end = now

    if job_b in active_ids and t_b_start is None:
        t_b_start = now
        b_wait_ms = float(active_ids[job_b].get("wait_ms") or 0.0)
        if t_a_end is None:
            t_a_end = now
        print(f"PASS: B became active; scheduler wait_ms={b_wait_ms:.1f}")

    if t_b_start is not None and job_b not in active_ids:
        if st.get("active_count") == 0 and st.get("queued_count") == 0:
            t_b_end = now
            break

    time.sleep(0.05)
else:
    raise SystemExit(
        "FAIL: scheduler did not return to idle within 900s; last="
        + json.dumps(last_status, ensure_ascii=False)
    )

if t_a_end is None or t_b_start is None or t_b_end is None or b_wait_ms is None:
    raise SystemExit("FAIL: incomplete timing observation")

# A timing starts when the observer first detected it active, so it is a slight
# underestimate of real A service time by at most the polling/detection delay.
a_active_s = max(0.0, t_a_end - t_a_detect)
b_queue_observed_s = max(0.0, t_b_start - t_b_queued)
b_active_s = max(0.0, t_b_end - t_b_start)
total_observed_s = max(0.0, t_b_end - t_a_detect)

print()
print("===== STAGE-10 TIMING SUMMARY =====")
print(f"Telegram A active observed: {a_active_s:.2f}s")
print(f"Telegram B queue observed:  {b_queue_observed_s:.2f}s")
print(f"Telegram B scheduler wait:  {b_wait_ms/1000.0:.2f}s")
print(f"Telegram B active observed: {b_active_s:.2f}s")
print(f"A-start -> all idle:        {total_observed_s:.2f}s")
print(f"jobs: A={job_a} B={job_b}")
print()
print("PASS: scheduler returned to idle after two real Telegram jobs")
print("Now verify both Telegram accounts received the response belonging to their own message.")
PY

section "POSTCHECK"
"$PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=2) as r:
    h = json.load(r)
assert h.get("status") == "ok" and h.get("ollama") == "ok", h
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=2) as r:
    s = json.load(r)
assert s.get("active_count") == 0 and s.get("queued_count") == 0, s
print("PASS: AI Gateway healthy and idle")
PY

say
say "PASS: Stage-10 real Telegram latency observation completed"
