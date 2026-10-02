#!/usr/bin/env python3
"""Offline evidence diagnostics. No GPU, payload-path traversal or final unlock API."""
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import compare_quality_v5 as compare
try:
    from protocol_v2 import simulation_evidence as simulation
    from protocol_v2 import acquisition
except ModuleNotFoundError:
    import simulation_evidence as simulation
    import acquisition

FILES = ('protocol.json', 'sources.json', 'families.json', 'exposure_ledger.json',
         'calibration.json', 'precision.json', 'simulation_evidence.json',
         'acquisition_sources.json', 'acquisition_candidates.json')
DOMAINS = {'power_integrity', 'analog_sensor_chain', 'actuator_power_stage',
           'digital_timing_reset', 'vehicle_network', 'pcb_fault_localization',
           'intermittent_environmental', 'ecu_system_isolation'}
ROLES = {'parent_selection', 'selection_dev', 'prefinal', 'sealed_final', 'train', 'calibration', 'quarantine'}
FLOORS = {'diagnostic_model_pass_rate': .90, 'measurement_pass_rate': .90,
          'prediction_pass_rate': .90, 'no_guessing_pass_rate': .98,
          'insufficient_data_abstention_rate': .95, 'sufficient_data_answer_rate': .95,
          'raw_parse_rate': 1., 'final_parse_rate': 1.}


