"""Offline, advisory decision prerequisites. No market data or execution hooks."""
import argparse
import json
from datetime import datetime


def stamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('timestamps must include timezone')
    return dt


def plan(doc, as_of):
    now = stamp(as_of)
    if doc.get('schema_version') != 1:
        raise ValueError('unsupported schema')
    if stamp(doc['snapshot_at']) > now:
        raise ValueError('snapshot is from the future')
    evidence = {}
    for row in doc['evidence']:
        key = row['id']
        if key in evidence:
            raise ValueError('duplicate evidence id')
        if row['status'] not in {'verified', 'pending', 'unknown', 'rejected'}:
            raise ValueError('invalid evidence status')
        if not row.get('owner') or not row.get('source'):
            raise ValueError('owner and source are required')
        status = row['status']
        if status == 'verified':
            if not row.get('receipt') or not row.get('valid_until'):
                raise ValueError('verified evidence needs receipt and validity boundary')
            observed = stamp(row['observed_at'])
            expiry = stamp(row['valid_until'])
            if expiry < observed:
                raise ValueError('invalid validity interval')
            if observed > now or now > expiry:
                status = 'unknown'
        evidence[key] = dict(row, effective_status=status)

    decisions, seen = [], set()
    for row in doc['decisions']:
        if row['id'] in seen:
            raise ValueError('duplicate decision id')
        seen.add(row['id'])
        if not row.get('owner') or not row.get('source') or not row.get('alternatives'):
            raise ValueError('decision needs owner, source and explicit alternatives')
        routes = []
        for alternative in row['alternatives']:
            if not alternative or len(alternative) != len(set(alternative)):
                raise ValueError('empty or duplicate prerequisite')
            if any(key not in evidence for key in alternative):
                raise ValueError('unknown prerequisite')
            if any(evidence[key]['effective_status'] == 'rejected' for key in alternative):
                continue
            routes.append(frozenset(key for key in alternative
                                   if evidence[key]['effective_status'] != 'verified'))
        minimal = sorted({r for r in routes if not any(s < r for s in routes)},
                         key=lambda r: (len(r), sorted(r)))
        decisions.append(dict(id=row['id'], owner=row['owner'], source=row['source'],
                              status=('ready_for_owner_review' if frozenset() in minimal
                                      else 'unresolved' if minimal else 'no_viable_route'),
                              missing_bundles=[sorted(r) for r in minimal]))

    bundles = {tuple(b) for d in decisions for b in d['missing_bundles'] if b}
    actions = []
    for bundle in bundles:
        supplied = set(bundle)
        unlocked = [d['id'] for d in decisions if d['status'] == 'unresolved'
                    and any(set(b) <= supplied for b in d['missing_bundles'])]
        actions.append(dict(evidence=list(bundle),
                            owners=sorted({evidence[k]['owner'] for k in bundle}),
                            would_unlock_owner_reviews=sorted(unlocked),
                            structural_impact=len(unlocked),
                            cost='unknown', recommendation='request evidence from owners'))
    actions.sort(key=lambda a: (-a['structural_impact'], len(a['evidence']), a['evidence']))
    return dict(schema_version=1, snapshot_at=doc['snapshot_at'], as_of=as_of,
                mode='advisory_metadata_only', execution_authorized=False,
                interpretation='Conditional structural impact, not probability, profit or information gain. '
                'Completing a bundle means obtaining valid evidence, not assuming a passing outcome. '
                'Ordering is an inspection aid; costs, value and feasibility remain unestimated.',
                decisions=decisions, candidate_bundles=actions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot')
    parser.add_argument('--as-of', required=True)
    args = parser.parse_args()
    with open(args.snapshot, encoding='utf-8') as stream:
        print(json.dumps(plan(json.load(stream), args.as_of), indent=2))


if __name__ == '__main__':
    main()
