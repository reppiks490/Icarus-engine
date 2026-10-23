"""Local prospective records with transactions and a tamper-evident hash chain.

The local clock and SQLite file are not independent attestations. A user who can
rewrite every hash can rewrite history; externally anchor exports when required.
"""
from datetime import datetime, timezone
import copy
import json
import math
from pathlib import Path
import sqlite3
from .contracts import ModelError, canonical, digest, number, text, utc
from .decision import evaluate, flags


class JournalError(ValueError):
    pass


def now_utc():
    return datetime.now(timezone.utc).isoformat()


class Journal:
    def __init__(self, path, *, clock=now_utc, create=True):
        self.clock = clock
        path = Path(path)
        if not create and not path.is_file():
            raise JournalError('journal does not exist')
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.db.execute('PRAGMA busy_timeout=10000')
        self.db.execute('PRAGMA journal_mode=WAL')
        if not create and not self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='atlas_events'").fetchone():
            self.db.close()
            raise JournalError('file is not an Atlas journal')
        self.db.execute('''CREATE TABLE IF NOT EXISTS atlas_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL, record_key TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL, previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL UNIQUE)''')

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _verified(self):
        previous, events = '0' * 64, []
        for seq, kind, key, raw, prev, saved in self.db.execute(
                'SELECT seq,kind,record_key,payload,previous_hash,event_hash '
                'FROM atlas_events ORDER BY seq'):
            try:
                payload = json.loads(raw)
                expected = digest({'kind': kind, 'key': key, 'payload': payload,
                                   'previous_hash': previous})
            except (ValueError, TypeError) as exc:
                raise JournalError('unreadable journal payload') from exc
            if prev != previous or expected != saved or seq != len(events) + 1:
                raise JournalError('journal integrity failure')
            previous = saved
            events.append({'seq': seq, 'kind': kind, 'key': key, 'payload': payload,
                           'event_hash': saved})
        return events

    def verify(self):
        events = self._verified()
        return self._integrity(events)

    @staticmethod
    def _integrity(events):
        return {'status': 'VALID_LOCAL_CHAIN', 'events': len(events),
                'head_hash': events[-1]['event_hash'] if events else '0' * 64,
                'external_attestation': False, **flags()}

    def _append_locked(self, kind, key, payload, events):
        current_stamp = payload.get('recorded_at', payload.get('received_at'))
        if events:
            last = events[-1]['payload']
            last_stamp = last.get('recorded_at', last.get('received_at'))
            if utc(current_stamp) < utc(last_stamp):
                raise JournalError('local clock moved backwards')
        previous = events[-1]['event_hash'] if events else '0' * 64
        event_hash = digest({'kind': kind, 'key': key, 'payload': payload,
                             'previous_hash': previous})
        self.db.execute('INSERT INTO atlas_events '
                        '(kind,record_key,payload,previous_hash,event_hash) VALUES(?,?,?,?,?)',
                        (kind, key, canonical(payload), previous, event_hash))
        return {'idempotent': False, 'payload': payload, 'event_hash': event_hash, **flags()}

    def register(self, record_id, model, experiment_id, expires_at):
        text(record_id, 'record_id')
        frozen_model = copy.deepcopy(model)
        analysis = evaluate(frozen_model)
        candidate = next((x for x in analysis['experiments']
                          if x['experiment_id'] == experiment_id), None)
        if candidate is None or not candidate['available']:
            raise JournalError('experiment is unknown or unavailable')
        if candidate['net_decision_value'] is None:
            raise JournalError('unknown cost cannot be registered as an assessed recommendation')
        utc(expires_at)
        semantic = {'record_id': record_id, 'model': frozen_model,
                    'model_hash': analysis['model_hash'], 'experiment_id': experiment_id,
                    'expires_at': expires_at, 'predicted': candidate}
        key = 'recommendation:' + record_id
        self.db.execute('BEGIN IMMEDIATE')
        try:
            events = self._verified()
            prior = next((e for e in events if e['key'] == key), None)
            if prior:
                old = {k: v for k, v in prior['payload'].items() if k != 'recorded_at'}
                if canonical(old) != canonical(semantic):
                    raise JournalError('record id already has different content')
                result = {'idempotent': True, 'payload': prior['payload'],
                          'event_hash': prior['event_hash'], **flags()}
            else:
                stamp = self.clock()
                if utc(expires_at) <= utc(stamp):
                    raise JournalError('expiry must be in the future')
                result = self._append_locked('recommendation', key,
                                             dict(semantic, recorded_at=stamp), events)
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def observe(self, record_id, outcome, observed_at, actual_cost, unit):
        text(record_id, 'record_id')
        text(outcome, 'outcome')
        observed = utc(observed_at)
        amount = number(actual_cost, 'actual_cost', 0)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            events = self._verified()
            rec = next((e['payload'] for e in events
                        if e['key'] == 'recommendation:' + record_id), None)
            if rec is None:
                raise JournalError('unknown recommendation')
            if observed <= utc(rec['recorded_at']):
                raise JournalError('outcome must be strictly after local registration')
            if observed > utc(rec['expires_at']):
                raise JournalError('outcome is outside registered validity window')
            predicted = rec['predicted']
            if unit != predicted['utility_unit']:
                raise JournalError('actual cost unit differs from registered utility unit')
            policy = next((r for r in predicted['outcome_policy'] if r['outcome'] == outcome), None)
            if policy is None:
                raise JournalError('outcome is outside the frozen outcome vocabulary')
            probabilities = {r['outcome']: r['probability'] for r in predicted['outcome_policy']}
            p = probabilities[outcome]
            # Explicit model failure avoids serializing infinity for a zero-probability event.
            payload = {'record_id': record_id, 'outcome': outcome, 'observed_at': observed_at,
                       'actual_cost': amount, 'unit': unit,
                       'outcome_probability': p,
                       'status': 'MODEL_CONTRADICTION' if p == 0 else 'OBSERVED',
                       'log_loss_bits': None if p == 0 else -math.log2(p),
                       'brier_score': math.fsum((v - (k == outcome)) ** 2
                                                for k, v in probabilities.items()),
                       'cost_above_registered_range': amount > predicted['cost']['high'],
                       'recommended_actions_under_model': policy['best_actions'],
                       'decision_benefit_proven': False}
            key = 'outcome:' + record_id
            prior = next((e for e in events if e['key'] == key), None)
            if prior:
                old = {k: v for k, v in prior['payload'].items() if k != 'received_at'}
                if canonical(old) != canonical(payload):
                    raise JournalError('outcome already recorded with different content')
                result = {'idempotent': True, 'payload': prior['payload'],
                          'event_hash': prior['event_hash'], **flags()}
            else:
                now = self.clock()
                if observed > utc(now):
                    raise JournalError('outcome cannot be from the future')
                result = self._append_locked('outcome', key, dict(payload, received_at=now), events)
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def report(self):
        events = self._verified()
        recommendations = {e['payload']['record_id']: e['payload'] for e in events
                           if e['kind'] == 'recommendation'}
        outcomes = {e['payload']['record_id']: e['payload'] for e in events if e['kind'] == 'outcome'}
        finite_losses = [v['log_loss_bits'] for v in outcomes.values() if v['log_loss_bits'] is not None]
        now = utc(self.clock())
        unresolved = sorted(set(recommendations) - set(outcomes))
        return {'schema_version': 'atlas.journal_report.v1', 'integrity': self._integrity(events),
                'registered': len(recommendations), 'observed': len(outcomes),
                'unresolved_ids': unresolved,
                'expired_unresolved_ids': [k for k in unresolved
                                           if utc(recommendations[k]['expires_at']) < now],
                'model_contradictions': sum(v['status'] == 'MODEL_CONTRADICTION'
                                            for v in outcomes.values()),
                'mean_brier_score': (math.fsum(v['brier_score'] for v in outcomes.values()) /
                                     len(outcomes)) if outcomes else None,
                'mean_finite_log_loss_bits': (math.fsum(finite_losses) / len(finite_losses)
                                              if finite_losses else None),
                'finite_log_loss_count': len(finite_losses),
                'cost_overruns': sum(v['cost_above_registered_range'] for v in outcomes.values()),
                'decision_benefit_proven': False,
                'limits': 'Predictive scoring only. Contradictions remain counted separately. '
                          'No counterfactual realized benefit or external timestamp attestation.', **flags()}

    def export(self):
        events = self._verified()
        return {'schema_version': 'atlas.journal_export.v1', 'integrity': self._integrity(events),
                'events': events, **flags()}
