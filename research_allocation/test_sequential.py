from decimal import Decimal
import random
import unittest
from research_allocation.contracts import ModelError, parse_model
from research_allocation.sequential import evaluate_sequential
from research_allocation.test_decision import model, experiment, xor_bundle


def selective_model():
    m = model()
    first = experiment('first', low=.05, high=.05)
    first['likelihood'] = {'A': {'a': .5, 'b': .5}, 'B': {'a': 0, 'b': 1}}
    m['experiments'] = [first, experiment('second')]
    b = xor_bundle(); b['members'] = ['first', 'second']
    b['outcomes'] = {x: {'first': x[0], 'second': x[1]} for x in ['aa','ab','ba','bb']}
    b['likelihood'] = {'A': {'aa': .5, 'ab': 0, 'ba': .5, 'bb': 0},
                       'B': {'aa': 0, 'ab': 0, 'ba': 0, 'bb': 1}}
    return m, b


def rare_model(component_probability=1e-12, joint_probability=1e-12):
    m = model()
    m['utility'] = {'choose_A': {'A': 1e12, 'B': -1e12},
                    'defer': {'A': 0, 'B': 0}}
    first = experiment('left', low=1, high=1)
    first['likelihood'] = {s: {'a': component_probability,
                               'b': 1-component_probability} for s in m['states']}
    m['experiments'] = [first, experiment('right', low=7.5e11, high=7.5e11)]
    b = xor_bundle()
    b['likelihood'] = {'A': {'aa': joint_probability, 'ab': 0,
                            'ba': 1-joint_probability, 'bb': 0},
                       'B': {'aa': 0, 'ab': joint_probability,
                            'ba': 0, 'bb': 1-joint_probability}}
    return m, b


