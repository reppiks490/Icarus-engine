from contextlib import redirect_stderr, redirect_stdout
import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from research_allocation.cli import main, read_json
from research_allocation.contracts import ModelError
from research_allocation.test_decision import model, experiment, xor_bundle
from research_allocation.test_sequential import selective_model


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.model_path = self.write('model.json', model())

    def tearDown(self): self.tmp.cleanup()

    def write(self, name, value):
        p = self.root/name; p.write_text(json.dumps(value), encoding='utf-8'); return str(p)

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err): code = main(list(args))
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_validate_evaluate_and_handoff(self):
        self.assertEqual(self.invoke('validate', self.model_path)[0], 0)
        code, payload = self.invoke('evaluate', self.model_path)
        self.assertEqual(code, 0); self.assertFalse(payload['provenance_verified'])
        code, payload = self.invoke('handoff', self.model_path, 'Claude',
                                    '2026-10-11T16:00:00Z', 'a'*40)
        self.assertEqual(code, 0); self.assertEqual(len(payload['handoff_hash']), 64)

    def test_sequential_and_bundle(self):
        m, b = selective_model()
        mp, bp = self.write('sequential.json', m), self.write('bundle.json', b)
        code, r = self.invoke('sequential', mp, bp, 'first')
        self.assertEqual(code, 0)
        self.assertAlmostEqual(r['conservative_policy']['net_value'], .375)
        self.assertEqual(self.invoke('bundle', mp, bp)[0], 0)

    def test_compare(self):
        p = self.write('scenarios.json', {'one': model(), 'two': model()})
        self.assertEqual(self.invoke('compare', p)[1]['recommendation'], ['signal'])

    def test_complete_cli_journal_roundtrip(self):
        db = str(self.root/'events.db')
        deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        code, record = self.invoke('register', db, 'r1', self.model_path, 'signal', deadline)
        self.assertEqual(code, 0)
        observed = datetime.now(timezone.utc).isoformat()
        code, row = self.invoke('observe', db, 'r1', 'a', observed, 'synthetic_utility', '.1')
        self.assertEqual(code, 0, row)
        self.assertEqual(self.invoke('report', db)[1]['observed'], 1)
        self.assertEqual(len(self.invoke('export', db)[1]['events']), 2)
        self.assertEqual(self.invoke('verify-journal', db)[1]['events'], 2)

    def test_missing_journal_is_not_created(self):
        path = self.root/'missing.db'
        code, _ = self.invoke('report', str(path))
        self.assertEqual(code, 2); self.assertFalse(path.exists())

    def test_duplicate_json_key_rejected(self):
        p = self.root/'bad.json'; p.write_text('{"a":1,"a":2}')
        with self.assertRaises(ModelError): read_json(p)

    def test_nonfinite_json_rejected(self):
        p = self.root/'bad.json'; p.write_text('{"a":NaN}')
        self.assertEqual(self.invoke('evaluate', str(p))[0], 2)

    def test_malformed_input_is_error_json(self):
        p = self.root/'bad.json'; p.write_text('{')
        code, r = self.invoke('evaluate', str(p))
        self.assertEqual(code, 2); self.assertEqual(r['status'], 'ERROR')

    def test_oversized_json_integer_has_structured_error(self):
        for field in ('utility', 'prior', 'cost'):
            with self.subTest(field=field):
                raw = model()
                if field == 'utility': raw['utility']['choose_A']['A'] = 10**400
                elif field == 'prior': raw['prior']['A'] = 10**400
                else: raw['experiments'][0]['cost']['low'] = 10**400
                code, payload = self.invoke('evaluate', self.write('oversized.json', raw))
                self.assertEqual(code, 2)
                self.assertEqual(payload['status'], 'ERROR')
                self.assertFalse(payload['execution_authorized'])
                self.assertFalse(payload['production_decision_authorized'])

    def test_missing_predictive_model_is_explicitly_insufficient(self):
        for field in ('prior', 'utility', 'experiments'):
            with self.subTest(field=field):
                raw = model(); raw.pop(field)
                path = self.write('incomplete.json', raw)
                code, payload = self.invoke('evaluate', path)
                self.assertEqual(code, 2)
                self.assertEqual(payload['status'], 'INSUFFICIENT_MODEL')
                self.assertFalse(payload['execution_authorized'])
                self.assertFalse(payload['production_decision_authorized'])

    def test_missing_likelihood_is_not_inferred(self):
        raw = model(); raw['experiments'][0].pop('likelihood')
        code, payload = self.invoke('evaluate', self.write('no-likelihood.json', raw))
        self.assertEqual(code, 2)
        self.assertEqual(payload['status'], 'INSUFFICIENT_MODEL')

    def test_cli_validation_keeps_both_authority_flags_false(self):
        code, payload = self.invoke('validate', self.model_path)
        self.assertEqual(code, 0)
        self.assertFalse(payload['execution_authorized'])
        self.assertFalse(payload['production_decision_authorized'])

    def test_python_module_entrypoint(self):
        result = subprocess.run([sys.executable, '-m', 'research_allocation', 'evaluate',
                                 self.model_path], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['schema_version'], 'atlas.analysis.v1')


if __name__ == '__main__': unittest.main()
