"""Strict, bounded finite-model contracts; no inferred costs or probabilities."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math


class ModelError(ValueError):
    pass


class InsufficientModelError(ModelError):
    """Required predictive/decision inputs are missing; never synthesize them."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def utc(value):
    if not isinstance(value, str):
        raise ModelError('timestamp must be text')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ModelError('invalid timestamp') from exc
    if result.tzinfo is None:
        raise ModelError('timestamp must include timezone')
    return result


def text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ModelError(f'{label} must be nonempty text, at most 500 characters')
    if value != value.strip():
        raise ModelError(f'{label} cannot have surrounding whitespace')
    return value


def number(value, label, low=-1e12, high=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelError(f'{label} must be numeric')
    # Reject arbitrary-precision JSON integers before converting them to floats.
    if not low <= value <= high or not math.isfinite(value):
        raise ModelError(f'{label} must be finite and in [{low}, {high}]')
    return float(value)


def obj(value, label, required, optional=()):
    if value is None:
        raise InsufficientModelError(f'{label} is missing')
    if not isinstance(value, dict):
        raise ModelError(f'{label} must be an object')
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if extra:
        raise ModelError(f'{label}: missing={sorted(missing)}, unknown={sorted(extra)}')
    if missing:
        raise InsufficientModelError(f'{label}: missing={sorted(missing)}')
    return value


def names(value, label, maximum):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ModelError(f'{label} must contain 1..{maximum} names')
    result = tuple(text(x, label) for x in value)
    if len(set(result)) != len(result):
        raise ModelError(f'{label} contains duplicates')
    return result


def distribution(value, keys, label):
    obj(value, label, keys)
    result = {k: number(value[k], label, 0, 1) for k in keys}
    if not math.isclose(math.fsum(result.values()), 1.0, rel_tol=0, abs_tol=1e-10):
        raise ModelError(f'{label} must sum to one')
    # Normalize only accepted floating-point roundoff, never malformed probabilities.
    total = math.fsum(result.values())
    return {k: v / total for k, v in result.items()}


@dataclass(frozen=True)
class Cost:
    low: float
    high: float
    unit: str


def cost(value, unit):
    if value is None:
        return None
    obj(value, 'cost', ('low', 'high', 'unit'))
    if value['unit'] != unit:
        raise ModelError('cost unit must equal utility unit; explicit conversion required')
    low, high = number(value['low'], 'cost.low', 0), number(value['high'], 'cost.high', 0)
    if low > high:
        raise ModelError('cost.low exceeds cost.high')
    return Cost(low, high, unit)


@dataclass(frozen=True)
class Experiment:
    id: str
    outcomes: tuple
    likelihood: dict
    cost: Cost | None
    available: bool
    reference: str


@dataclass(frozen=True)
class DecisionModel:
    id: str
    states: tuple
    actions: tuple
    prior: dict
    utility: dict
    unit: str
    experiments: tuple
    provenance: dict
    model_hash: str


def parse_model(raw):
    obj(raw, 'model', ('schema_version', 'id', 'states', 'prior', 'utility',
                       'utility_unit', 'experiments', 'provenance'),
        ('execution_authorized',))
    if raw['schema_version'] != 'atlas.decision.v1':
        raise ModelError('unsupported decision schema')
    if raw.get('execution_authorized', False) is not False:
        raise ModelError('Atlas cannot authorize execution')
    mid, unit = text(raw['id'], 'model.id'), text(raw['utility_unit'], 'utility_unit')
    states = names(raw['states'], 'states', 128)
    prior = distribution(raw['prior'], states, 'prior')
    if not isinstance(raw['utility'], dict):
        raise ModelError('utility must be an object')
    actions = names(list(raw['utility']), 'actions', 64)
    if 'defer' not in actions:
        raise ModelError('an explicit defer action is required')
    utility = {}
    for action in actions:
        obj(raw['utility'][action], f'utility.{action}', states)
        utility[action] = {s: number(raw['utility'][action][s], 'utility') for s in states}
    obj(raw['provenance'], 'provenance', ('kind', 'reference'))
    if raw['provenance']['kind'] not in ('synthetic', 'owner_supplied'):
        raise ModelError('provenance.kind must be synthetic or owner_supplied')
    provenance = dict(raw['provenance'])
    text(provenance['reference'], 'provenance.reference')
    rows = raw['experiments']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 64:
        raise ModelError('experiments must contain 1..64 entries')
    experiments, seen, work = [], set(), 0
    for row in rows:
        obj(row, 'experiment', ('id', 'outcomes', 'likelihood', 'cost', 'available', 'reference'))
        eid = text(row['id'], 'experiment.id')
        if eid in seen:
            raise ModelError('duplicate experiment id')
        seen.add(eid)
        outcomes = names(row['outcomes'], 'outcomes', 256)
        work += len(states) * len(actions) * len(outcomes)
        if work > 2_000_000:
            raise ModelError('model exceeds 2,000,000 evaluation cells')
        obj(row['likelihood'], 'likelihood', states)
        likelihood = {s: distribution(row['likelihood'][s], outcomes, f'likelihood.{s}')
                      for s in states}
        if type(row['available']) is not bool:
            raise ModelError('available must be boolean')
        experiments.append(Experiment(eid, outcomes, likelihood, cost(row['cost'], unit),
                                      row['available'], text(row['reference'], 'reference')))
    return DecisionModel(mid, states, tuple(sorted(actions)), prior, utility, unit,
                         tuple(experiments), provenance, digest(raw))
