#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_PYTHON="${HERMES_HOME}/hermes-agent/venv/bin/python"
PYTHON="/opt/ai-bridge/.venv/bin/python"
GATEWAY="http://127.0.0.1:11435"

printf '%s\n' "===== AI GATEWAY STAGE-5 REAL TELEGRAM E2E TEST ====="

[ -x "$PYTHON" ] || { echo "FAIL: production Python missing: $PYTHON"; exit 1; }
[ -x "$HERMES_PYTHON" ] || { echo "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { echo "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || {
    echo "FAIL: ai-gateway.service is not active"
    exit 1
}
[ "$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)" = "active" ] || {
    echo "FAIL: hermes-gateway.service is not active"
    exit 1
}

MODEL="$($HERMES_PYTHON - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys
import yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
model_cfg = cfg.get("model") or {}
if isinstance(model_cfg, str):
    model = model_cfg.strip()
elif isinstance(model_cfg, dict):
    model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
else:
    model = ""
if not model:
    providers = cfg.get("custom_providers") or []
    if isinstance(providers, list):
        for item in providers:
            if isinstance(item, dict) and item.get("model"):
                model = str(item["model"]).strip()
                break
print(model)
PY
)"
[ -n "$MODEL" ] || { echo "FAIL: could not resolve Hermes model"; exit 1; }

echo "model: $MODEL"
echo "gateway: $GATEWAY"
echo

echo "This test does not modify configuration or restart services."
echo "It waits for two REAL Telegram users, then injects one synthetic ventilation inference."
echo

"$PYTHON" - "$MODEL" <<'PY'
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request

MODEL = sys.argv[1]
GATEWAY = "http://127.0.0.1:11435"
STATUS_URL = f"{GATEWAY}/status"
VENT_URL = f"{GATEWAY}/clients/ventilation/api/chat"


def get_status(timeout: float = 2.0) -> dict:
    with urllib.request.urlopen(STATUS_URL, timeout=timeout) as response:
        return json.load(response)


def wait_for(predicate, timeout: float, label: str, interval: float = 0.10):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = get_status()
        result = predicate(last)
        if result:
            return result, last
        time.sleep(interval)
    raise SystemExit(f"FAIL: timeout waiting for {label}; last status={json.dumps(last, ensure_ascii=False)}")


def find_active_hermes(status: dict):
    for row in status.get("active") or []:
        if row.get("source") == "hermes" and row.get("priority") == 50:
            return int(row["job_id"])
    return None


def find_queued_hermes(status: dict, exclude: int):
    for row in status.get("queued") or []:
        if row.get("source") == "hermes" and row.get("priority") == 50 and int(row["job_id"]) != exclude:
            return int(row["job_id"])
    return None


def active_job(status: dict):
    rows = status.get("active") or []
    if not rows:
        return None
    row = rows[0]
    return (int(row["job_id"]), str(row.get("source")), int(row.get("priority")))


initial = get_status()
if initial.get("max_concurrency") != 1:
    raise SystemExit(f"FAIL: expected max_concurrency=1, got {initial.get('max_concurrency')}")
if initial.get("active_count") or initial.get("queued_count"):
    raise SystemExit(
        "FAIL: scheduler is not idle. Finish current AI work and run the test again. "
        + json.dumps(initial, ensure_ascii=False)
    )
print("PASS: gateway idle, max_concurrency=1")
print()
print("STEP 1/3 — TELEGRAM USER A")
print("From the FIRST Telegram account, send this now:")
print("  Napisz opis architektury lokalnego serwera AI w około 500 słowach. Nie używaj narzędzi.")
print("Waiting for a real Hermes inference...")

job_a, st = wait_for(lambda s: find_active_hermes(s), 180, "Telegram user A Hermes job")
print(f"PASS: Telegram A reached scheduler as Hermes job={job_a} priority=50")
print()
print("STEP 2/3 — TELEGRAM USER B")
print("From the SECOND Telegram account, send this immediately:")
print("  Napisz dokładnie: TELEGRAM_B_OK")
print("Waiting until user B is queued behind user A...")

