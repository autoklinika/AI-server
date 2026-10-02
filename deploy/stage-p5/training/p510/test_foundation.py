"""Self-authored software calibration fixtures, never model evaluation/training data."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audit_dataset_quality as audit
import compare_quality_v5 as compare
import preflight
scorer = compare.scorer


def fixture():
    # A deliberately tiny artificial calibration case, not independent evidence.
    case = {'case_id': 'calibration-only', 'scenario_id': 'fixture-only', 'category': 'power_integrity',
            'must_abstain': False, 'rubric': {
                'diagnostic_model': {'all_of': [[r'supply impedance or load fault', r'load fault versus supply impedance']],
                                     'none_of': [r'not (?:a )?supply impedance', r'regulator is certainly defective']},
                'discriminating_measurement': {'all_of': [[r'measure input and output under load',
                                                          r'under load, probe both input and output']],
                                               'none_of': [r'do not measure', r'without load']},
                'predicted_result': {'all_of': [[r'if input drops, suspect upstream', r'upstream is implicated if input falls'],
                                              [r'if input stays stable, investigate load', r'stable input points to the load']],
                                     'none_of': [r'if input drops, suspect only downstream']},
                'no_guessing': {'all_of': [[r'suspect|investigate|implicated|points to']],
                                'none_of': [r'certainly|definitely|replace now|na pewno|wymień']}}}
    result = {'case_id': case['case_id'], 'raw_parse_ok': True, 'parsed': {
        'diagnostic_model': 'Supply impedance or load fault.',
        'discriminating_measurement': 'Measure input and output under load.',
        'predicted_result': 'If input drops, suspect upstream; if input stays stable, investigate load.',
        'abstain': False}}
    return case, result


def report():
    c, r = fixture()
    out = scorer.score([c], [r])
    out['bindings'] = {'dataset_sha256': 'a'*64, 'results_sha256': 'b'*64,
                       'scorer_sha256': scorer.digest(compare.SCORER_PATH)}
    return out


class ScorerTests(unittest.TestCase):
    def test_positive(self):
        c, r = fixture()
        self.assertTrue(all(scorer.score_case(c, r)[k] for k in scorer.DIMENSIONS))

    def test_equivalent_phrasing(self):
        c, r = fixture()
        r['parsed'].update(diagnostic_model='Load fault versus supply impedance.',
                           discriminating_measurement='Under load, probe both input and output.',
                           predicted_result='Upstream is implicated if input falls; stable input points to the load.')
        self.assertTrue(all(scorer.score_case(c, r)[k] for k in scorer.DIMENSIONS))

    def test_wrong_causal_branch(self):
        c, r = fixture()
        r['parsed']['predicted_result'] = 'If input drops, suspect only downstream.'
        self.assertFalse(scorer.score_case(c, r)['prediction_pass'])

    def test_contradiction_overrides_positive(self):
        c, r = fixture()
        r['parsed']['predicted_result'] += ' If input drops, suspect only downstream.'
        self.assertFalse(scorer.score_case(c, r)['prediction_pass'])

    def test_keyword_salad_requires_review(self):
        c, r = fixture()
        r['parsed']['diagnostic_model'] = 'Supply load regulator driver input output.'
        row = scorer.score_case(c, r)
        self.assertFalse(row['diagnostic_model_pass'])
        self.assertTrue(row['review_required'])

    def test_negation(self):
        c, r = fixture()
        r['parsed']['discriminating_measurement'] = 'Do not measure input and output under load.'
        self.assertFalse(scorer.score_case(c, r)['measurement_pass'])

    def test_guess_in_any_field(self):
        for f in scorer.FIELDS:
            c, r = fixture()
            r['parsed'][f] += ' Replace now.'
            self.assertFalse(scorer.score_case(c, r)['no_guessing_pass'])

    def test_schema_strict_boolean(self):
        c, r = fixture()
        r['parsed']['abstain'] = 'false'
        self.assertFalse(scorer.score_case(c, r)['final_parse_ok'])

    def test_schema_missing_field(self):
        c, r = fixture()
        del r['parsed']['predicted_result']
        self.assertFalse(scorer.score_case(c, r)['final_parse_ok'])

    def test_over_abstention(self):
        c, r = fixture()
        r['parsed']['abstain'] = True
        self.assertFalse(scorer.score_case(c, r)['abstain_ok'])

    def test_insufficient_evidence_abstention(self):
        c, r = fixture()
        c['must_abstain'] = True
        self.assertFalse(scorer.score_case(c, r)['no_guessing_pass'])
        r['parsed']['abstain'] = True
        self.assertTrue(scorer.score_case(c, r)['abstain_ok'])

    def test_missing_rubric_fails(self):
        c, r = fixture()
        del c['rubric']
        with self.assertRaises(ValueError): scorer.score_case(c, r)

    def test_empty_rule_fails(self):
        with self.assertRaises(ValueError): scorer.validate_rule({'all_of': [['.*']], 'none_of': []})

    def test_duplicate_case_fails(self):
        c, r = fixture()
        with self.assertRaises(ValueError): scorer.score([c,c], [r])
        with self.assertRaises(ValueError): scorer.score([c], [r,r])

    def test_missing_extra_cases_fail(self):
        c, r = fixture()
        r['case_id'] = 'extra'
        with self.assertRaises(ValueError): scorer.score([c], [r])

    def test_repeated_scenario_fails(self):
        c, r = fixture(); c2, r2 = copy.deepcopy(c), copy.deepcopy(r)
        c2['case_id'] = r2['case_id'] = 'second'
        with self.assertRaises(ValueError): scorer.score([c,c2], [r,r2])

    def test_empty_results_fail(self):
        c, _ = fixture()
        with self.assertRaises(ValueError): scorer.score([c], [])

    def test_absent_abstention_not_perfect(self):
        self.assertIsNone(report()['metrics']['insufficient_data_abstention_rate'])

    def test_wilson_boundary(self):
        self.assertAlmostEqual(scorer.wilson(5, 5)['low'], .5655, places=3)
        self.assertIsNone(scorer.wilson(0, 0)['score'])


class ComparisonTests(unittest.TestCase):
    def test_duplicate_details(self):
        r = report(); r['details'] *= 2
        with self.assertRaises(ValueError): compare.validate_report(r)

    def test_forged_summary(self):
        r = report(); r['metrics']['records'] = 1000
        with self.assertRaises(ValueError): compare.validate_report(r)

    def test_binding_mismatch(self):
        p, c = report(), report(); c['bindings']['dataset_sha256'] = 'f'*64
        with self.assertRaises(ValueError): compare.compare(p,c)

    def test_review_rejected(self):
        r = report(); r['details'][0]['review_required'] = True
        with self.assertRaises(ValueError): compare.validate_report(r)

    def test_no_pass_for_tie_or_tiny_sample(self):
        out = compare.compare(report(), report())
        self.assertEqual(out['status'], 'INCONCLUSIVE_OR_REGRESSED')
        self.assertFalse(out['acceptance_authorized'])

    def test_bootstrap_reproducible(self):
        self.assertEqual(compare.bootstrap_ci([0, 1, -1]), compare.bootstrap_ci([0, 1, -1]))
        with self.assertRaises(ValueError): compare.bootstrap_ci([])


class AuditTests(unittest.TestCase):
    def test_numeric_variants_not_independent(self):
        self.assertEqual(audit.normalized('TP123 has 12 V at 40 C'), audit.normalized('TP999 has 15 V at 80 C'))

    def test_protected_never_opened(self):
        with tempfile.TemporaryDirectory(prefix='p510-') as tmp:
            p = Path(tmp)/'sealed.jsonl'; p.write_text('not json')
            with patch.object(Path, 'open', side_effect=AssertionError('opened protected payload')):
                out = audit.audit([p])
            self.assertEqual(out['protected_unopened'][0]['status'], 'NOT_OPENED')
            with self.assertRaises(ValueError): audit.sha(p)
            with self.assertRaises(ValueError): audit.rows(p)
            with self.assertRaises(ValueError): scorer.read_public(p)

    def test_symlink_cannot_bypass_protection(self):
        with tempfile.TemporaryDirectory(prefix='p510-') as tmp:
            p = Path(tmp)/'golden.jsonl'; p.write_text('not json')
            q = Path(tmp)/'dev.jsonl'; q.symlink_to(p)
            with self.assertRaises(ValueError): audit.rows(q)
            with self.assertRaises(ValueError): scorer.read_public(q)

    def test_former_final_alias_protected(self):
        self.assertTrue(audit.protected('/evidence/p57-regression/results.jsonl'))
        self.assertTrue(audit.protected('/evidence/parent-p57-score-v4.json'))

    def test_overlap_quarantines_train(self):
        with tempfile.TemporaryDirectory(prefix='p510-') as tmp:
            paths = [Path(tmp)/n for n in ('train.jsonl', 'dev.jsonl')]
            for p in paths: p.write_text(json.dumps({'prompt': 'Measure TP1 voltage 12 V', 'category': 'power'})+'\n')
            out = audit.audit(paths)
            self.assertTrue(out['summaries'][str(paths[0])]['train_eval_overlap'])
            self.assertEqual(out['summaries'][str(paths[0])]['allowed_roles'], [])


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='p510-bindings-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        payloads = {name: b'software fixture' for name in preflight.ARTIFACTS}
        payloads['audit'] = json.dumps({'schema_version': 2, 'status': 'AUDITED_NOT_CERTIFIED',
            'summaries': {'public': {}}, 'protected_unopened': [
                {'path': '/never/open/sealed.jsonl', 'status': 'NOT_OPENED', 'content_hash': None}]}).encode()
        payloads['inventory'] = json.dumps({'status': 'INVENTORIED_NO_COMMON_NEW_EVAL',
            'parent': None, 'candidates': {k: {'tournament_status': 'NOT_RUN'} for k in preflight.CANDIDATES},
            'sealed_final': {'content_opened_by_this_task': False, 'independence_certified': False}}).encode()
        for name in preflight.protocol_v2.FILES:
            payloads['protocol_v2_' + name.removesuffix('.json')] = (Path(__file__).parent / 'protocol_v2' / name).read_bytes()
        ledger = json.loads(payloads['protocol_v2_exposure_ledger'])
        ledger['audit_sha256'] = hashlib.sha256(payloads['audit']).hexdigest()
        ledger['inventory_sha256'] = hashlib.sha256(payloads['inventory']).hexdigest()
        payloads['protocol_v2_exposure_ledger'] = json.dumps(ledger).encode()
        self.manifest = {'schema_version': 1, 'status': preflight.STATUS, 'parent': None,
            'acceptance_authorized': False, 'independent_eval': None, 'candidate_status': 'NOT_RUN',
            'artifacts': {}}
        for name, rel in preflight.ARTIFACTS.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(payloads[name])
            self.manifest['artifacts'][name] = {'path': rel, 'bytes': len(payloads[name]),
                'sha256': hashlib.sha256(payloads[name]).hexdigest()}
        self.write_manifest()

    def write_manifest(self):
        (self.root / preflight.PREFIX / 'artifact_manifest.json').write_text(json.dumps(self.manifest))

    def test_valid_snapshot_still_blocked(self):
        result = preflight.validate(self.root)
        self.assertTrue(result['artifact_bindings_valid'])
        self.assertFalse(result['acceptance_authorized'])
        self.assertEqual(result['status'], preflight.STATUS)
        self.assertIsNone(result['parent'])

    def test_tamper_rejected(self):
        (self.root / preflight.ARTIFACTS['scorer']).write_text('changed')
        with self.assertRaisesRegex(ValueError, 'hash/size mismatch'):
            preflight.validate(self.root)

    def test_missing_binding_rejected(self):
        del self.manifest['artifacts']['scorer']
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'allowlist'):
            preflight.validate(self.root)

    def test_protected_path_binding_never_followed(self):
        self.manifest['artifacts']['scorer']['path'] = '/never/open/sealed.jsonl'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'path binding'):
            preflight.validate(self.root)

    def test_symlink_rejected_before_open(self):
        p = self.root / preflight.ARTIFACTS['scorer']
        p.unlink()
        p.symlink_to('/never/open/sealed.jsonl')
        with self.assertRaisesRegex(ValueError, 'redirected'):
            preflight.validate(self.root)

    def test_status_flip_cannot_authorize(self):
        self.manifest['status'] = 'PASS'
        self.manifest['acceptance_authorized'] = True
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'disposition'):
            preflight.validate(self.root)

    def test_cli_returns_two_for_valid_and_invalid_artifacts(self):
        with patch.object(preflight, 'validate', return_value={'status': preflight.STATUS}), patch('builtins.print'):
            self.assertEqual(preflight.main(), 2)
        with patch.object(preflight, 'validate', side_effect=ValueError('bad binding')), patch('builtins.print'):
            self.assertEqual(preflight.main(), 2)


if __name__ == '__main__':
    unittest.main()
