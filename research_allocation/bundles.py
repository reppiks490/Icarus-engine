"""Joint observations are explicit; independence is never synthesized."""
import math
from .contracts import Cost, Experiment, ModelError, distribution, names, obj, text
from .decision import evaluate_experiment


def _validated_bundle(model, raw):
    obj(raw, 'bundle', ('id', 'members', 'outcomes', 'likelihood', 'reference'))
    bid = text(raw['id'], 'bundle.id')
    members = names(raw['members'], 'members', 8)
    known = {e.id: e for e in model.experiments}
    if len(members) < 2 or any(x not in known for x in members):
        raise ModelError('bundle needs 2..8 known experiments')
    if not isinstance(raw['outcomes'], dict):
        raise ModelError('bundle outcomes must map labels to component outcomes')
    outcomes = names(list(raw['outcomes']), 'joint outcomes', 256)
    if len(outcomes) * len(model.states) * len(model.actions) > 2_000_000:
        raise ModelError('joint model exceeds evaluation budget')
    tuples = set()
    for label in outcomes:
        mapping = raw['outcomes'][label]
        obj(mapping, 'joint observation', members)
        if any(mapping[m] not in known[m].outcomes for m in members):
            raise ModelError('unknown component outcome')
        values = tuple(mapping[m] for m in members)
        if values in tuples:
            raise ModelError('duplicate joint outcome tuple')
        tuples.add(values)
    obj(raw['likelihood'], 'joint likelihood', model.states)
    likelihood = {s: distribution(raw['likelihood'][s], outcomes, 'joint row')
                  for s in model.states}
    for state in model.states:
        for member in members:
            for outcome in known[member].outcomes:
                marginal = math.fsum(likelihood[state][j] for j in outcomes
                                    if raw['outcomes'][j][member] == outcome)
                if not math.isclose(marginal, known[member].likelihood[state][outcome],
                                    rel_tol=1e-10, abs_tol=0):
                    raise ModelError('joint likelihood contradicts component marginal')
    costs = [known[m].cost for m in members]
    total_cost = None if any(c is None for c in costs) else Cost(
        math.fsum(c.low for c in costs), math.fsum(c.high for c in costs), model.unit)
    joint = Experiment(bid, outcomes, likelihood, total_cost,
                       all(known[m].available for m in members), text(raw['reference'], 'reference'))
    return joint, members, known


def evaluate_bundle(model, raw):
    joint, members, known = _validated_bundle(model, raw)
    result = evaluate_experiment(model, joint)
    singles = {m: evaluate_experiment(model, known[m])['gross_decision_value'] for m in members}
    result.update({'members': list(members), 'joint_outcomes': raw['outcomes'],
                   'single_gross_values': singles,
                   'complementarity_vs_sum': result['gross_decision_value'] - math.fsum(singles.values()),
                   'increment_over_best_single': result['gross_decision_value'] - max(singles.values()),
                   'cost_assumption': 'All member costs charged; no adaptive stopping or discount assumed.'})
    return result
