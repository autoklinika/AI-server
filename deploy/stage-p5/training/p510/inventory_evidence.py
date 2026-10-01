#!/usr/bin/env python3
"""Inventory historical artifacts without reading protected datasets or raw final answers."""
import argparse
import json
from pathlib import Path
from audit_dataset_quality import sha, protected

CANDIDATES = {
    'v3': 'adapters/electronics-foundation-v3/current',
    'v4_r3': 'checkpoints/electronics-v4-measurement-r3-20261001',
    'p57_step008': 'checkpoints/p57-p57-seed1b-20261001/step-008',
    'p58_step008': 'checkpoints/p58-p58-seed1-20261001/step-008',
    'p59_step008': 'checkpoints/p59-p59-seed1-20261001/step-008',
}

def inventory(repo, data):
    state_path = data / 'p57/p57-seed1b-20261001/state.json'
    state = json.loads(state_path.read_text())
    eligible = [r for r in state['history'] if r['eligible']]
    best = max(eligible, key=lambda r: (r['score'], -r['index']))
    if best['checkpoint'] != state['best_checkpoint']:
        raise ValueError('P57 state does not match eligible history')
    if best['checkpoint'] != str(data / CANDIDATES['p57_step008']):
        raise ValueError('P57 candidate changed; review required')
    candidates = {}
    for name, rel in CANDIDATES.items():
        path = (data / rel).resolve()
        files = {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size}
                 for p in path.glob('adapter*') if p.is_file()}
        config = json.loads((path / 'adapter_config.json').read_text())
        candidates[name] = {'requested_path': str(data / rel), 'resolved_path': str(path),
                            'files': files, 'config': config, 'tournament_status': 'NOT_RUN'}
    artifacts = []
    excluded = []
    paths = list((repo / 'deploy/stage-p5').rglob('*.json'))
    paths += list((repo / 'benchmarks/electronics_v3_quality_v1').glob('*.json'))
    for directory in ('evals', 'benchmarks', 'p57', 'p58', 'p59'):
        paths += list((data / directory).rglob('*.json'))
    for p in sorted(set(paths)):
        if 'p510' in p.parts:
            continue
        if protected(p):
            excluded.append({'path': str(p), 'status': 'NOT_OPENED'})
            continue
        # Score files may include per-case answer text: retain only aggregate fields.
        d = json.loads(p.read_text())
        # Only summary artifacts; no jsonl payloads, no raw/reference/details text.
        entry = {'path': str(p), 'sha256': sha(p)}
        if isinstance(d, dict):
            keys = ('status', 'checks', 'metrics', 'category_metrics', 'token_weighted_loss',
                    'records', 'best_checkpoint', 'best_index', 'best_score', 'stop_reason',
                    'final_open_allowed', 'relative_regression_vs_parent')
            entry['summary'] = {k: d[k] for k in keys if k in d}
            if 'manifest' in p.name:
                entry['manifest'] = d
        artifacts.append(entry)
    code = []
    for p in sorted((repo / 'deploy/stage-p5').rglob('*')):
        if p.suffix in ('.py', '.sh') and 'p510' not in p.parts and not protected(p):
            code.append({'path': str(p), 'sha256': sha(p)})
    p58 = json.loads((repo / 'deploy/stage-p5/training/p58/p58_manifest.json').read_text())
    p59 = json.loads((repo / 'deploy/stage-p5/training/p59/p59_manifest.json').read_text())
    return {'schema_version': 1, 'candidates': candidates, 'historical_artifacts': artifacts,
            'historical_code_inventory': code, 'protected_artifacts_unopened': excluded,
            'p57_selection_evidence': {'path': str(state_path), 'sha256': sha(state_path),
                                       'best_checkpoint': best['checkpoint'], 'score': best['score'],
                                       'scope': 'historical dev eligibility only; not new parent selection'},
            'sealed_final': {'path': 'deploy/stage-p5/training/p58/p58_final_v1.jsonl',
                             'declared_sha256': p58['final_sha256'], 'declared_records': p58['final_records'],
                             'p59_reuses_same_final': p58['final_sha256'] == p59['p58_final_sha256'],
                             'content_opened_by_this_task': False,
                             'p58_results_exist': (data / 'benchmarks/p58-seed1-20261001/final/results.jsonl').exists(),
                             'p59_results_exist': (data / 'benchmarks/p59-seed1-20261001/final/results.jsonl').exists(),
                             'independence_certified': False},
            'parent': None, 'status': 'INVENTORIED_NO_COMMON_NEW_EVAL'}

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', type=Path, default=Path('.'))
    ap.add_argument('--data', type=Path, default=Path('/srv/ai-data/training/p5'))
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output.write_text(json.dumps(inventory(a.repo, a.data), indent=2, ensure_ascii=False, sort_keys=True) + '\n')
