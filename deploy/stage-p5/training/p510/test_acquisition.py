"""Adversarial quarantine/provenance guards; fixtures are not model evaluations."""
import copy
import unittest
from protocol_v2 import validate_protocol as v
from protocol_v2 import acquisition as a


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.bundle = v.load_bundle()
        self.sdoc = self.bundle['acquisition_sources.json']
        self.cdoc = self.bundle['acquisition_candidates.json']
        self.sources = self.sdoc['sources']
        self.rows = self.cdoc['candidates']

    def inspect(self):
        return a.inspect(self.sdoc, self.cdoc, self.bundle['sources.json']['sources'],
                         self.bundle['families.json']['families'], v.DOMAINS,
                         v.record_hash, v.split_guard, v.normalized)

    def rehash(self, row):
        row['record_sha256'] = v.record_hash(row)

    def test_real_packet_and_no_assignments(self):
        out = self.inspect()
        self.assertEqual(out['candidate_count'], 40)
        self.assertEqual(out['new_primary_source_families'], 32)
        self.assertEqual(out['domains'], {d: 5 for d in v.DOMAINS})
        self.assertEqual(out['retrieval'], dict(FETCHED_RESPONSE_HASHED=17,
                                              WEB_EXCERPT_RAW_FETCH_FAILED=15))
        self.assertEqual(out['certified_scenarios'], 0)
        self.assertEqual(out['review_queue']['assigned_roles'], [])
        self.assertEqual(out['review_queue']['eligible_candidates'], 0)
        full = v.inspect(self.bundle)
        self.assertEqual(full['acquisition'], out)
        self.assertEqual(full['certified_scenarios'], 0)
        self.assertEqual(full['sealed_final'], 'UNOPENED')
        self.assertFalse(full['acceptance_authorized'])

    def test_hash_tampering(self):
        for collection in (self.sources, self.rows):
            with self.subTest(kind=collection[0].get('source_id', 'candidate')):
                collection[0]['extra_claim'] = 'forged'
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    self.inspect()
                del collection[0]['extra_claim']

    def test_duplicate_source_identity(self):
        for key in ('source_id', 'source_family_id', 'url', 'title'):
            with self.subTest(key=key):
                before = copy.deepcopy(self.sources[1])
                self.sources[1][key] = self.sources[0][key]
                self.rehash(self.sources[1])
                with self.assertRaisesRegex(ValueError, 'duplicate'):
                    self.inspect()
                self.sources[1] = before

    def test_tracking_url_cannot_create_new_source(self):
        self.sources[1]['url'] = self.sources[0]['url'] + '#renamed'
        self.rehash(self.sources[1])
        with self.assertRaisesRegex(ValueError, 'canonical URL'):
            self.inspect()
        self.assertEqual(a.canonical_url('https://www.ti.com/a.pdf?ts=123&utm_source=x'),
                         a.canonical_url('https://www.ti.com/a.pdf'))
        self.assertNotEqual(a.canonical_url('https://www.vishay.com/doc/?28960='),
                            a.canonical_url('https://www.vishay.com/doc/?20132='))

    def test_duplicate_candidate_id_and_cluster(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        with self.assertRaises(ValueError):
            self.inspect()
        self.rows.pop()
        self.rows[1]['causal_cluster_id'] = self.rows[0]['causal_cluster_id']
        self.rehash(self.rows[1])
        with self.assertRaisesRegex(ValueError, 'causal cluster'):
            self.inspect()

    def test_relabelled_numeric_variant_not_new_family(self):
        r = copy.deepcopy(self.rows[0])
        r.update(family_id='new-id', causal_cluster_id='renamed-cluster')
        r['topology'] += ' 12 V'
        original = self.rows[0]
        original['topology'] += ' 24 V'
        self.rehash(original)
        self.rehash(r)
        self.rows.append(r)
        with self.assertRaisesRegex(ValueError, 'causal fingerprint'):
            self.inspect()

    def test_required_candidate_fields_even_after_rehash(self):
        for key in ('automotive_context', 'competing_mechanism', 'source_support_scope',
                    'review_notes', 'safety_constraints', 'primary_sources', 'exposure',
                    'sufficiency_potential', 'correctness_review', 'possible_overlap_family_ids'):
            with self.subTest(key=key):
                saved = copy.deepcopy(self.rows[0])
                del self.rows[0][key]
                self.rehash(self.rows[0])
                with self.assertRaises(ValueError):
                    self.inspect()
                self.rows[0] = saved

    def test_required_source_fields(self):
        for key in ('vendor', 'locator', 'license', 'accessed_date', 'inspection_scope'):
            with self.subTest(key=key):
                saved = copy.deepcopy(self.sources[0])
                del self.sources[0][key]
                self.rehash(self.sources[0])
                with self.assertRaises(ValueError):
                    self.inspect()
                self.sources[0] = saved

    def test_failed_fetch_cannot_receive_invented_hash(self):
        s = next(s for s in self.sources if s['retrieved_sha256'] is None)
        s['retrieved_sha256'] = 'a' * 64
        self.rehash(s)
        with self.assertRaisesRegex(ValueError, 'failed source fetch'):
            self.inspect()

    def test_successful_fetch_requires_realistic_response_metadata(self):
        s = next(s for s in self.sources if s['retrieved_sha256'] is not None)
        for key, bad in [('retrieved_sha256', None), ('retrieved_bytes', True),
                         ('http_status', 403), ('retrieved_bytes', 0)]:
            saved = copy.deepcopy(s)
            s[key] = bad
            self.rehash(s)
            with self.assertRaises(ValueError):
                self.inspect()
            s.clear()
            s.update(saved)

    def test_foreign_host_and_retrieval_date_fail(self):
        s = self.sources[0]
        for key, bad in [('url', 'https://example.org/fake.pdf'),
                         ('accessed_date', '2020-01-01')]:
            saved = copy.deepcopy(s)
            s[key] = bad
            self.rehash(s)
            with self.assertRaises(ValueError):
                self.inspect()
            s.clear()
            s.update(saved)

    def test_rebound_candidate_provenance_must_match_registry(self):
        self.rows[0]['primary_sources'][0]['title'] = 'unsupported title'
        self.rehash(self.rows[0])
        with self.assertRaisesRegex(ValueError, 'provenance binding'):
            self.inspect()

    def test_candidate_cannot_bind_wrong_primary_family(self):
        self.rows[0]['source_family_id'] = self.rows[1]['source_family_id']
        self.rehash(self.rows[0])
        with self.assertRaisesRegex(ValueError, 'provenance binding'):
            self.inspect()

    def test_source_cannot_claim_independent_review(self):
        self.sources[0]['review'] = 'INDEPENDENT_REVIEWER'
        self.rehash(self.sources[0])
        with self.assertRaisesRegex(ValueError, 'review claim'):
            self.inspect()

    def test_automatic_attestation_cannot_promote(self):
        for field in ('correctness_review', 'independence_review', 'custodian_attestation'):
            saved = copy.deepcopy(self.rows[0])
            self.rows[0][field] = dict(actor='Codex', status='PASS')
            self.rehash(self.rows[0])
            with self.assertRaisesRegex(ValueError, 'automatic review'):
                self.inspect()
            self.rows[0] = saved

    def test_all_five_lineages_remain_unknown(self):
        for lineage in sorted(a.LINEAGES):
            saved = copy.deepcopy(self.rows[0])
            self.rows[0]['exposure'][lineage]['status'] = 'EXCLUDED'
            self.rehash(self.rows[0])
            with self.assertRaisesRegex(ValueError, 'exposure claim'):
                self.inspect()
            self.rows[0] = saved

    def test_role_assignment_and_envelope_unlock_fail(self):
        for field, value in [('role', 'parent_selection'), ('eligible_roles', ['prefinal']),
                             ('certification', 'CERTIFIED')]:
            saved = copy.deepcopy(self.rows[0])
            self.rows[0][field] = value
            self.rehash(self.rows[0])
            with self.assertRaisesRegex(ValueError, 'promotion'):
                self.inspect()
            self.rows[0] = saved
        for field, value in [('training_authorized', True), ('parent', 'v3'),
                             ('assigned_roles', ['selection_dev']), ('acceptance_authorized', 0)]:
            saved = copy.deepcopy(self.cdoc[field])
            self.cdoc[field] = value
            with self.assertRaisesRegex(ValueError, 'promotion'):
                self.inspect()
            self.cdoc[field] = saved

    def test_no_fabricated_measurements_or_labels(self):
        self.rows[0]['sufficiency_potential']['observed_data'] = {'voltage': 12}
        self.rehash(self.rows[0])
        with self.assertRaisesRegex(ValueError, 'observation claim'):
            self.inspect()

    def test_legacy_and_secondary_source_cross_role_collisions(self):
        x, y = copy.deepcopy(self.rows[:2])
        x['role'] = 'parent_selection'
        y['role'] = 'prefinal'
        y['source_family_ids'] = [y['source_family_id'], x['source_family_id']]
        with self.assertRaisesRegex(ValueError, 'cross-role'):
            v.split_guard([x, y])
        y.pop('source_family_ids')
        y['causal_cluster_id'] = x['causal_cluster_id']
        with self.assertRaisesRegex(ValueError, 'cross-role'):
            v.split_guard([x, y])

    def test_transitive_possible_overlap_holds_cannot_cross_roles(self):
        rows = copy.deepcopy(self.rows[:3])
        for row in rows:
            row['possible_overlap_family_ids'] = []
        rows[0]['possible_overlap_family_ids'] = [rows[1]['family_id']]
        rows[1]['possible_overlap_family_ids'] = [rows[2]['family_id']]
        self.assertEqual(len(a.review_groups(rows)), 1)
        rows[2]['role'] = 'selection_dev'
        with self.assertRaisesRegex(ValueError, 'cross-role'):
            a.review_groups(rows)

    def test_unknown_overlap_reference_rejected(self):
        self.rows[0]['possible_overlap_family_ids'] = ['nonexistent-family']
        self.rehash(self.rows[0])
        with self.assertRaisesRegex(ValueError, 'overlap family reference'):
            self.inspect()

    def test_no_unused_sources_counted_as_evidence(self):
        unused = copy.deepcopy(self.sources[0])
        unused.update(source_id='unused', source_family_id='unused', title='unused document',
                      url='https://www.ti.com/unused.pdf')
        self.rehash(unused)
        self.sources.append(unused)
        with self.assertRaisesRegex(ValueError, 'unbound acquisition source'):
            self.inspect()


if __name__ == '__main__':
    unittest.main()