def record_hash(record):
    return hashlib.sha256(json.dumps({k: v for k, v in record.items() if k != 'record_sha256'},
        sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def normalized(text):
    return re.sub(r'\s+', ' ', re.sub(r'\d+(?:\.\d+)?', '#', text.lower())).strip()


def split_guard(rows):
    """Catch declared equivalences and numeric variants; cannot infer causal independence."""
    ids, owners = set(), {}
    for r in rows:
        if not isinstance(r.get('family_id'), str) or not r['family_id'] or r['family_id'] in ids:
            raise ValueError('missing/duplicate family ID')
        ids.add(r['family_id'])
        if r.get('domain') not in DOMAINS or r.get('role') not in ROLES:
            raise ValueError('invalid domain/role')
        for field in ('source_family_id', 'causal_cluster_id', 'topology', 'mechanism', 'intervention', 'prediction'):
            if not isinstance(r.get(field), str) or not r[field].strip():
                raise ValueError('missing causal metadata: ' + field)
        keys = [('source', r['source_family_id']), ('cluster', r['causal_cluster_id']),
                ('causal_fingerprint', normalized(r['topology'] + ' ' + r['mechanism']))]
        keys.extend(('source', source) for source in r.get('source_family_ids', []))
        for key in keys:
            if key in owners and owners[key] != r['role']:
                raise ValueError('cross-role source/causal-family reuse')
            owners[key] = r['role']
    return len(ids)


def prefinal_metrics(report):
    """Fixed numerical checks only. Even all true cannot authorize sealed access."""
    rows = list(compare.validate_report(report).values())
    if any(r.get('category') not in DOMAINS for r in rows):
        raise ValueError('unexpected category')
    metrics, _ = compare.scorer.aggregate(rows)
    checks = {k: metrics[k] is not None and metrics[k] >= floor for k, floor in FLOORS.items()}
    checks['sufficiency_coverage'] = all(sum(r['must_abstain'] is b for r in rows) >= 60 for b in (True, False))
    for domain in sorted(DOMAINS):
        group = [r for r in rows if r['category'] == domain]
        checks[domain + '/count'] = len(group) >= 50
        for dim in compare.DIMENSIONS[:3]:
            checks[domain + '/' + dim] = compare.scorer.wilson(sum(r[dim] for r in group), len(group))['low'] >= .80
    return {'numerical_checks_satisfied': all(checks.values()), 'checks': checks,
            'acceptance_authorized': False, 'status': 'DIAGNOSTIC_ONLY_NO_FINAL_TOKEN'}


def inspect(bundle):
    protocol, sources, families, ledger = (bundle[k] for k in FILES[:4])
    if (protocol.get('schema_version') != 2 or protocol.get('status') != 'BLOCKED_INDEPENDENT_EVIDENCE'
            or protocol.get('acceptance_authorized') is not False):
        raise ValueError('draft cannot be promoted by status edit')
    if set(protocol['domains']) != DOMAINS or protocol['prefinal_floors'] != FLOORS:
        raise ValueError('taxonomy or floors changed')
    if protocol['category_core_wilson_lower'] != .80 or protocol['legacy_max_relative_loss_increase'] != .02:
        raise ValueError('regression/category thresholds changed')
    for role, count in [('parent_selection', 30), ('selection_dev', 30), ('prefinal', 50)]:
        if protocol['roles'][role] != dict(minimum_per_domain=count, minimum_sufficient=60, minimum_insufficient=60):
            raise ValueError('coverage targets changed')
    src = sources['sources']; rows = families['families']
    for r in src + rows:
        if r.get('record_sha256') != record_hash(r):
            raise ValueError('source/family record hash mismatch')
    source_ids = {r['source_id'] for r in src}
    if len(source_ids) != len(src):
        raise ValueError('duplicate source')
    split_guard(rows)
    for r in rows:
        if not r['source_ids'] or not set(r['source_ids']) <= source_ids:
            raise ValueError('missing source binding')
        if r['role'] != 'quarantine' or r.get('correctness_review') is not None or r.get('independence_review') is not None:
            raise ValueError('unverified seed promotion; new externally reviewed snapshot required')
        if set(r['exposure']) != {'v3', 'v4_r3', 'p57_step008', 'p58_step008', 'p59_step008'}:
            raise ValueError('missing candidate exposure')
        if any(v != 'UNKNOWN_FAMILY_EXPOSURE' for v in r['exposure'].values()):
            raise ValueError('unsupported exposure claim')
    if ledger['custodian_attestation'] is not None or any(x['content_opened'] is not False for x in ledger['protected_material']):
        raise ValueError('protected disposition changed')
    sim = bundle['simulation_evidence.json']
    simulation.validate_snapshot(sim)
    declared = protocol.get('simulation_evidence', {})
    if (declared.get('status') != simulation.STATUS
            or declared.get('family_count') != 8
            or declared.get('mathematical_ground_truth_verified') is not True
            or declared.get('p5_exposure_excluded') is not False
            or declared.get('real_world_representativeness_certified') is not False
            or declared.get('eligible_for_parent_selection') is not False
            or declared.get('acceptance_authorized') is not False):
        raise ValueError('simulation evidence disposition changed')
    led_sim = ledger.get('simulation_evidence', {})
    if (led_sim.get('p5_exposure_excluded') is not False
            or led_sim.get('real_world_representativeness_certified') is not False
            or led_sim.get('eligible_roles') != []):
        raise ValueError('simulation exposure ledger overclaims evidence')
    acquired = acquisition.inspect(bundle['acquisition_sources.json'], bundle['acquisition_candidates.json'],
                                   src, rows, DOMAINS, record_hash, split_guard, normalized)
    return {'status': 'BLOCKED_INDEPENDENT_EVIDENCE', 'acceptance_authorized': False,
            'automated_checks_only': True, 'seed_families': len(rows),
            'acquisition': acquired,
            'domains': dict(sorted(Counter(r['domain'] for r in rows).items())),
            'certified_scenarios': 0, 'simulation_verified_quarantine_families': 8, 'parent': None, 'sealed_final': 'UNOPENED',
            'blockers': ['Eight executable mathematical oracles are verified, but P5 exposure and real-world representativeness remain uncertified; all seeds stay quarantined.',
                         'Required 240 parent-selection + 240 selection-dev + 400 prefinal scenarios not acquired.',
                         'Independent Polish scorer calibration and blinded adjudication unavailable.',
                         'Custodian split-exclusion attestation unavailable.',
                         'Base/tokenizer/generation bindings, checkpoint multiplicity and live launch gate pending.']}


def load_bundle():
    bundle = {}
    for name in FILES:
        path = HERE / name
        if path.resolve() != path or not path.is_file():
            raise ValueError('missing/redirected protocol artifact')
        bundle[name] = json.loads(path.read_text())
    return bundle


def main():
    try:
        result = inspect(load_bundle())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = {'status': 'BLOCKED_ARTIFACT_INTEGRITY', 'acceptance_authorized': False, 'error': str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
