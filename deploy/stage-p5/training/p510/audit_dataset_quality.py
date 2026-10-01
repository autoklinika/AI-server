#!/usr/bin/env python3
"""Read public P5 data only. Sealed/test payloads are NEVER opened by this audit."""
from __future__ import annotations
import argparse
import collections
import hashlib
import itertools
import json
import math
import re
from pathlib import Path


def rows(path):
    if protected(path):
        raise ValueError(f'protected content: {path}')
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def prompt(row):
    for key in ('prompt', 'user', 'instruction'):
        if isinstance(row.get(key), str) and row[key].strip():
            return row[key]
    return '\n'.join(m['content'] for m in row.get('messages', [])
                     if m.get('role') == 'user' and isinstance(m.get('content'), str))


def category(row):
    return row.get('category') or row.get('metadata', {}).get('category') or 'unknown'


def normalized(text):
    text = text.lower()
    text = re.sub(r'\b(?:[a-z]+[-_]?)?\d+(?:[.,]\d+)?\b', '<n>', text)
    return ' '.join(re.sub(r'[^a-ząćęłńóśźż<>]+', ' ', text).split())


def sha(path):
    if protected(path):
        raise ValueError(f'protected content cannot be hashed: {path}')
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def protected(path):
    # Conservative: even revealed former finals are not inspected for redesign.
    names = (str(path).lower(), str(Path(path).resolve()).lower())
    # Aliases known from the historical pipeline: these are former final outputs.
    return any(any(x in name for x in ('final', 'golden', 'test', 'sealed',
                                      'p57-regression', 'parent-p57')) for name in names)


def role(path):
    name = str(path).lower()
    if protected(path):
        return 'protected_content_unopened'
    if any(x in name for x in ('holdout', 'regression', 'cases.v1', 'dev')):
        return 'exposed_evaluation_only'
    if any(x in name for x in ('train', 'curriculum_seed', 'curriculum_v2')):
        return 'train_candidate_requires_review'
    return 'quarantine_unknown_role'


def summarize(path):
    data = rows(path)
    ps = [prompt(r) for r in data]
    counts = collections.Counter(normalized(p) for p in ps)
    cats = collections.Counter(category(r) for r in data)
    n = len(data)
    unique = sorted(counts)
    ts = [set(x.split()) for x in unique]
    near_pairs = sum(bool(a and b) and len(a & b) / len(a | b) >= 0.82
                     for a, b in itertools.combinations(ts, 2))
    groups = collections.defaultdict(list)
    for i, r in enumerate(data):
        groups[normalized(ps[i])].append(r.get('case_id', r.get('record_id', str(i))))
    return {
        'path': str(path), 'sha256': sha(path), 'records': n,
        'within_file_near_template_pairs_at_082': near_pairs,
        'semantic_independence': 'NOT_CERTIFIED_REQUIRES_CAUSAL_SCENARIO_REVIEW',
        'categories': dict(sorted(cats.items())), 'missing_prompts': sum(not p.strip() for p in ps),
        'exact_unique_prompts': len(set(ps)), 'exact_duplicate_rows': n - len(set(ps)),
        'normalized_unique_prompts': len(counts), 'normalized_duplicate_rows': n - len(counts),
        'largest_template_share': max(counts.values(), default=0) / n if n else None,
        'template_effective_n': n*n / sum(c*c for c in counts.values()) if n else 0,
        'template_entropy_bits': -sum(c/n * math.log2(c/n) for c in counts.values()) if n else 0,
        'category_templates': {c: len({normalized(prompt(r)) for r in data if category(r) == c}) for c in cats},
        'duplicate_groups': [ids for ids in groups.values() if len(ids) > 1],
        'declared_role': role(path),
    }, data


