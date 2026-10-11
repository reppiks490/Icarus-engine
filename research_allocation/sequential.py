"""Two-stage observation policy under an explicit joint model.

Optimizes stop/continue decisions, not trades. Costs are fixed per acquisition
and nonnegative. No independence, adaptive likelihood fitting, or free retries.
"""
import math
from .bundles import _validated_bundle
from .contracts import ModelError
from .decision import _best, evaluate_experiment, flags


def evaluate_sequential(model, bundle, first):
    joint, members, known = _validated_bundle(model, bundle)
    joint_result = evaluate_experiment(model, joint)
    if len(members) != 2 or first not in members:
        raise ModelError('sequential policy requires exactly two members and a valid first ID')
    second = next(m for m in members if m != first)
    e1, e2 = known[first], known[second]
    base = joint_result['baseline_expected_utility']
    if not e1.available:
        return {'status': 'FIRST_OBSERVATION_UNAVAILABLE', 'first': first,
                'second': second, **flags()}
    if e1.cost is None or (e2.available and e2.cost is None):
        return {'status': 'UNKNOWN_COST', 'first': first, 'second': second, **flags()}
    # Every stage consumes the same normalized joint, including its marginal.
    # Multiplying before summation also keeps subnormal branch weights coherent.
    joint_weights = {j: {s: model.prior[s] * joint.likelihood[s][j] for s in model.states}
                     for j in joint.outcomes}
    upper = joint_result['perfect_information_bound']
    value_tolerance = max(1e-10, 32 * math.ulp(max(1.0, abs(base), abs(base+upper))))

    def solve(cost_field):
        first_cost = getattr(e1.cost, cost_field)
        second_cost = getattr(e2.cost, cost_field) if e2.available else 0.0
        rows, value_terms, follow_terms = [], [], []
        for outcome in e1.outcomes:
            first_labels = [j for j in joint.outcomes if bundle['outcomes'][j][first] == outcome]
            first_weights = {s: math.fsum(joint_weights[j][s] for j in first_labels)
                             for s in model.states}
            p = math.fsum(first_weights.values())
            if p == 0:
                rows.append({'first_outcome': outcome, 'probability': 0.0,
                             'action': 'UNREACHABLE', 'terminal_actions': []})
                continue
            stop_values = {a: math.fsum(first_weights[s] * model.utility[a][s]
                                        for s in model.states) / p
                           for a in model.actions}
            stop, stop_actions = _best(stop_values)
            future_terms, continuations = [], []
            for second_outcome in e2.outcomes:
                labels = [j for j, values in bundle['outcomes'].items()
                          if values[first] == outcome and values[second] == second_outcome]
                weights = {s: math.fsum(joint_weights[j][s] for j in labels) / p
                           for s in model.states}
                prob2 = math.fsum(weights.values())
                if prob2 == 0:
                    continue
                utilities = {a: math.fsum(weights[s]*model.utility[a][s] for s in model.states)
                              / prob2 for a in model.actions}
                terminal, actions = _best(utilities)
                future_terms.append(prob2 * terminal)
                continuations.append({'second_outcome': second_outcome,
                                      'conditional_probability': prob2,
                                      'terminal_actions': actions})
            after_second = math.fsum(future_terms)
            if not math.isclose(math.fsum(r['conditional_probability'] for r in continuations),
                                1.0, rel_tol=0, abs_tol=1e-12):
                raise ModelError('conditional joint probabilities must sum to one')
            tolerance = max(1e-10, 32 * math.ulp(max(1.0, abs(stop), abs(after_second),
                                                    abs(second_cost))))
            follow = e2.available and after_second - second_cost > stop + tolerance
            value_terms.append(p * (after_second - second_cost if follow else stop))
            if follow: follow_terms.append(p)
            rows.append({'first_outcome': outcome, 'probability': p,
                         'action': 'ACQUIRE_SECOND' if follow else 'STOP',
                         'stop_expected_utility': stop,
                         'followup_gross_value': max(0.0, after_second - stop),
                         'terminal_actions': [] if follow else stop_actions,
                         'continuations': continuations if follow else []})
        follow_probability = math.fsum(follow_terms)
        expected_cost = first_cost + follow_probability * second_cost
        gain_before_first_cost = math.fsum(value_terms) - base
        if gain_before_first_cost < -value_tolerance or gain_before_first_cost > upper+value_tolerance:
            raise ModelError('sequential policy value bounds violated')
        gain_before_first_cost = min(upper, max(0.0, gain_before_first_cost))
        return {'net_value': gain_before_first_cost - first_cost,
                'probability_acquire_second': follow_probability,
                'expected_acquisition_cost': expected_cost,
                'maximum_acquisition_cost': first_cost + second_cost,
                'policy': rows}

    conservative, optimistic = solve('high'), solve('low')
    # Fixed conservative policy evaluated at low costs; do not mix changing policies in this range.
    savings = e1.cost.high - e1.cost.low
    if e2.available:
        savings += conservative['probability_acquire_second'] * (e2.cost.high - e2.cost.low)
    upper_for_fixed_policy = conservative['net_value'] + savings
    return {'schema_version': 'atlas.sequential.v1', 'status': 'ASSESSED',
            'first': first, 'second': second, 'utility_unit': model.unit,
            'baseline_expected_utility': base,
            'value_roundoff_tolerance': value_tolerance,
            'conservative_policy': conservative,
            'conservative_policy_net_range': {'low': conservative['net_value'],
                                               'high': upper_for_fixed_policy},
            'optimistic_policy': optimistic,
            'preferred_to_no_acquisition_at_high_cost': conservative['net_value'] > value_tolerance,
            'upfront_joint_net': joint_result['net_decision_value'],
            'limits': 'Explicit two-observation joint model; fixed per-acquisition costs. '
                      'No learning or empirical optimality claim. Different cost endpoints may choose different policies.',
            **flags()}
