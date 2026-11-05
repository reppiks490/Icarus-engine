import copy
from decimal import Decimal
import math
import random
import unittest
from research_allocation.contracts import ModelError, parse_model
from research_allocation.decision import evaluate
from research_allocation.bundles import evaluate_bundle
from research_allocation.robust import compare_scenarios
from research_allocation.handoff import prepare_handoff


def model():
    return {'schema_version': 'atlas.decision.v1', 'id': 'synthetic-two-state',
            'states': ['A', 'B'], 'prior': {'A': .5, 'B': .5},
            'utility': {'choose_A': {'A': 1, 'B': 0}, 'choose_B': {'A': 0, 'B': 1},
                        'defer': {'A': 0, 'B': 0}},
            'utility_unit': 'synthetic_utility',
            'provenance': {'kind': 'synthetic', 'reference': 'analytical unit example'},
            'experiments': [experiment()]}


def experiment(eid='signal', accuracy=1, low=.1, high=.1):
    return {'id': eid, 'outcomes': ['a', 'b'],
            'likelihood': {'A': {'a': accuracy, 'b': 1-accuracy},
                           'B': {'a': 1-accuracy, 'b': accuracy}},
            'available': True, 'reference': 'synthetic finite model',
            'cost': {'low': low, 'high': high, 'unit': 'synthetic_utility'}}


def result(raw):
    return evaluate(raw)['experiments'][0]


def xor_bundle():
    return {'id': 'joint', 'members': ['left', 'right'],
            'outcomes': {'aa': {'left': 'a', 'right': 'a'},
                         'ab': {'left': 'a', 'right': 'b'},
                         'ba': {'left': 'b', 'right': 'a'},
                         'bb': {'left': 'b', 'right': 'b'}},
            'likelihood': {'A': {'aa': .5, 'ab': 0, 'ba': 0, 'bb': .5},
                           'B': {'aa': 0, 'ab': .5, 'ba': .5, 'bb': 0}},
            'reference': 'synthetic XOR observation'}