def audit(paths, threshold=0.82):
    summaries, datasets, sealed = {}, {}, []
    for path in sorted(set(map(Path, paths))):
        if protected(path):
            sealed.append({'path': str(path), 'bytes': path.stat().st_size,
                           'status': 'NOT_OPENED', 'content_hash': None,
                           'allowed_roles': [], 'disposition': 'RESERVED_NOT_CERTIFIED_FOR_ANY_NEW_ROLE'})
            continue
        summaries[str(path)], datasets[str(path)] = summarize(path)
    norms = {p: {normalized(prompt(r)) for r in rs} for p, rs in datasets.items()}
    exact = {p: {prompt(r) for r in rs} for p, rs in datasets.items()}
    token_sets = {s: set(s.split()) for ns in norms.values() for s in ns}
    overlaps = []
    unsafe_train = set()
    for a, b in itertools.combinations(datasets, 2):
        na, nb = norms[a], norms[b]
        near, examples = 0, []
        for x in sorted(na):
            tx = token_sets[x]
            for y in sorted(nb):
                ty = token_sets[y]
                if not tx or not ty or min(len(tx), len(ty)) / max(len(tx), len(ty)) < threshold:
                    continue
                score = len(tx & ty) / len(tx | ty)
                if score >= threshold:
                    near += 1
                    if len(examples) < 3:
                        examples.append({'left_template_sha256': hashlib.sha256(x.encode()).hexdigest(),
                                         'right_template_sha256': hashlib.sha256(y.encode()).hexdigest(),
                                         'jaccard': score})
        if near or exact[a] & exact[b]:
            overlaps.append({'left': a, 'right': b, 'exact_prompt_overlap': len(exact[a] & exact[b]),
                             'normalized_overlap': len(na & nb), 'near_template_pairs': near,
                             'examples': examples})
            for train, other in ((a, b), (b, a)):
                if role(train) == 'train_candidate_requires_review' and role(other) == 'exposed_evaluation_only':
                    unsafe_train.add(train)
    for p, s in summaries.items():
        s['allowed_roles'] = []
        if s['declared_role'] == 'exposed_evaluation_only':
            s['allowed_roles'] = ['historical_diagnostic_evidence']
        s['train_eval_overlap'] = p in unsafe_train
        if s['declared_role'] == 'train_candidate_requires_review':
            s['disposition'] = 'ROW_LEVEL_REVIEW_REQUIRED' if p not in unsafe_train else 'QUARANTINE_CROSS_EVAL_TEMPLATE_OVERLAP'
        else:
            s['disposition'] = 'NOT_UNUSED_NO_SELECTION_OR_FINAL_CLAIM'
    return {'schema_version': 2, 'status': 'AUDITED_NOT_CERTIFIED', 'near_threshold': threshold,
            'limitations': ['Lexical template clustering is a lower bound on dependence, not a semantic independence certificate.',
                           'No train/replay file is automatically approved; row-level provenance and scenario review are required.',
                           'Sealed/final/test content is excluded; cross-split checks against it are deferred until authorized final evaluation.',
                           'Historical exposure is inferred from roles and run artifacts; absence of an output does not prove non-exposure.'],
            'summaries': summaries, 'cross_split_overlap': overlaps, 'protected_unopened': sealed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', action='append', nargs=2, default=[])
    ap.add_argument('--root', type=Path)
    ap.add_argument('--near-threshold', type=float, default=0.82)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    if not 0 < a.near_threshold <= 1:
        ap.error('near-threshold must be in (0,1]')
    paths = [Path(p) for _, p in a.split]
    if a.root:
        paths += list((a.root / 'deploy/stage-p5/training').rglob('*.jsonl'))
        paths += list((a.root / 'benchmarks/electronics_v3_quality_v1').glob('*.jsonl'))
        paths += list((a.root / 'benchmarks/automotive_v1/datasets').glob('*.jsonl'))
    if not paths:
        ap.error('no inputs')
    out = audit(paths, a.near_threshold)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True) + '\n')
    print(json.dumps({'status': out['status'], 'datasets': len(out['summaries']), 'protected': len(out['protected_unopened'])}))

if __name__ == '__main__':
    main()
