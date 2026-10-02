#!/usr/bin/env python3
"""Validate this blocked software snapshot; never authorize evaluation or GPU work.

Only the fixed repository artifact allowlist is opened. Dataset paths and declared
protected hashes inside audit/inventory metadata are never followed or recomputed.
The manifest is an integrity binding, not a signature or an independence certificate.
"""
import hashlib
import json
from pathlib import Path
from protocol_v2 import validate_protocol as protocol_v2

PREFIX = 'deploy/stage-p5/training/p510/'
ARTIFACTS = {
    'methodology': PREFIX + 'METHODOLOGY.md',
    'audit_code': PREFIX + 'audit_dataset_quality.py',
    'audit': PREFIX + 'audit.json',
    'inventory_code': PREFIX + 'inventory_evidence.py',
    'inventory': PREFIX + 'evidence_inventory.json',
    'scorer': 'deploy/stage-p5/benchmark/score_quality_benchmark_v5.py',
    'comparator': PREFIX + 'compare_quality_v5.py',
    'unit_tests': PREFIX + 'test_foundation.py',
    'preflight': PREFIX + 'preflight.py',
    'task': PREFIX + 'CODEX_TASK.md',
    'report': PREFIX + 'CODEX_REPORT.md',
}
ARTIFACTS.update({
    'protocol_v2_' + name.removesuffix('.json'): PREFIX + 'protocol_v2/' + name
    for name in protocol_v2.FILES
})
ARTIFACTS.update({
    'protocol_v2_validator': PREFIX + 'protocol_v2/validate_protocol.py',
    'protocol_v2_acquisition_validator': PREFIX + 'protocol_v2/acquisition.py',
    'protocol_v2_acquisition_tests': PREFIX + 'test_acquisition.py',
    'protocol_v2_acquisition_report': PREFIX + 'protocol_v2/ACQUISITION_REPORT.md',
    'protocol_v2_tests': PREFIX + 'test_protocol_v2.py',
    'protocol_v2_notes': PREFIX + 'protocol_v2/README.md',
    'protocol_v2_simulation_code': PREFIX + 'protocol_v2/simulation_evidence.py',
    'protocol_v2_scorer_v5_1_snapshot': PREFIX + 'protocol_v2/scorer_v5_1_snapshot.py',
    'manifest_builder': PREFIX + 'freeze_snapshot.py',
})
STATUS = 'BLOCKED_INDEPENDENT_EVIDENCE'
BLOCKER = ('Eight-domain executable ground truth PoC passes, but zero scenarios are certified for evaluation. '
           'Independent causal/correctness/exposure review, full 240/240/400 pools, '
           'independent Polish scorer calibration, custodian exclusion and a frozen '
           'execution contract remain missing. Automated tests cannot authorize a run.')
CANDIDATES = {'v3', 'v4_r3', 'p57_step008', 'p58_step008', 'p59_step008'}


def read_fixed(root, relative):
    root = Path(root).resolve()
    path = root / relative
    # Refuse symlinks even if their target has an innocuous name.
    if path.resolve() != path or not path.is_file():
        raise ValueError('missing or redirected snapshot artifact: ' + relative)
    return path.read_bytes()


def validate(root):
    manifest = json.loads(read_fixed(root, PREFIX + 'artifact_manifest.json'))
    if (manifest.get('schema_version') != 1 or manifest.get('status') != STATUS
            or manifest.get('parent') is not None
            or manifest.get('acceptance_authorized') is not False
            or manifest.get('independent_eval') is not None
            or manifest.get('candidate_status') != 'NOT_RUN'):
        raise ValueError('invalid blocked disposition')
    bindings = manifest.get('artifacts', {})
    if not isinstance(bindings, dict) or set(bindings) != set(ARTIFACTS):
        raise ValueError('artifact binding set differs from fixed allowlist')
    payloads = {}
    for name, relative in ARTIFACTS.items():
        binding = bindings[name]
        if not isinstance(binding, dict) or binding.get('path') != relative:
            raise ValueError('invalid artifact path binding: ' + name)
        payload = read_fixed(root, relative)
        if (binding.get('sha256') != hashlib.sha256(payload).hexdigest()
                or type(binding.get('bytes')) is not int or binding['bytes'] != len(payload)):
            raise ValueError('artifact hash/size mismatch: ' + name)
        payloads[name] = payload
    audit = json.loads(payloads['audit'])
    inventory = json.loads(payloads['inventory'])
    if audit.get('status') != 'AUDITED_NOT_CERTIFIED' or audit.get('schema_version') != 2:
        raise ValueError('invalid audit disposition')
    if not audit.get('summaries') or not audit.get('protected_unopened'):
        raise ValueError('missing audit coverage')
    for record in audit['protected_unopened']:
        if record.get('status') != 'NOT_OPENED' or record.get('content_hash') is not None:
            raise ValueError('protected dataset disposition changed')
    if (inventory.get('status') != 'INVENTORIED_NO_COMMON_NEW_EVAL'
            or inventory.get('parent') is not None
            or set(inventory.get('candidates', {})) != CANDIDATES):
        raise ValueError('invalid inventory disposition')
    if any(c.get('tournament_status') != 'NOT_RUN' for c in inventory['candidates'].values()):
        raise ValueError('candidate tournament status changed')
    sealed = inventory.get('sealed_final', {})
    if (sealed.get('content_opened_by_this_task') is not False
            or sealed.get('independence_certified') is not False):
        raise ValueError('sealed final disposition changed')
    evidence = protocol_v2.inspect({name: json.loads(payloads['protocol_v2_' + name.removesuffix('.json')])
                                    for name in protocol_v2.FILES})
    ledger = json.loads(payloads['protocol_v2_exposure_ledger'])
    for field, name in [('audit_sha256', 'audit'), ('inventory_sha256', 'inventory')]:
        if ledger.get(field) != hashlib.sha256(payloads[name]).hexdigest():
            raise ValueError('exposure ledger historical snapshot mismatch')
    return {'status': STATUS, 'evidence': evidence, 'artifact_bindings_valid': True,
            'artifact_count': len(ARTIFACTS), 'candidate_status': 'NOT_RUN',
            'parent': None, 'acceptance_authorized': False, 'blocker': BLOCKER,
            'protected_content_opened': False}


def main():
    try:
        result = validate(Path(__file__).resolve().parents[4])
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result = {'status': 'BLOCKED_ARTIFACT_INTEGRITY', 'artifact_bindings_valid': False,
                  'acceptance_authorized': False, 'error': str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
