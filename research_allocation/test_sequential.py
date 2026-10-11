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


class SequentialTests(unittest.TestCase):
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