class SequentialTests(unittest.TestCase):
    def test_large_constant_utility_preserves_tiny_negative_acquisition_cost(self):
        m = model()
        m['prior'] = {'A': .7994044827864234, 'B': 1-.7994044827864234}
        m['utility'] = {a: {'A': 1e12, 'B': 1e12} for a in m['utility']}
        first = experiment('left', low=1e-8, high=1e-8)
        first['likelihood'] = {'A': {'a': .03280200762057717, 'b': 1-.03280200762057717},
                               'B': {'a': .48088133338888395, 'b': 1-.48088133338888395}}
        m['experiments'] = [first, experiment('right', .5)]
        b = xor_bundle()
        b['likelihood'] = {s: {j: first['likelihood'][s][values['left']]*.5
                               for j, values in b['outcomes'].items()} for s in m['states']}
        r = evaluate_sequential(parse_model(m), b, 'left')
        self.assertAlmostEqual(r['conservative_policy']['net_value'], -1e-8, places=12)
        self.assertFalse(r['preferred_to_no_acquisition_at_high_cost'])

    def test_200_joint_policies_against_decimal_oracle(self):
        rng = random.Random(8453)
        d = lambda x: Decimal(str(x))
        for _ in range(200):
            m, b = selective_model()
            p = rng.randint(1, 99)/100
            m['prior'] = {'A': p, 'B': 1-p}
            for state in m['states']:
                weights = {j: rng.randint(0, 20) for j in b['outcomes']}
                total = sum(weights.values())
                b['likelihood'][state] = {j: w/total for j, w in weights.items()}
                for exp in m['experiments']:
                    exp['likelihood'][state] = {
                        o: sum(b['likelihood'][state][j] for j, values in b['outcomes'].items()
                               if values[exp['id']] == o) for o in exp['outcomes']}
            for values in m['utility'].values():
                for state in m['states']: values[state] = rng.randint(-30, 30)
            for exp in m['experiments']:
                cost = rng.randint(0, 500)/100
                exp['cost'].update(low=cost, high=cost)
            prior_total = sum(d(v) for v in m['prior'].values())
            prior = {s: d(v)/prior_total for s, v in m['prior'].items()}
            joint = {s: {j: d(v)/sum(d(w) for w in row.values()) for j, v in row.items()}
                     for s, row in b['likelihood'].items()}
            baseline = max(sum(prior[s]*d(values[s]) for s in m['states'])
                           for values in m['utility'].values())
            terms = []
            for first in ('a', 'b'):
                labels = [j for j, values in b['outcomes'].items() if values['first'] == first]
                mass = sum(prior[s]*joint[s][j] for s in m['states'] for j in labels)
                stop = max(sum(prior[s]*joint[s][j]*d(values[s])
                               for s in m['states'] for j in labels)
                           for values in m['utility'].values())
                follow = sum(max(sum(prior[s]*joint[s][j]*d(values[s])
                                      for s in m['states'] for j in labels
                                      if b['outcomes'][j]['second'] == second)
                                 for values in m['utility'].values()) for second in ('a', 'b'))
                terms.append(max(stop, follow-mass*d(m['experiments'][1]['cost']['high'])))
            expected = sum(terms)-d(m['experiments'][0]['cost']['high'])-baseline
            actual = evaluate_sequential(parse_model(m), b, 'first')
            self.assertAlmostEqual(actual['conservative_policy']['net_value'],
                                   float(expected), places=10)

    def test_rare_component_marginal_mismatch_rejected(self):
        m, b = rare_model(joint_probability=5e-10)
        with self.assertRaises(ModelError):
            evaluate_sequential(parse_model(m), b, 'left')

    def test_impossible_component_cannot_gain_tiny_joint_mass(self):
        m, b = rare_model(component_probability=0)
        with self.assertRaises(ModelError):
            evaluate_sequential(parse_model(m), b, 'left')

    def test_coherent_rare_event_does_not_justify_expensive_followup(self):
        m, b = rare_model()
        r = evaluate_sequential(parse_model(m), b, 'left')
        self.assertEqual(r['conservative_policy']['probability_acquire_second'], 0)
        self.assertAlmostEqual(r['conservative_policy']['net_value'], -1)
        self.assertFalse(r['preferred_to_no_acquisition_at_high_cost'])

    def test_accepted_joint_roundoff_cannot_create_constant_utility_value(self):
        m = model()
        m['experiments'] = [experiment('left', .5), experiment('right', .5)]
        m['utility'] = {'fixed': {'A': 1e12, 'B': 1e12},
                        'defer': {'A': 0, 'B': 0}}
        b = xor_bundle()
        b['likelihood'] = {s: {j: .25+1e-11 for j in b['outcomes']}
                           for s in m['states']}
        r = evaluate_sequential(parse_model(m), b, 'left')
        self.assertEqual(r['conservative_policy']['probability_acquire_second'], 0)
        self.assertAlmostEqual(r['conservative_policy']['net_value'], -.1, delta=1e-3)
        self.assertFalse(r['preferred_to_no_acquisition_at_high_cost'])

    def test_selective_followup_saves_cost(self):
        m, b = selective_model()
        r = evaluate_sequential(parse_model(m), b, 'first')
        self.assertAlmostEqual(r['conservative_policy']['probability_acquire_second'], .75)
        self.assertAlmostEqual(r['conservative_policy']['net_value'], .375)
        self.assertAlmostEqual(r['upfront_joint_net']['low'], .35)
        self.assertEqual(r['conservative_policy']['policy'][0]['action'], 'STOP')

    def test_xor_requires_both(self):
        m = model(); m['experiments'] = [experiment('left', .5), experiment('right', .5)]
        r = evaluate_sequential(parse_model(m), xor_bundle(), 'left')
        self.assertAlmostEqual(r['conservative_policy']['probability_acquire_second'], 1)
        self.assertAlmostEqual(r['conservative_policy']['net_value'], .3)

    def test_expensive_second_is_skipped(self):
        m, b = selective_model(); m['experiments'][1]['cost'].update(low=2, high=2)
        r = evaluate_sequential(parse_model(m), b, 'first')
        self.assertEqual(r['conservative_policy']['probability_acquire_second'], 0)

    def test_missing_followup_still_allows_stopping(self):
        m, b = selective_model(); m['experiments'][1]['available'] = False
        m['experiments'][1]['cost'] = None
        r = evaluate_sequential(parse_model(m), b, 'first')
        self.assertEqual(r['conservative_policy']['probability_acquire_second'], 0)

    def test_unknown_cost_withheld(self):
        m, b = selective_model(); m['experiments'][1]['cost'] = None
        self.assertEqual(evaluate_sequential(parse_model(m), b, 'first')['status'], 'UNKNOWN_COST')

    def test_first_unavailable(self):
        m, b = selective_model(); m['experiments'][0]['available'] = False
        self.assertEqual(evaluate_sequential(parse_model(m), b, 'first')['status'],
                         'FIRST_OBSERVATION_UNAVAILABLE')

    def test_invalid_first_rejected(self):
        m, b = selective_model()
        with self.assertRaises(ModelError): evaluate_sequential(parse_model(m), b, 'typo')

    def test_policy_cost_sensitivity(self):
        m, b = selective_model(); m['experiments'][1]['cost']['high'] = .8
        r = evaluate_sequential(parse_model(m), b, 'first')
        self.assertEqual(r['conservative_policy']['probability_acquire_second'], 0)
        self.assertAlmostEqual(r['optimistic_policy']['probability_acquire_second'], .75)


if __name__ == '__main__': unittest.main()
