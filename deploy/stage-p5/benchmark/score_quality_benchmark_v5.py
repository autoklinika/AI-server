#!/usr/bin/env python3
"""Experimental, case-specific rubric scorer. Never authorizes training or final access.

Rules express complete causal propositions, measurement setup and predicted branches.
Equivalent phrasings are explicit alternatives. Unmatched text requires review; embedding
similarity and category keywords cannot override a missing/contradicted proposition.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
from pathlib import Path

FIELDS = ('diagnostic_model', 'discriminating_measurement', 'predicted_result')
DIMENSIONS = ('diagnostic_model_pass', 'measurement_pass', 'prediction_pass',
              'no_guessing_pass', 'abstain_ok')
SCORER = 'case-rubric-v5.1-experimental'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_public(path):
    names = (str(path).lower(), str(Path(path).resolve()).lower())
    if any(any(t in n for t in ('final', 'golden', 'sealed', 'test', 'p57-regression', 'parent-p57'))
           for n in names):
        raise ValueError('protected content is not accepted by the P510 development scorer')
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def wilson(successes, total, z=1.959963984540054):
    if total == 0:
        return {'score': None, 'low': 0.0, 'high': 1.0, 'n': 0}
    if not 0 <= successes <= total:
        raise ValueError('invalid binomial counts')
    p = successes / total
    den = 1 + z*z/total
    center = (p + z*z/(2*total))/den
    radius = z * math.sqrt((p*(1-p)+z*z/(4*total))/total)/den
    return {'score': p, 'low': max(0., center-radius), 'high': min(1., center+radius), 'n': total}


def indexed(rows):
    out = {}
    for row in rows:
        key = row.get('case_id')
        if not isinstance(key, str) or not key or key in out:
            raise ValueError('missing or duplicate case_id')
        out[key] = row
    if not out:
        raise ValueError('empty dataset/results')
    return out


def validate_rule(rule):
    # Every group is a required proposition; patterns within a group are alternatives.
    if not isinstance(rule, dict) or not rule.get('all_of') or 'none_of' not in rule:
        raise ValueError('rubric requires all_of and none_of')
    if not isinstance(rule['all_of'], list) or not isinstance(rule['none_of'], list):
        raise ValueError('invalid rubric lists')
    for group in rule['all_of']:
        if not isinstance(group, list) or not group:
            raise ValueError('empty proposition')
    for pattern in [p for group in rule['all_of'] for p in group] + rule['none_of']:
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError('empty rubric pattern')
        compiled = re.compile(pattern, re.I)
        if compiled.search(''):
            raise ValueError('pattern matches empty text')


def match_rule(text, rule):
    validate_rule(rule)
    text = ' '.join(text.lower().split())
    contradicted = any(re.search(p, text, re.I) for p in rule['none_of'])
    matched = all(any(re.search(p, text, re.I) for p in group) for group in rule['all_of'])
    return matched and not contradicted, contradicted


def score_case(case, result):
    rubric = case.get('rubric', {})
    if type(case.get('must_abstain')) is not bool:
        raise ValueError('must_abstain must be boolean')
    for field in (*FIELDS, 'no_guessing'):
        validate_rule(rubric.get(field))
    parsed = result.get('parsed')
    valid = (isinstance(parsed, dict) and type(parsed.get('abstain')) is bool
             and all(isinstance(parsed.get(f), str) and parsed[f].strip() for f in FIELDS))
    row = {k: case[k] for k in ('case_id', 'scenario_id', 'category')}
    row.update(raw_parse_ok=result.get('raw_parse_ok') is True, final_parse_ok=valid,
               must_abstain=case['must_abstain'], review_required=False)
    row.update({key: False for key in DIMENSIONS})
    if not valid:
        return row
    for field, dim in zip(FIELDS, DIMENSIONS):
        passed, contradicted = match_rule(parsed[field], rubric[field])
        row[dim] = passed
        row['review_required'] |= not passed and not contradicted
    passed, contradicted = match_rule(' '.join(parsed[f] for f in FIELDS), rubric['no_guessing'])
    row['no_guessing_pass'] = passed and (not case['must_abstain'] or parsed['abstain'])
    row['review_required'] |= not passed and not contradicted
    row['abstain_ok'] = parsed['abstain'] == case['must_abstain']
    return row


def aggregate(details):
    fields = {'raw_parse_rate': 'raw_parse_ok', 'final_parse_rate': 'final_parse_ok',
              'diagnostic_model_pass_rate': DIMENSIONS[0], 'measurement_pass_rate': DIMENSIONS[1],
              'prediction_pass_rate': DIMENSIONS[2], 'no_guessing_pass_rate': DIMENSIONS[3],
              'abstention_accuracy': DIMENSIONS[4]}
    cis = {k: wilson(sum(r[f] for r in details), len(details)) for k, f in fields.items()}
    for name, must in (('insufficient_data_abstention_rate', True), ('sufficient_data_answer_rate', False)):
        subset = [r for r in details if r['must_abstain'] is must]
        cis[name] = wilson(sum(r['abstain_ok'] for r in subset), len(subset))
    metrics = {k: v['score'] for k, v in cis.items()}
    metrics['records'] = len(details)
    metrics['selection_score'] = sum(sum(r[k] for k in DIMENSIONS)/5 for r in details)/len(details)
    return metrics, cis


def score(cases, results):
    cs, rs = indexed(cases), indexed(results)
    if cs.keys() != rs.keys():
        raise ValueError('results must cover every case exactly once; no extras')
    scenarios = [c.get('scenario_id') for c in cases]
    if any(not isinstance(s, str) or not s for s in scenarios) or len(set(scenarios)) != len(scenarios):
        raise ValueError('one row per independent scenario required; IDs alone do not certify independence')
    if any(not isinstance(c.get('category'), str) or not c['category'] for c in cases):
        raise ValueError('missing category')
    details = [score_case(cs[k], rs[k]) for k in sorted(cs)]
    metrics, cis = aggregate(details)
    categories = {c: aggregate([r for r in details if r['category'] == c])
                  for c in sorted({r['category'] for r in details})}
    return {'status': 'SCORED_REVIEW_REQUIRED' if any(r['review_required'] for r in details) else 'SCORED',
            'scorer': SCORER, 'acceptance_authorized': False,
            'metrics': metrics, 'metric_intervals_95': cis,
            'category_metrics': {c: v[0] for c, v in categories.items()},
            'category_intervals_95': {c: v[1] for c, v in categories.items()}, 'details': details}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('dataset', 'results', 'output'):
        ap.add_argument('--'+name, required=True)
    a = ap.parse_args()
    out = score(read_public(a.dataset), read_public(a.results))
    out['bindings'] = {'dataset_sha256': digest(a.dataset), 'results_sha256': digest(a.results),
                       'scorer_sha256': digest(__file__)}
    Path(a.output).write_text(json.dumps(out, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    print(json.dumps({'status': out['status'], 'metrics': out['metrics']}))


if __name__ == '__main__':
    main()
