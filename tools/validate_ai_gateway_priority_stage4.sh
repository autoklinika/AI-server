#!/usr/bin/env bash
set -euo pipefail

PYTHON="/opt/ai-bridge/.venv/bin/python"
GATEWAY="http://127.0.0.1:11435"
HERMES_BASE="${GATEWAY}/clients/hermes/v1"
VENT_BASE="${GATEWAY}/clients/ventilation"
HERMES_CONFIG="/srv/ai-data/hermes/config.yaml"

printf '%s\n' "===== AI GATEWAY STAGE-4 PRIORITY CONTENTION TEST ====="

[ -x "$PYTHON" ] || { echo "FAIL: production Python missing: $PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { echo "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || {
  echo "FAIL: ai-gateway.service is not active"
  exit 1
}
[ "$(systemctl is-active ollama.service 2>/dev/null || true)" = "active" ] || {
  echo "FAIL: ollama.service is not active"
  exit 1
}

"$PYTHON" - "$GATEWAY" "$HERMES_BASE" "$VENT_BASE" "$HERMES_CONFIG" <<'PY'
from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
import sys
import time
import urllib.request

import yaml

gateway, hermes_base, vent_base, config_path = sys.argv[1:]
config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
model_cfg = config.get("model") or {}
model = ""
if isinstance(model_cfg, str):
    model = model_cfg.strip()
elif isinstance(model_cfg, dict):
    model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
if not model:
    providers = config.get("custom_providers") or []
    if isinstance(providers, list):
        for item in providers:
            if isinstance(item, dict) and item.get("model"):
                model = str(item["model"]).strip()
                break
if not model:
    raise SystemExit("FAIL: could not resolve Hermes model")


def status():
    with urllib.request.urlopen(gateway + "/status", timeout=2) as response:
        return json.load(response)


def post_json(url: str, payload: dict, timeout: int = 600):
    started = time.monotonic()
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = json.load(response)
        meta = {
            "priority": response.headers.get("X-AI-Gateway-Priority"),
            "job_id": response.headers.get("X-AI-Gateway-Job-Id"),
            "wait_ms": response.headers.get("X-AI-Gateway-Wait-Ms"),
            "elapsed": time.monotonic() - started,
        }
    return body, meta


def wait_for(predicate, label: str, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = status()
        if predicate(last):
            return last
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting for {label}; last status={last}")


def hermes_payload(text: str, max_tokens: int):
    return {
        "model": model,
        "messages": [{"role": "user", "content": text}],
        "stream": False,
        "temperature": 0,
        "max_tokens": max_tokens,
    }


def vent_payload():
    return {
        "model": model,
        "messages": [{"role": "user", "content": "Odpowiedz jednym słowem: VENT_OK"}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 16},
    }

initial = status()
assert initial.get("max_concurrency") == 1, initial
assert initial.get("active_count") == 0, f"gateway busy before test: {initial}"
print(f"model: {model}")
print("PASS: gateway idle, max_concurrency=1")

completion_order: list[str] = []


def run(label, url, payload):
    result = post_json(url, payload)
    completion_order.append(label)
    return result

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    a = pool.submit(
        run,
        "hermes-A",
        hermes_base + "/chat/completions",
        hermes_payload(
            "Napisz dokładnie 500 krótkich, ponumerowanych pozycji od 1 do 500. "
            "Każda pozycja ma zawierać słowo TEST i numer. Nie skracaj listy.",
            1800,
        ),
    )

    active_a = wait_for(
        lambda s: s.get("active_count") == 1
        and (s.get("active") or [{}])[0].get("source") == "hermes",
        "Hermes A active",
    )
    a_job = active_a["active"][0]["job_id"]
    print(f"PASS: Hermes A active job={a_job}")

    b = pool.submit(
        run,
        "hermes-B",
        hermes_base + "/chat/completions",
        hermes_payload("Odpowiedz jednym słowem: HERMES_B_OK", 32),
    )

    queued_b = wait_for(
        lambda s: any(
            j.get("source") == "hermes" and j.get("priority") == 50
            for j in (s.get("queued") or [])
        ),
        "Hermes B queued",
    )
    b_jobs = [j for j in queued_b["queued"] if j.get("source") == "hermes"]
    b_job = b_jobs[0]["job_id"]
    print(f"PASS: Hermes B queued job={b_job} priority=50")

    v = pool.submit(run, "ventilation", vent_base + "/api/chat", vent_payload())

    ordered = wait_for(
        lambda s: len(s.get("queued") or []) >= 2
        and (s.get("queued") or [])[0].get("source") == "ventilation"
        and (s.get("queued") or [])[0].get("priority") == 10
        and any(
            j.get("source") == "hermes" and j.get("priority") == 50
            for j in (s.get("queued") or [])[1:]
        ),
        "ventilation ahead of waiting Hermes",
    )
    print("queue snapshot:")
    print(json.dumps(ordered, indent=2))
    print("PASS: later ventilation job is queued ahead of waiting Hermes B")

    a_body, a_meta = a.result(timeout=600)
    v_body, v_meta = v.result(timeout=600)
    b_body, b_meta = b.result(timeout=600)

assert a_meta["priority"] == "50", a_meta
assert v_meta["priority"] == "10", v_meta
assert b_meta["priority"] == "50", b_meta
assert int(v_meta["job_id"]) > int(b_meta["job_id"]), (v_meta, b_meta)
assert completion_order == ["hermes-A", "ventilation", "hermes-B"], completion_order

final = wait_for(
    lambda s: s.get("active_count") == 0 and s.get("queued_count") == 0,
    "gateway idle after test",
    timeout=30,
)

print("completion order:", " -> ".join(completion_order))
print(
    "Hermes A:",
    f"job={a_meta['job_id']} priority={a_meta['priority']} wait_ms={a_meta['wait_ms']} elapsed={a_meta['elapsed']:.2f}s",
)
print(
    "Ventilation:",
    f"job={v_meta['job_id']} priority={v_meta['priority']} wait_ms={v_meta['wait_ms']} elapsed={v_meta['elapsed']:.2f}s",
)
print(
    "Hermes B:",
    f"job={b_meta['job_id']} priority={b_meta['priority']} wait_ms={b_meta['wait_ms']} elapsed={b_meta['elapsed']:.2f}s",
)
print("PASS: scheduler enforced Hermes A -> ventilation -> Hermes B on real Qwen")
print("PASS: gateway returned to idle")
PY

printf '\n%s\n' "PASS: stage-4 real-server priority contention validation completed"
