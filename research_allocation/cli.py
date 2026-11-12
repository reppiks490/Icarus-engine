"""Offline Atlas CLI: validate, evaluate, compare, and record prospective evidence."""
import argparse
import json
import sys
import sqlite3
from .bundles import evaluate_bundle
from .contracts import InsufficientModelError, ModelError, parse_model
from .decision import evaluate, flags
from .journal import Journal, JournalError
from .robust import compare_scenarios
from .sequential import evaluate_sequential
from .handoff import prepare_handoff


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ModelError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ModelError('non-finite JSON constant: ' + value)
    with open(path, encoding='utf-8') as stream:
        value = stream.read(4_000_001)
    if len(value) > 4_000_000:
        raise ModelError('input exceeds 4 MB text limit')
    return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for command in ('validate', 'evaluate'):
        sub = subs.add_parser(command); sub.add_argument('model')
    sub = subs.add_parser('bundle'); sub.add_argument('model'); sub.add_argument('bundle')
    sub = subs.add_parser('sequential')
    sub.add_argument('model'); sub.add_argument('bundle'); sub.add_argument('first')
    sub = subs.add_parser('handoff')
    for arg in ('model', 'owner', 'as_of', 'source_revision'): sub.add_argument(arg)
    sub = subs.add_parser('compare'); sub.add_argument('scenarios')
    sub = subs.add_parser('register')
    for arg in ('database', 'record_id', 'model', 'experiment_id', 'expires_at'):
        sub.add_argument(arg)
    sub = subs.add_parser('observe')
    for arg in ('database', 'record_id', 'outcome', 'observed_at', 'unit'):
        sub.add_argument(arg)
    sub.add_argument('actual_cost', type=float)
    for command in ('report', 'export', 'verify-journal'):
        sub = subs.add_parser(command); sub.add_argument('database')
    args = parser.parse_args(argv)
    try:
        if args.command == 'validate':
            m = parse_model(read_json(args.model))
            result = {'status': 'VALID_FINITE_MODEL', 'model_hash': m.model_hash,
                      'market_validated': False, **flags()}
        elif args.command == 'evaluate':
            result = evaluate(read_json(args.model))
        elif args.command == 'bundle':
            result = evaluate_bundle(parse_model(read_json(args.model)), read_json(args.bundle))
        elif args.command == 'compare':
            result = compare_scenarios(read_json(args.scenarios))
        elif args.command == 'sequential':
            result = evaluate_sequential(parse_model(read_json(args.model)),
                                         read_json(args.bundle), args.first)
        elif args.command == 'handoff':
            result = prepare_handoff(read_json(args.model), owner=args.owner, as_of=args.as_of,
                                     source_revision=args.source_revision)
        else:
            with Journal(args.database, create=args.command == 'register') as journal:
                if args.command == 'register':
                    result = journal.register(args.record_id, read_json(args.model),
                                              args.experiment_id, args.expires_at)
                elif args.command == 'observe':
                    result = journal.observe(args.record_id, args.outcome, args.observed_at,
                                             args.actual_cost, args.unit)
                elif args.command == 'report': result = journal.report()
                elif args.command == 'export': result = journal.export()
                else: result = journal.verify()
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (ModelError, JournalError, OSError, ValueError, sqlite3.Error) as exc:
        status = 'INSUFFICIENT_MODEL' if isinstance(exc, InsufficientModelError) else 'ERROR'
        print(json.dumps({'status': status, 'reason': str(exc), **flags()}),
              file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