job_b, st = wait_for(lambda s: find_queued_hermes(s, job_a), 120, "Telegram user B queued Hermes job")
print(f"PASS: Telegram B queued as Hermes job={job_b} priority=50")

vent_result: dict[str, object] = {}
vent_error: list[str] = []


def run_ventilation() -> None:
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": "Odpowiedz jednym słowem: VENT_OK"}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }).encode("utf-8")
    req = urllib.request.Request(
        VENT_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        started = time.monotonic()
        with urllib.request.urlopen(req, timeout=900) as response:
            body = json.load(response)
            vent_result.update({
                "job_id": int(response.headers.get("X-AI-Gateway-Job-Id", "0")),
                "priority": response.headers.get("X-AI-Gateway-Priority"),
                "wait_ms": response.headers.get("X-AI-Gateway-Wait-Ms"),
                "elapsed": time.monotonic() - started,
                "body": body,
            })
    except Exception as exc:  # diagnostic script
        vent_error.append(repr(exc))


print()
print("STEP 3/3 — INJECTING VENTILATION PRIORITY-10 REQUEST")
t = threading.Thread(target=run_ventilation, daemon=True)
t.start()


def queue_has_vent_ahead_of_b(status: dict):
    queued = status.get("queued") or []
    vent_index = None
    b_index = None
    vent_id = None
    for idx, row in enumerate(queued):
        if row.get("source") == "ventilation" and row.get("priority") == 10 and vent_index is None:
            vent_index = idx
            vent_id = int(row["job_id"])
        if int(row.get("job_id", -1)) == job_b:
            b_index = idx
    if vent_index is not None and b_index is not None and vent_index < b_index:
        return vent_id
    return None

job_v, queue_status = wait_for(queue_has_vent_ahead_of_b, 30, "ventilation queued ahead of Telegram B")
print("queue snapshot:")
print(json.dumps(queue_status, ensure_ascii=False, indent=2))
print(f"PASS: ventilation job={job_v} priority=10 queued ahead of Telegram B job={job_b}")

transitions: list[tuple[int, str, int]] = [(job_a, "hermes", 50)]
last = transitions[-1]
started_observation = time.monotonic()
deadline = started_observation + 900
while time.monotonic() < deadline:
    st = get_status()
    cur = active_job(st)
    if cur is not None and cur != last:
        transitions.append(cur)
        last = cur
    if st.get("active_count") == 0 and st.get("queued_count") == 0:
        break
    time.sleep(0.05)
else:
    elapsed = time.monotonic() - started_observation
    raise SystemExit(
        f"FAIL: scheduler did not return to idle during stage-5 observation after {elapsed:.1f}s"
    )

t.join(timeout=2)
if vent_error:
    raise SystemExit(f"FAIL: synthetic ventilation request failed: {vent_error[0]}")
if not vent_result:
    raise SystemExit("FAIL: ventilation request did not return a result")
if vent_result.get("priority") != "10":
    raise SystemExit(f"FAIL: ventilation response priority was {vent_result.get('priority')!r}")

filtered: list[tuple[int, str, int]] = []
for row in transitions:
    if row[0] not in {job_a, job_v, job_b}:
        continue
    if not filtered or filtered[-1] != row:
        filtered.append(row)

ids = [row[0] for row in filtered]
expected = [job_a, job_v, job_b]
print()
print("observed active sequence:")
for job_id, source, priority in filtered:
    print(f"  job={job_id} source={source} priority={priority}")

if ids != expected:
    raise SystemExit(f"FAIL: expected active order {expected}, observed {ids}")

final = get_status()
if final.get("active_count") != 0 or final.get("queued_count") != 0:
    raise SystemExit(f"FAIL: gateway did not return to idle: {final}")

print()
print("PASS: REAL Telegram A -> ventilation -> REAL Telegram B ordering observed")
print(
    "PASS: ventilation result "
    f"job={vent_result['job_id']} priority={vent_result['priority']} "
    f"wait_ms={vent_result['wait_ms']} elapsed={vent_result['elapsed']:.2f}s"
)
print("PASS: gateway returned to idle")
print()
print("Now verify on both phones/accounts that each Telegram user received the response to their own message.")
PY

echo
echo "PASS: stage-5 real Telegram end-to-end scheduler validation completed"
