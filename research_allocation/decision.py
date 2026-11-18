"""Exact finite expectation under an explicit model, not empirical edge estimation."""
import math
from .contracts import DecisionModel, Experiment, parse_model


def flags():
    return {'execution_authorized': False, 'production_decision_authorized': False}


def _best(values):
    optimum = max(values.values())
    # Absolute roundoff only; don't turn economically distinct choices into broad ties.
    tolerance = max(1e-12, 8 * math.ulp(max(1.0, abs(optimum))))
    return optimum, sorted(a for a, v in values.items() if optimum - v <= tolerance)


def evaluate_experiment(model: DecisionModel, exp: Experiment):
    action_values = {a: math.fsum(model.prior[s] * model.utility[a][s] for s in model.states)
                     for a in model.actions}
    baseline, baseline_actions = _best(action_values)
    perfect = math.fsum(model.prior[s] * max(model.utility[a][s] for a in model.actions)
                        for s in model.states)
    after_terms, information_terms, rows = [], [], []
    changed = []
    for outcome in exp.outcomes:
        joints = {s: model.prior[s] * exp.likelihood[s][outcome] for s in model.states}
        probability = math.fsum(joints.values())
        if probability == 0:
            rows.append({'outcome': outcome, 'probability': 0.0, 'posterior': None,
                         'best_actions': [], 'posterior_utility': None})
            continue
        posterior = {s: joints[s] / probability for s in model.states}
        weighted = {a: math.fsum(joints[s] * model.utility[a][s] for s in model.states)
                    for a in model.actions}
        conditional = {a: value / probability for a, value in weighted.items()}
        best, actions = _best(conditional)
        after_terms.append(best * probability)
        if not set(actions).intersection(baseline_actions):
            changed.append(probability)
        for state in model.states:
            if joints[state] > 0:
                information_terms.append(joints[state] * (math.log2(
                    exp.likelihood[state][outcome]) - math.log2(probability)))
        rows.append({'outcome': outcome, 'probability': probability, 'posterior': posterior,
                     'best_actions': actions, 'posterior_utility': best})
    after = math.fsum(after_terms)
    tolerance = max(1e-10, 32 * math.ulp(max(1.0, abs(after), abs(baseline), abs(perfect))))
    gross, upper = after - baseline, perfect - baseline
    if gross < -tolerance or gross > upper + tolerance:
        raise ArithmeticError('information-value bounds violated')
    gross, upper = max(0.0, gross), max(0.0, upper)
    gross = min(gross, upper)
    indistinguishable = []
    for i, left in enumerate(model.states):
        for right in model.states[i + 1:]:
            if all(math.isclose(exp.likelihood[left][o], exp.likelihood[right][o],
                                rel_tol=0, abs_tol=1e-12) for o in exp.outcomes):
                indistinguishable.append([left, right])
    net = None if exp.cost is None else {'low': gross - exp.cost.high,
                                         'high': gross - exp.cost.low}
    status = ('UNAVAILABLE' if not exp.available else 'UNKNOWN_COST' if net is None
              else 'POSITIVE_ACROSS_COST_RANGE' if net['low'] > tolerance
              else 'NONPOSITIVE_ACROSS_COST_RANGE' if net['high'] <= tolerance
              else 'COST_SENSITIVE')
    return {'experiment_id': exp.id, 'status': status, 'available': exp.available,
            'utility_unit': model.unit, 'baseline_expected_utility': baseline,
            'baseline_actions': baseline_actions, 'action_values': action_values,
            'expected_utility_after_observation': after,
            'gross_decision_value': gross, 'perfect_information_bound': upper,
            'net_decision_value': net, 'cost': None if exp.cost is None else vars(exp.cost),
            'mutual_information_bits': max(0.0, math.fsum(information_terms)),
            'probability_requires_action_change': math.fsum(changed),
            'indistinguishable_state_pairs': indistinguishable,
            'outcome_policy': rows, 'reference': exp.reference,
            'interpretation': 'Exact under supplied finite assumptions; not validated market value.',
            **flags()}


def evaluate(raw):
    model = parse_model(raw)
    experiments = [evaluate_experiment(model, e) for e in model.experiments]
    return {'schema_version': 'atlas.analysis.v1', 'model_id': model.id,
            'model_hash': model.model_hash, 'provenance': model.provenance,
            'provenance_verified': False, 'experiments': experiments, **flags()}
