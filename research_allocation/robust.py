"""Sensitivity across explicitly supplied scenarios; no guessed probabilities."""
from .contracts import ModelError, names, parse_model
from .decision import evaluate_experiment, flags


def compare_scenarios(scenarios):
    if not isinstance(scenarios, dict) or not 1 <= len(scenarios) <= 32:
        raise ModelError('scenarios must contain 1..32 named models')
    names(list(scenarios), 'scenario names', 32)
    models = {key: parse_model(raw) for key, raw in scenarios.items()}
    first = next(iter(models.values()))
    universe = {e.id for e in first.experiments}
    for model in models.values():
        if (set(model.states) != set(first.states) or model.actions != first.actions
                or model.utility != first.utility or model.unit != first.unit
                or {e.id for e in model.experiments} != universe):
            raise ModelError('scenarios must share states, actions, utilities, units and experiment IDs')
    matrix = {key: {e.id: evaluate_experiment(m, e) for e in m.experiments}
              for key, m in models.items()}
    rows, complete = {}, True
    for eid in sorted(universe):
        values = [matrix[key][eid] for key in models]
        if not all(v['available'] for v in values):
            rows[eid] = {'status': 'NOT_AVAILABLE_IN_ALL_SCENARIOS'}
            complete = False
        elif any(v['net_decision_value'] is None for v in values):
            rows[eid] = {'status': 'UNKNOWN_COST'}
            complete = False
        else:
            rows[eid] = {'status': 'ASSESSED',
                         'worst_net': min(v['net_decision_value']['low'] for v in values),
                         'best_net': max(v['net_decision_value']['high'] for v in values)}
    assessed = [e for e in rows if rows[e]['status'] == 'ASSESSED']
    for eid in assessed:
        dominated_by = []
        for other in assessed:
            if other == eid:
                continue
            gaps = [matrix[k][other]['net_decision_value']['low'] -
                    matrix[k][eid]['net_decision_value']['high'] for k in models]
            if all(g >= -1e-10 for g in gaps) and any(g > 1e-10 for g in gaps):
                dominated_by.append(other)
        # Conservative range regret with no-acquisition option 0; self cannot regret itself.
        regret = max(max([0.0] + [matrix[k][o]['net_decision_value']['high']
                                  for o in assessed if o != eid]) -
                     matrix[k][eid]['net_decision_value']['low'] for k in models)
        rows[eid].update({'dominated_by': dominated_by, 'worst_regret_bound': max(0.0, regret)})
    positive = [e for e in assessed if rows[e]['worst_net'] > 1e-10]
    best = max((rows[e]['worst_net'] for e in positive), default=0)
    choices = [e for e in positive if abs(rows[e]['worst_net'] - best) <= 1e-10]
    return {'schema_version': 'atlas.sensitivity.v1',
            'status': 'COMPLETE_SUPPLIED_SCENARIOS' if complete else 'INCOMPLETE_COMPARISON',
            'scenario_hashes': {k: m.model_hash for k, m in models.items()},
            'experiments': rows, 'scenario_results': matrix,
            'conditional_maximin_choices': choices,
            'recommendation': choices if complete and choices else ['DEFER'],
            'limits': 'Scenario sensitivity, not a probability distribution or confidence interval. '
                      'Comparison requires a common utility scale; unassessed alternatives block a complete recommendation.',
            **flags()}
