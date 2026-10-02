"""Software guards only; no independent domain review or model evaluation."""
import copy
import json
import unittest
from pathlib import Path
from protocol_v2 import validate_protocol as v


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.bundle = v.load_bundle()
        self.rows = self.bundle['families.json']['families']

    def test_snapshot_never_authorizes(self):
        out = v.inspect(self.bundle)
        self.assertEqual(out['certified_scenarios'], 0)
        self.assertEqual(len(out['domains']), 8)
        self.assertFalse(out['acceptance_authorized'])

    def test_source_tampering(self):
        self.bundle['sources.json']['sources'][0]['claim'] = 'fabricated'
        with self.assertRaisesRegex(ValueError, 'hash'): v.inspect(self.bundle)

    def test_cross_role_source(self):
        self.rows[0]['role'] = 'parent_selection'
        self.rows[1]['role'] = 'selection_dev'
        with self.assertRaisesRegex(ValueError, 'cross-role'): v.split_guard(self.rows)

    def test_relabelled_numeric_family(self):
        a = copy.deepcopy(self.rows[0]); b = copy.deepcopy(a)
        a.update(role='train', topology='source 12 V -> contact 3 -> load')
        b.update(role='prefinal', family_id='alias', source_family_id='another-source',
                 causal_cluster_id='renamed', topology='source 24 V -> contact 9 -> load')
        with self.assertRaisesRegex(ValueError, 'cross-role'): v.split_guard([a,b])

    def test_renamed_causal_cluster(self):
        a = copy.deepcopy(self.rows[0]); b = copy.deepcopy(self.rows[2])
        a['role'] = 'calibration'; b['role'] = 'sealed_final'
        b['causal_cluster_id'] = a['causal_cluster_id']
        with self.assertRaisesRegex(ValueError, 'cross-role'): v.split_guard([a,b])

    def test_duplicate_and_missing_metadata(self):
        with self.assertRaises(ValueError): v.split_guard(self.rows + [self.rows[0]])
        del self.rows[0]['intervention']
        with self.assertRaises(ValueError): v.split_guard(self.rows)

    def test_threshold_lowering_and_status_flip(self):
        for key, value in [('prefinal_floors', {}), ('acceptance_authorized', True), ('status', 'PASS')]:
            b = copy.deepcopy(self.bundle); b['protocol.json'][key] = value
            with self.assertRaises(ValueError): v.inspect(b)

    def test_fake_review_cannot_promote_seed(self):
        self.rows[0]['independence_review'] = {'actor':'automatic', 'status':'PASS'}
        self.rows[0]['record_sha256'] = v.record_hash(self.rows[0])
        with self.assertRaisesRegex(ValueError, 'promotion'): v.inspect(self.bundle)

    def test_polish_fixture_mutations(self):
        for fixture in self.bundle['calibration.json']['fixtures']:
            with self.subTest(domain=fixture['case']['category']):
                c, r = fixture['case'], fixture['positive']
                s = v.compare.scorer
                self.assertTrue(all(s.score_case(c,r)[d] for d in s.DIMENSIONS))
                eq = copy.deepcopy(r)
                for field in s.FIELDS: eq['parsed'][field] = '  '.join(eq['parsed'][field].upper().split())
                self.assertTrue(all(s.score_case(c,eq)[d] for d in s.DIMENSIONS))
                for field, dim in zip(s.FIELDS, s.DIMENSIONS):
                    bad = copy.deepcopy(r); bad['parsed'][field] += ' Odwrócona przyczynowość.'
                    self.assertFalse(s.score_case(c,bad)[dim])
                for mutation in ['Na pewno.', '1000 V', 'Zasil magistralę podczas pomiaru rezystancji']:
                    bad = copy.deepcopy(r); bad['parsed']['predicted_result'] += ' '+mutation
                    self.assertFalse(s.score_case(c,bad)['no_guessing_pass'])
                bad = copy.deepcopy(r); bad['parsed']['abstain'] = True
                self.assertFalse(s.score_case(c,bad)['abstain_ok'])

    def test_unlisted_negation_requires_review(self):
        # Known v5.1 false positive now escalates conservatively under v5.2.
        f = self.bundle['calibration.json']['fixtures'][0]; r = copy.deepcopy(f['positive'])
        r['parsed']['diagnostic_model'] = 'Nieprawda, że: ' + r['parsed']['diagnostic_model']
        self.assertFalse(v.compare.scorer.score_case(f['case'],r)['diagnostic_model_pass'])
        self.assertTrue(v.compare.scorer.score_case(f['case'],r)['review_required'])
        self.assertIsNone(self.bundle['calibration.json']['independent_review'])

    def make_report(self, missing=None, successes=50):
        rows=[]
        for domain in sorted(v.DOMAINS - ({missing} if missing else set())):
            for i in range(50):
                row=dict(case_id=f'{domain}-{i}', scenario_id=f'{domain}-{i}', category=domain,
                         must_abstain=i<10, raw_parse_ok=True, final_parse_ok=True, review_required=False)
                row.update({d: True for d in v.compare.DIMENSIONS})
                row['diagnostic_model_pass'] = i < successes
                rows.append(row)
        return dict(scorer=v.compare.scorer.SCORER, status='SCORED', details=rows,
                    metrics=v.compare.scorer.aggregate(rows)[0], bindings=dict(dataset_sha256='a'*64,
                    results_sha256='b'*64,scorer_sha256=v.compare.scorer.digest(v.compare.SCORER_PATH)))

    def test_numerical_prefinal_never_unlocks(self):
        out = v.prefinal_metrics(self.make_report())
        self.assertTrue(out['numerical_checks_satisfied'])
        self.assertFalse(out['acceptance_authorized'])

    def test_prefinal_missing_domain_and_wilson_boundary(self):
        self.assertFalse(v.prefinal_metrics(self.make_report(missing='power_integrity'))['numerical_checks_satisfied'])
        self.assertFalse(v.prefinal_metrics(self.make_report(successes=45))['numerical_checks_satisfied'])
        self.assertTrue(v.prefinal_metrics(self.make_report(successes=46))['numerical_checks_satisfied'])

    def test_prefinal_rejects_unresolved_review_and_forged_summary(self):
        r=self.make_report(); r['details'][0]['review_required']=True
        with self.assertRaises(ValueError): v.prefinal_metrics(r)
        r=self.make_report(); r['metrics']['records']=999
        with self.assertRaises(ValueError): v.prefinal_metrics(r)

    def test_simulation_is_deterministic_and_quarantined(self):
        a = v.simulation.build_snapshot()
        b = v.simulation.build_snapshot()
        self.assertEqual(a, b)
        self.assertTrue(v.simulation.validate_snapshot(a))
        self.assertEqual(a['family_count'], 8)
        self.assertFalse(a['acceptance_authorized'])
        self.assertFalse(a['training_authorized'])
        self.assertFalse(a['sealed_final_authorized'])
        self.assertTrue(all(r['status'] == v.simulation.STATUS for r in a['families']))
        self.assertTrue(all(r['mathematical_ground_truth_verified'] is True for r in a['families']))
        self.assertTrue(all(r['p5_exposure_excluded'] is False for r in a['families']))
        self.assertTrue(all(r['real_world_representativeness_certified'] is False for r in a['families']))
        self.assertTrue(all(r['eligible_for_parent_selection'] is False for r in a['families']))

    def test_simulation_has_one_distinct_mechanism_per_domain(self):
        a = v.simulation.build_snapshot()
        rows = a['families']
        self.assertEqual({r['domain'] for r in rows}, v.DOMAINS)
        self.assertEqual(len({r['family_id'] for r in rows}), 8)
        self.assertEqual(len({r['model_kind'] for r in rows}), 8)
        self.assertTrue(all(r['oracle_pass'] and r['metamorphic_pass'] for r in rows))

    def test_simulation_observable_tamper_fails(self):
        a = v.simulation.build_snapshot()
        row = a['families'][0]
        key = next(k for k, val in row['observables'].items() if isinstance(val, (int, float)))
        row['observables'][key] += 0.125
        with self.assertRaisesRegex(ValueError, 'simulation result mismatch'):
            v.simulation.validate_snapshot(a)

    def test_simulation_cannot_be_relabelled_as_eval(self):
        a = v.simulation.build_snapshot()
        a['families'][0]['eligible_for_parent_selection'] = True
        with self.assertRaises(ValueError):
            v.simulation.validate_snapshot(a)
        out = v.inspect(self.bundle)
        self.assertEqual(out['certified_scenarios'], 0)
        self.assertEqual(out['simulation_verified_quarantine_families'], 8)
        self.assertFalse(out['acceptance_authorized'])

    def test_v51_snapshot_bound_and_v52_scope_fail_closed(self):
        import hashlib
        old = Path(v.HERE / 'scorer_v5_1_snapshot.py')
        protocol = self.bundle['protocol.json']
        self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(),
                         protocol['execution_contract']['historical_scorer_v5_1_sha256'])
        self.assertEqual(v.compare.scorer.SCORER, 'case-rubric-v5.2-scope-fail-closed')
        f = self.bundle['calibration.json']['fixtures'][0]
        r = copy.deepcopy(f['positive'])
        r['parsed']['diagnostic_model'] = 'Ktoś twierdzi: ' + r['parsed']['diagnostic_model']
        scored = v.compare.scorer.score_case(f['case'], r)
        self.assertFalse(scored['diagnostic_model_pass'])
        self.assertTrue(scored['review_required'])


if __name__ == '__main__':
    unittest.main()
