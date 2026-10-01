#!/usr/bin/env python3
"""Paired evidence report, not a launch/prefinal gate. Fixed thresholds, no CLI overrides."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import random
from pathlib import Path

SCORER_PATH = Path(__file__).resolve().parents[2] / 'benchmark/score_quality_benchmark_v5.py'
spec = importlib.util.spec_from_file_location('p510_scorer', SCORER_PATH)
scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorer)
DIMENSIONS = scorer.DIMENSIONS


def case_score(row):
    return sum(row[k] for k in DIMENSIONS)/len(DIMENSIONS)


def bootstrap_ci(values, resamples=5000, seed=20261001, alpha=0.05):
    if not values or resamples < 1000 or not 0 < alpha < 1:
        raise ValueError('nonempty paired values and >=1000 resamples required')
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n))/n for _ in range(resamples))
    return {'mean': sum(values)/n, 'low': means[int(alpha/2*(resamples-1))],
            'high': means[int((1-alpha/2)*(resamples-1))], 'n': n, 'alpha': alpha}


def validate_report(report):
    if report.get('scorer') != scorer.SCORER or report.get('status') != 'SCORED':
        raise ValueError('requires current scorer with no unresolved review')
    rows = scorer.indexed(report['details'])
    for row in rows.values():
        if any(type(row.get(k)) is not bool for k in (*DIMENSIONS, 'must_abstain', 'raw_parse_ok', 'final_parse_ok')):
            raise ValueError('nonboolean case score')
        if row.get('review_required') is not False:
            raise ValueError('unresolved review')
    ids = [r.get('scenario_id') for r in rows.values()]
    if any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('missing/repeated scenarios')
    if report['metrics'] != scorer.aggregate(list(rows.values()))[0]:
        raise ValueError('aggregate does not match per-case scores')
    binding = report.get('bindings', {})
    for key in ('dataset_sha256', 'scorer_sha256', 'results_sha256'):
        value = binding.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('missing/invalid digest binding')
    if binding['scorer_sha256'] != scorer.digest(SCORER_PATH):
        raise ValueError('scorer implementation changed')
    return rows


def compare(parent, candidate):
    pd, cd = validate_report(parent), validate_report(candidate)
    if pd.keys() != cd.keys():
        raise ValueError('case sets differ')
    for key in ('dataset_sha256', 'scorer_sha256'):
        if parent['bindings'][key] != candidate['bindings'][key]:
            raise ValueError('dataset/scorer binding differs')
    for key in pd:
        for field in ('scenario_id', 'category', 'must_abstain'):
            if pd[key][field] != cd[key][field]:
                raise ValueError('case metadata differs')
    # Five candidates -> ten pairwise comparisons; six statistics per pair.
    # Simultaneous conservative family-wise intervals; no winner from point noise.
    alpha = .05 / (10 * 6)
    ids = sorted(pd)
    paired = bootstrap_ci([case_score(cd[k])-case_score(pd[k]) for k in ids], resamples=20000, alpha=alpha)
    dimensions = {d: bootstrap_ci([int(cd[k][d])-int(pd[k][d]) for k in ids],
                                  resamples=20000, alpha=alpha) for d in DIMENSIONS}
    cm = candidate['metrics']
    checks = {'at_least_240_scenarios': len(ids) >= 240,
              'raw_and_final_parse': cm['raw_parse_rate'] == cm['final_parse_rate'] == 1.,
              'no_guessing': cm['no_guessing_pass_rate'] >= .98,
              'abstention': cm['insufficient_data_abstention_rate'] is not None and cm['insufficient_data_abstention_rate'] >= .95,
              'sufficient_answers': cm['sufficient_data_answer_rate'] is not None and cm['sufficient_data_answer_rate'] >= .95,
              'paired_improvement': paired['low'] > 0,
              'dimension_noninferiority': all(x['low'] >= -.02 for x in dimensions.values())}
    return {'status': 'EVIDENCE_FAVORS_CANDIDATE' if all(checks.values()) else 'INCONCLUSIVE_OR_REGRESSED',
            'acceptance_authorized': False, 'checks': checks,
            'paired_composite_delta': paired, 'paired_dimension_deltas': dimensions,
            'bindings': {'parent': parent['bindings'], 'candidate': candidate['bindings']},
            'limitations': ['Conditional on externally reviewed independent scenarios; IDs are not proof.',
                           'Bootstrap intervals are approximate, including degenerate all-tie samples.',
                           'Legacy regression, provenance, calibration and preflight remain separate mandatory checks.']}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ('parent', 'candidate', 'output'):
        ap.add_argument('--'+key, required=True)
    args = ap.parse_args()
    out = compare(json.loads(Path(args.parent).read_text()), json.loads(Path(args.candidate).read_text()))
    Path(args.output).write_text(json.dumps(out, indent=2, allow_nan=False)+'\n')
    print(out['status'])
    # An evidence report is never a PASS token for a runner.
    raise SystemExit(2)


if __name__ == '__main__':
    main()
