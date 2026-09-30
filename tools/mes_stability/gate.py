#!/usr/bin/env python3
"""Evaluate evidence only; never resumes training or promotes adapters."""
import argparse
import json
from pathlib import Path


def evaluate(results, minimum_seconds=3600, repeats=3):
    reasons = []
    if len(results) < repeats:
        reasons.append('insufficient independent process repetitions')
    identities = {(r.get('variant'), r.get('image_id'), r.get('git', {}).get('sha'),
                   r.get('kernel'), r.get('profile')) for r in results}
    if len(identities) != 1:
        reasons.append('configuration/build/profile mismatch')
    names = [r.get('container_name') for r in results]
    if len(set(names)) != len(names):
        reasons.append('duplicate run evidence')
    intervals = sorted((r.get('started_at_unix', 0), r.get('ended_at_unix', 0)) for r in results)
    if any(a[1] > b[0] for a,b in zip(intervals, intervals[1:])):
        reasons.append('overlapping runs')
    for r in results:
        if r.get('status') != 'PASS_RUN_ONLY' or r.get('workload_exit_code') != 0 or not r.get('container_stopped'):
            reasons.append('failed/incomplete workload')
        if any(r.get('error_counts', {'missing': 1}).values()):
            reasons.append('kernel errors')
        if r.get('profile') != 'qwen':
            reasons.append('synthetic microstress alone cannot pass Qwen stability gate')
        if r.get('measured_workload_s', 0) < minimum_seconds:
            reasons.append('duration shorter than required full P5.6 window')
        if r.get('git', {}).get('dirty', True):
            reasons.append('uncommitted code')
        if r.get('host_regression_free') is not True:
            reasons.append('host postflight missing or regressed')
        if r.get('peak_vram_bytes', 0) < 52 * 1024**3:
            reasons.append('load not representative of P5.6 memory footprint')
    return {'gate': 'FAIL_OR_INCOMPLETE' if reasons else 'PASS',
            'reasons': sorted(set(reasons)), 'minimum_seconds_each': minimum_seconds,
            'required_repeats': repeats, 'automatic_training_resume': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('results', nargs='+', type=Path)
    p.add_argument('--minimum-seconds', type=int, default=3600)
    a = p.parse_args()
    if a.minimum_seconds < 3600:
        p.error('minimum 3600 seconds; increase if full P5.6 estimate is longer')
    result = evaluate([json.loads(f.read_text()) for f in a.results], a.minimum_seconds)
    print(json.dumps(result, indent=2))
    return 0 if result['gate'] == 'PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
