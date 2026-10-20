#!/usr/bin/env python3
"""Read-only host audit for the Vision candidate. Never launches GPU or deploys.

No --apply or grant override exists. A CPU contract cannot approve a GPU pilot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = Path('/srv/ai-data/evaluation/vision-pcb-envs')
CHECKPOINT = MODEL_ROOT / ('anomalyvfm-radio-pilot-20261016/hf_cache/'
    'models--MaticFuc--anomalyvfm_radio/snapshots/'
    '17654e763c8fae5ae1c44e2ec421a427783d6196/model.safetensors')
CHECKPOINT_SHA = '50a219ba436ed656ad3c0405f9e81df8ad00b2e715c98be66d7e2edb62a83a37'
RUNTIME = MODEL_ROOT / 'anomalyvfm-radio-rocm714-py311/bin/python'


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            result.update(chunk)
    return result.hexdigest()


def read_status():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:11435/status', timeout=5) as response:
        return json.load(response)


def host_facts(status):
    """Only allowlisted facts; no lease IDs, tokens, arbitrary worker output."""
    gpu = status.get('gpu_residency', {})
    engines = status.get('resource_manager', {}).get('engines', [])
    vision = next((row for row in engines if row.get('id') == 'vision'), {})
    return {
        'gateway_idle': (status.get('active_count') == 0
                         and status.get('queued_count') == 0
                         and status.get('admission_blocked') is False
                         and status.get('resource_leases', {}).get('lease_count') == 0
                         and gpu.get('recovery_required') is False
                         and status.get('resource_manager', {}).get('state') == 'IDLE'),
        'gpu_reuse_safe': status.get('resource_evidence', {}).get('GPU_REUSE_SAFE', {}).get('status', 'UNKNOWN'),
        'production_vision_execution_available': vision.get('execution_available') is True,
    }


def audit():
    result = {
        'schema': 1, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'gpu_pilot': 'BLOCKED', 'production': 'BLOCKED',
        'gpu_inference': 'NOT_RUN', 'inference_host': 'harrypotter-AI-Series',
        'capture_host': 'vision', 'automatic_n1_grant': 'NOT_ADMITTED',
        'reasons': ['NO_ADMITTED_LOCAL_RADIO_EXECUTOR',
                    'NO_VERIFIED_VISION_GPU_HANDOFF_OR_CLEANUP',
                    'INCOMPLETE_INTEGRATION_MUST_NOT_BE_DEPLOYED'],
    }
    try:
        result.update(host_facts(read_status()))
        result['radio_runtime_present'] = RUNTIME.is_file()
        result['radio_checkpoint_sha256'] = digest(CHECKPOINT)
        result['radio_checkpoint_verified'] = result['radio_checkpoint_sha256'] == CHECKPOINT_SHA
        if not result['gateway_idle']:
            result['reasons'].append('GATEWAY_BUSY_OR_UNCERTAIN')
        if not result['radio_runtime_present'] or not result['radio_checkpoint_verified']:
            result['reasons'].append('RADIO_RUNTIME_OR_CHECKPOINT_INVALID')
        # Validate the ACTIVE production rollback, without switching services or
        # claiming that the new integration has a tested deployment/rollback.
        sys.path.insert(0, str(ROOT / 'tools'))
        import deploy_rm_gateway_backport_v1 as deployment
        deployment.installed_overlay_ok()
        result['existing_overlay_and_rollback_identity'] = 'READ_ONLY_VERIFIED'
        result['candidate_deployment_rollback'] = 'NOT_TESTED_NOT_INSTALLED'
    except Exception as error:
        result['audit_error'] = type(error).__name__
        result['reasons'].append('HOST_AUDIT_INCOMPLETE')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit()
    content = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.output:
        with args.output.open('x') as stream:
            stream.write(content)
    print(content, end='')
    return 2  # This candidate intentionally has no admitted GPU executor.


if __name__ == '__main__':
    raise SystemExit(main())
