#!/usr/bin/env python3
"""Bounded local readiness check for systemd; never submit GPU work."""
import argparse
import json
import time
import urllib.request


def fetch(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=3) as response:
        return json.load(response)


def ready(target):
    if target == 'gateway':
        value = fetch('http://127.0.0.1:11435/health')
        return (value.get('status') == 'ok'
                and value.get('scheduler', {}).get('admission_blocked') is False
                and value.get('gpu_residency', {}).get('recovery_required') is False)
    value = fetch('http://127.0.0.1:8188/ai-platform/residency')
    return (type(value.get('schema_version')) is int and value['schema_version'] == 1
            and all(type(value.get(key)) is int and value[key] == 0
                    for key in ('loaded_models', 'queue_running', 'queue_pending'))
            and value.get('cleanup_pending') is False)


def wait(target, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if ready(target):
                print(target.upper() + '_READY=PASS', flush=True)
                return
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        time.sleep(.5)
    raise RuntimeError(target + ' readiness timeout')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', choices=('comfyui', 'gateway'))
    args = parser.parse_args()
    wait(args.target, 120 if args.target == 'comfyui' else 180)
