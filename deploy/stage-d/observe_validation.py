#!/usr/bin/env python3
"""Read-only, content-free snapshot for supervised Telegram/media validation."""
import argparse
import json
from urllib.request import urlopen


def snapshot(fetch):
    health = fetch("http://127.0.0.1:11435/health")
    status = fetch("http://127.0.0.1:11435/status")
    comfy = fetch("http://127.0.0.1:8188/queue")
    if health.get("status") != "ok":
        raise ValueError("gateway unhealthy")
    counts = [status.get("active_count"), status.get("queued_count"),
              status.get("resource_leases", {}).get("lease_count")]
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValueError("invalid counters")
    queues = [comfy.get("queue_running"), comfy.get("queue_pending")]
    if any(not isinstance(value, list) for value in queues):
        raise ValueError("invalid ComfyUI queues")
    # No source, prompt, lease token, exception text, raw status or queue entries.
    return {"gateway_healthy": True, "active": counts[0], "queued": counts[1],
            "leases": counts[2], "comfy_running": len(queues[0]),
            "comfy_pending": len(queues[1])}


def fetch(url):
    with urlopen(url, timeout=5) as response:
        return json.load(response)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-idle", action="store_true")
    args = parser.parse_args()
    try:
        result = snapshot(fetch)
        if args.require_idle and any(result[key] for key in
                                    ("active", "queued", "leases", "comfy_running", "comfy_pending")):
            raise ValueError("not idle")
    except Exception:
        raise SystemExit("FAIL: runtime observation failed health/shape/idle gate") from None
    print(json.dumps(result, sort_keys=True))