class ValueTests(unittest.TestCase):
    def test_perfect_information_analytic(self):
        r = result(model())
        self.assertAlmostEqual(r['gross_decision_value'], .5)
        self.assertAlmostEqual(r['net_decision_value']['low'], .4)
        self.assertAlmostEqual(r['mutual_information_bits'], 1)
        self.assertEqual(r['outcome_policy'][0]['best_actions'], ['choose_A'])

    def test_uninformative_observation_has_no_value(self):
        m = model(); m['experiments'] = [experiment(accuracy=.5)]
        r = result(m)
        self.assertAlmostEqual(r['gross_decision_value'], 0)
        self.assertAlmostEqual(r['net_decision_value']['low'], -.1)
        self.assertEqual(r['indistinguishable_state_pairs'], [['A', 'B']])

    def test_information_without_action_value(self):
        m = model(); m['utility']['defer'] = {'A': 2, 'B': 2}
        r = result(m)
        self.assertAlmostEqual(r['gross_decision_value'], 0)
        self.assertAlmostEqual(r['mutual_information_bits'], 1)

    def test_prior_changes_value(self):
        m = model(); m['prior'] = {'A': .99, 'B': .01}
        self.assertAlmostEqual(result(m)['gross_decision_value'], .01)

    def test_zero_prior(self):
        m = model(); m['prior'] = {'A': 1, 'B': 0}
        self.assertEqual(result(m)['gross_decision_value'], 0)

    def test_unreachable_outcome_is_explicit(self):
        m = model()
        m['experiments'][0]['outcomes'].append('impossible')
        for row in m['experiments'][0]['likelihood'].values(): row['impossible'] = 0
        out = result(m)['outcome_policy'][-1]
        self.assertIsNone(out['posterior'])
        self.assertEqual(out['best_actions'], [])

    def test_subnormal_prior_does_not_overflow_information(self):
        m = model(); m['prior'] = {'A': 1e-320, 'B': 1.0}
        self.assertTrue(math.isfinite(result(m)['mutual_information_bits']))

    def test_unknown_cost_stays_unknown(self):
        m = model(); m['experiments'][0]['cost'] = None
        self.assertEqual(result(m)['status'], 'UNKNOWN_COST')
        self.assertIsNone(result(m)['net_decision_value'])

    def test_cost_interval_crosses_zero(self):
        m = model(); m['experiments'] = [experiment(low=.1, high=.8)]
        self.assertEqual(result(m)['status'], 'COST_SENSITIVE')

    def test_unavailable_not_recommended(self):
        m = model(); m['experiments'][0]['available'] = False
        self.assertEqual(result(m)['status'], 'UNAVAILABLE')

    def test_utility_shift_invariance(self):
        m = model(); expected = result(m)['gross_decision_value']
        for values in m['utility'].values():
            for s in values: values[s] -= 100
        self.assertAlmostEqual(result(m)['gross_decision_value'], expected)

    def test_positive_scaling_scales_value(self):
        m = model(); expected = result(m)['net_decision_value']['low']
        for values in m['utility'].values():
            for s in values: values[s] *= 13
        m['experiments'][0]['cost'] = {'low': 1.3, 'high': 1.3, 'unit': 'synthetic_utility'}
        self.assertAlmostEqual(result(m)['net_decision_value']['low'], expected * 13)

    def test_input_unchanged(self):
        m = model(); original = copy.deepcopy(m); evaluate(m)
        self.assertEqual(m, original)

    def test_250_random_models_against_decimal_oracle(self):
        rng = random.Random(3401)
        for _ in range(250):
            m = model(); p = rng.randint(1, 99) / 100; q = rng.randint(0, 100) / 100
            m['prior'] = {'A': p, 'B': 1-p}
            m['experiments'] = [experiment(accuracy=q)]
            for utility in m['utility'].values():
                for s in utility: utility[s] = rng.randint(-30, 30)
            d = lambda x: Decimal(str(x))
            baseline = max(sum(d(m['prior'][s])*d(v[s]) for s in m['states'])
                           for v in m['utility'].values())
            after = sum(max(sum(d(m['prior'][s])*d(m['experiments'][0]['likelihood'][s][o])*d(v[s])
                                for s in m['states']) for v in m['utility'].values())
                        for o in ['a', 'b'])
            self.assertAlmostEqual(result(m)['gross_decision_value'], float(after-baseline), places=10)


