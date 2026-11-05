import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from research_allocation.journal import Journal, JournalError
from research_allocation.contracts import digest
from research_allocation.test_decision import model


START = '2026-10-11T16:00:00Z'
OBSERVED = '2026-10-11T16:01:00Z'
RECEIVED = '2026-10-11T16:02:00Z'
EXPIRES = '2026-10-12T16:00:00Z'


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'journal.sqlite'
        self.now = START
        self.j = Journal(self.path, clock=lambda: self.now)

    def tearDown(self):
        self.j.close(); self.tmp.cleanup()

    def register(self):
        return self.j.register('r1', model(), 'signal', EXPIRES)

    def observe(self):
        self.now = RECEIVED
        return self.j.observe('r1', 'a', OBSERVED, .1, 'synthetic_utility')

    def after_write_lock_delay(self, operation, stamp, *, intervening=False, during_delay=None):
        ready, start, attempted, release = (threading.Event() for _ in range(4))
        values, errors = [], []

        def worker():
            try:
                with Journal(self.path, clock=lambda: self.now) as journal:
                    def trace(sql):
                        if sql == 'BEGIN IMMEDIATE':
                            attempted.set()
                            if not release.wait(timeout=5):
                                raise RuntimeError('test transaction was not released')
                    journal.db.set_trace_callback(trace)
                    ready.set()
                    if not start.wait(timeout=5):
                        raise RuntimeError('test worker was not started')
                    values.append(operation(journal))
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(ready.wait(timeout=5))
            self.j.db.execute('BEGIN IMMEDIATE')
            start.set()
            self.assertTrue(attempted.wait(timeout=5))
            self.now = stamp
            if during_delay is not None:
                during_delay()
            self.j.db.execute('COMMIT')
            if intervening:
                self.j.register('intervening', model(), 'signal', EXPIRES)
        finally:
            if self.j.db.in_transaction:
                self.j.db.execute('ROLLBACK')
            start.set()
            release.set()
            thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        return values, errors

    def test_registration_freezes_same_model_snapshot_as_prediction(self):
        raw = model()
        original = copy.deepcopy(raw)
        def mutate():
            raw['prior'].update(A=.6, B=.4)
            raw['experiments'][0]['cost'].update(low=.8, high=.8)
        values, errors = self.after_write_lock_delay(
            lambda j: j.register('r1', raw, 'signal', EXPIRES), RECEIVED,
            during_delay=mutate)
        self.assertFalse(errors, errors)
        payload = values[0]['payload']
        self.assertEqual(payload['model'], original)
        self.assertEqual(payload['model_hash'], digest(payload['model']))
        self.assertEqual(payload['predicted']['cost']['high'],
                         payload['model']['experiments'][0]['cost']['high'])

    def test_registration_expiry_checked_after_write_lock_delay(self):
        values, errors = self.after_write_lock_delay(
            lambda j: j.register('r1', model(), 'signal', '2026-10-11T16:00:01Z'),
            '2026-10-11T16:00:02Z')
        self.assertEqual(values, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], JournalError)
        self.assertEqual(self.j.verify()['events'], 0)

    def test_registration_is_not_backdated_before_lock_acquisition(self):
        stamp = '2026-10-11T16:00:02Z'
        values, errors = self.after_write_lock_delay(
            lambda j: j.register('r1', model(), 'signal', EXPIRES), stamp)
        self.assertFalse(errors, errors)
        self.assertEqual(values[0]['payload']['recorded_at'], stamp)
        with self.assertRaises(JournalError):
            self.j.observe('r1', 'a', '2026-10-11T16:00:00.5Z', .1, 'synthetic_utility')

    def test_intervening_writer_does_not_cause_false_clock_reversal(self):
        stamp = '2026-10-11T16:00:02Z'
        values, errors = self.after_write_lock_delay(
            lambda j: j.register('r1', model(), 'signal', EXPIRES), stamp,
            intervening=True)
        self.assertFalse(errors, errors)
        self.assertEqual(values[0]['payload']['recorded_at'], stamp)
        self.assertEqual(self.j.verify()['events'], 2)

    def test_outcome_receipt_time_sampled_after_write_lock_delay(self):
        self.register()
        self.now = OBSERVED
        values, errors = self.after_write_lock_delay(
            lambda j: j.observe('r1', 'a', '2026-10-11T16:00:30Z', .1,
                                'synthetic_utility'), RECEIVED)
        self.assertFalse(errors, errors)
        self.assertEqual(values[0]['payload']['received_at'], RECEIVED)

    def test_full_prospective_lifecycle(self):
        self.register(); observed = self.observe()
        self.assertAlmostEqual(observed['payload']['log_loss_bits'], 1)
        self.assertAlmostEqual(observed['payload']['brier_score'], .5)
        self.assertEqual(self.j.verify()['events'], 2)
        r = self.j.report()
        self.assertEqual(r['observed'], 1)
        self.assertFalse(r['decision_benefit_proven'])

    def test_identical_retry_idempotent(self):
        self.register(); self.assertTrue(self.register()['idempotent'])
        self.observe(); self.assertTrue(self.observe()['idempotent'])
        self.assertEqual(self.j.verify()['events'], 2)

    def test_different_model_same_id_rejected(self):
        self.register(); other = model(); other['prior'] = {'A': .6, 'B': .4}
        with self.assertRaises(JournalError): self.j.register('r1', other, 'signal', EXPIRES)

    def test_different_outcome_same_id_rejected(self):
        self.register(); self.observe()
        with self.assertRaises(JournalError):
            self.j.observe('r1', 'b', OBSERVED, .1, 'synthetic_utility')

    def test_unknown_record_rejected(self):
        with self.assertRaises(JournalError): self.observe()

    def test_retrospective_outcome_rejected(self):
        self.register(); self.now = RECEIVED
        for t in [START, '2026-10-11T15:59:00Z']:
            with self.assertRaises(JournalError):
                self.j.observe('r1', 'a', t, .1, 'synthetic_utility')

    def test_future_or_expired_outcome_rejected(self):
        self.register(); self.now = RECEIVED
        with self.assertRaises(JournalError):
            self.j.observe('r1', 'a', EXPIRES, .1, 'synthetic_utility')
        self.now = '2026-10-14T00:00:00Z'
        with self.assertRaises(JournalError):
            self.j.observe('r1', 'a', '2026-10-13T00:00:00Z', .1, 'synthetic_utility')

    def test_unknown_cost_cannot_be_assessed_registration(self):
        m = model(); m['experiments'][0]['cost'] = None
        with self.assertRaises(JournalError): self.j.register('r1', m, 'signal', EXPIRES)

    def test_zero_probability_outcome_is_model_contradiction(self):
        m = model(); m['prior'] = {'A': 1, 'B': 0}
        self.j.register('r1', m, 'signal', EXPIRES); self.now = RECEIVED
        out = self.j.observe('r1', 'b', OBSERVED, .1, 'synthetic_utility')
        self.assertEqual(out['payload']['status'], 'MODEL_CONTRADICTION')
        self.assertIsNone(out['payload']['log_loss_bits'])
        self.assertEqual(self.j.report()['model_contradictions'], 1)
        json.dumps(self.j.report(), allow_nan=False)

    def test_tampering_detected_and_no_further_append(self):
        self.register()
        self.j.db.execute("UPDATE atlas_events SET payload='{}'")
        with self.assertRaises(JournalError): self.j.verify()
        with self.assertRaises(JournalError): self.observe()
        self.assertEqual(self.j.db.execute('SELECT COUNT(*) FROM atlas_events').fetchone()[0], 1)

    def test_clock_reversal_rejected(self):
        self.register(); self.now = '2026-10-11T15:00:00Z'
        with self.assertRaises(JournalError):
            self.j.register('r2', model(), 'signal', EXPIRES)

    def test_unresolved_records_counted_after_expiry(self):
        self.register(); self.now = '2026-10-13T00:00:00Z'
        self.assertEqual(self.j.report()['expired_unresolved_ids'], ['r1'])
        self.assertTrue(self.register()['idempotent'])

    def test_cost_overrun_recorded(self):
        self.register(); self.now = RECEIVED
        self.j.observe('r1', 'a', OBSERVED, .5, 'synthetic_utility')
        self.assertEqual(self.j.report()['cost_overruns'], 1)

    def test_bad_outcome_and_wrong_unit_rejected(self):
        self.register(); self.now = RECEIVED
        for outcome, unit in [('typo', 'synthetic_utility'), ('a', 'USD')]:
            with self.assertRaises(JournalError):
                self.j.observe('r1', outcome, OBSERVED, .1, unit)

    def test_reopen_and_export(self):
        self.register(); self.observe()
        with Journal(self.path) as reopened:
            export = reopened.export()
            self.assertEqual(len(export['events']), 2)
            self.assertEqual(export['integrity']['head_hash'], export['events'][-1]['event_hash'])

    def test_concurrent_same_registration_is_one_record(self):
        errors, values = [], []
        barrier = threading.Barrier(4)
        def worker():
            try:
                with Journal(self.path, clock=lambda: START) as j:
                    barrier.wait(timeout=5)
                    values.append(j.register('same', model(), 'signal', EXPIRES))
            except BaseException as exc: errors.append(exc)
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertFalse(errors, errors)
        self.assertEqual(sum(not v['idempotent'] for v in values), 1)
        self.assertEqual(self.j.verify()['events'], 1)


if __name__ == '__main__': unittest.main()
