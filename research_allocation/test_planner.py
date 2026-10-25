import copy
import unittest
from research_allocation.planner import plan

NOW = '2026-10-11T15:42:00Z'


def fixture():
    return {'schema_version': 1, 'snapshot_at': NOW,
            'evidence': [dict(id=k, owner='peer', source='synthetic fixture', status='pending')
                         for k in ['a', 'b', 'c']],
            'decisions': [dict(id='one', owner='peer', source='synthetic fixture',
                               alternatives=[['a', 'b'], ['c']]),
                          dict(id='two', owner='peer', source='synthetic fixture',
                               alternatives=[['a', 'b']])]}


class PlannerTests(unittest.TestCase):
    def test_joint_prerequisites_and_shared_unlock(self):
        p = plan(fixture(), NOW)
        self.assertEqual(p['candidate_bundles'][0]['evidence'], ['a', 'b'])
        self.assertEqual(p['candidate_bundles'][0]['structural_impact'], 2)
        self.assertFalse(p['execution_authorized'])

    def test_rejection_removes_only_affected_route(self):
        d = fixture(); d['evidence'][0]['status'] = 'rejected'
        p = plan(d, NOW)
        self.assertEqual(p['decisions'][0]['missing_bundles'], [['c']])
        self.assertEqual(p['decisions'][1]['status'], 'no_viable_route')

    def test_stale_evidence_cannot_unlock(self):
        d = fixture()
        d['evidence'][2].update(status='verified', receipt='synthetic',
                                observed_at='2026-10-09T00:00:00Z',
                                valid_until='2026-10-10T00:00:00Z')
        self.assertEqual(plan(d, NOW)['decisions'][0]['status'], 'unresolved')

    def test_valid_evidence_is_only_ready_for_review(self):
        d = fixture()
        d['evidence'][2].update(status='verified', receipt='synthetic', observed_at=NOW,
                                valid_until='2026-10-12T00:00:00Z')
        self.assertEqual(plan(d, NOW)['decisions'][0]['status'], 'ready_for_owner_review')

    def test_missing_receipt_rejected(self):
        d = fixture(); d['evidence'][0]['status'] = 'verified'
        with self.assertRaises(ValueError): plan(d, NOW)

    def test_unknown_dependency_rejected(self):
        d = fixture(); d['decisions'][0]['alternatives'] = [['typo']]
        with self.assertRaises(ValueError): plan(d, NOW)

    def test_future_snapshot_rejected(self):
        with self.assertRaises(ValueError): plan(fixture(), '2026-10-10T00:00:00Z')

    def test_input_is_unchanged_and_output_deterministic(self):
        d = fixture(); before = copy.deepcopy(d)
        self.assertEqual(plan(d, NOW), plan(d, NOW))
        self.assertEqual(d, before)

    def test_minimal_routes_remove_supersets(self):
        d = fixture(); d['decisions'][0]['alternatives'] = [['a'], ['a', 'b']]
        self.assertEqual(plan(d, NOW)['decisions'][0]['missing_bundles'], [['a']])


if __name__ == '__main__': unittest.main()