class ContractTests(unittest.TestCase):
    def test_invalid_inputs(self):
        mutations = [
            lambda m: m.update(schema_version='v0'),
            lambda m: m.update(execution_authorized=True),
            lambda m: m.update(unrecognized=True),
            lambda m: m.update(prior={'A': .7, 'B': .7}),
            lambda m: m.update(states=['A', 'A']),
            lambda m: m['prior'].update(A=True),
            lambda m: m['prior'].update(A=float('nan')),
            lambda m: m['utility']['choose_A'].update(A=float('inf')),
            lambda m: m['utility'].pop('defer'),
            lambda m: m['experiments'][0]['cost'].update(unit='USD'),
            lambda m: m['experiments'][0]['cost'].update(low=2),
            lambda m: m['experiments'][0]['cost'].update(low=-1),
            lambda m: m['experiments'][0].update(available=1),
            lambda m: m['experiments'][0]['likelihood']['A'].update(a=.8),
            lambda m: m['experiments'].append(copy.deepcopy(m['experiments'][0])),
            lambda m: m['provenance'].update(kind='verified_market_truth'),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                m = model(); mutate(m)
                with self.assertRaises(ModelError): parse_model(m)

    def test_roundoff_only_probability_normalization(self):
        m = model(); m['prior']['B'] = .50000000000001
        self.assertAlmostEqual(sum(parse_model(m).prior.values()), 1)

    def test_handoff_is_not_runtime_authority(self):
        h = prepare_handoff(model(), owner='Claude', as_of='2026-10-11T16:00:00Z',
                            source_revision='a'*40)
        self.assertEqual(h['review_state'], 'OWNER_REVIEW_REQUIRED')
        self.assertFalse(h['runtime_integration_verified'])
        self.assertFalse(h['execution_authorized'])


class JointTests(unittest.TestCase):
    def test_complementary_pair(self):
        m = model(); m['experiments'] = [experiment('left', .5), experiment('right', .5)]
        r = evaluate_bundle(parse_model(m), xor_bundle())
        self.assertAlmostEqual(r['complementarity_vs_sum'], .5)
        self.assertAlmostEqual(r['net_decision_value']['low'], .3)

    def test_joint_must_match_marginals(self):
        m = model(); m['experiments'] = [experiment('left'), experiment('right')]
        with self.assertRaises(ModelError): evaluate_bundle(parse_model(m), xor_bundle())

    def test_redundant_observations_not_double_counted(self):
        m = model(); m['experiments'] = [experiment('left'), experiment('right')]
        b = xor_bundle()
        b['likelihood'] = {'A': {'aa': 1, 'ab': 0, 'ba': 0, 'bb': 0},
                            'B': {'aa': 0, 'ab': 0, 'ba': 0, 'bb': 1}}
        r = evaluate_bundle(parse_model(m), b)
        self.assertEqual(r['increment_over_best_single'], 0)
        self.assertEqual(r['complementarity_vs_sum'], -.5)

    def test_unknown_member_cost_propagates(self):
        m = model(); m['experiments'] = [experiment('left', .5), experiment('right', .5)]
        m['experiments'][1]['cost'] = None
        self.assertEqual(evaluate_bundle(parse_model(m), xor_bundle())['status'], 'UNKNOWN_COST')

    def test_duplicate_joint_tuple_rejected(self):
        m = model(); m['experiments'] = [experiment('left', .5), experiment('right', .5)]
        b = xor_bundle(); b['outcomes']['ab'] = b['outcomes']['aa'].copy()
        with self.assertRaises(ModelError): evaluate_bundle(parse_model(m), b)


class RobustTests(unittest.TestCase):
    def test_robust_dominance(self):
        m = model(); m['experiments'] += [experiment('weak', .6)]
        r = compare_scenarios({'base': m, 'repeat': copy.deepcopy(m)})
        self.assertEqual(r['recommendation'], ['signal'])
        self.assertEqual(r['experiments']['weak']['dominated_by'], ['signal'])

    def test_unknown_cost_blocks_complete_recommendation(self):
        m = model(); m['experiments'] += [experiment('unknown')]
        m['experiments'][1]['cost'] = None
        r = compare_scenarios({'base': m})
        self.assertEqual(r['status'], 'INCOMPLETE_COMPARISON')
        self.assertEqual(r['recommendation'], ['DEFER'])
        self.assertEqual(r['conditional_maximin_choices'], ['signal'])

    def test_no_positive_value_defers(self):
        m = model(); m['experiments'] = [experiment(accuracy=.5)]
        self.assertEqual(compare_scenarios({'base': m})['recommendation'], ['DEFER'])

    def test_unit_or_utility_change_rejected(self):
        m = model(); n = copy.deepcopy(m); n['utility']['defer']['A'] = 3
        with self.assertRaises(ModelError): compare_scenarios({'one': m, 'two': n})

    def test_scenario_disagreement_with_cost_sensitivity(self):
        m = model(); m['experiments'] += [experiment('other', .8, .01, .01)]
        n = copy.deepcopy(m); n['experiments'][0]['cost']['high'] = .9
        r = compare_scenarios({'low': m, 'high': n})
        self.assertEqual(r['recommendation'], ['other'])


if __name__ == '__main__': unittest.main()
