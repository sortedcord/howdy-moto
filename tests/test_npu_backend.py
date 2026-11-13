import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('backend', ROOT / 'src/npu/backend.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class MatchingTests(unittest.TestCase):
    def test_gate_needs_count_and_elapsed_time(self):
        gate = backend.MatchGate()
        self.assertFalse(gate.update(True, 0))
        self.assertFalse(gate.update(True, 0.1))
        self.assertFalse(gate.update(True, 0.2))
        self.assertTrue(gate.update(True, 0.3))

    def test_mismatch_resets_gate(self):
        gate = backend.MatchGate()
        gate.update(True, 0)
        gate.update(True, 0.2)
        self.assertFalse(gate.update(False, 0.3))
        self.assertFalse(gate.update(True, 0.5))
        self.assertFalse(gate.update(True, 0.8))
        self.assertTrue(gate.update(True, 0.9))

    def test_only_two_matches_not_enough(self):
        gate = backend.MatchGate()
        self.assertFalse(gate.update(True, 0))
        self.assertFalse(gate.update(True, 1))

    def test_invalid_templates_fail(self):
        for rows in ([], [[0] * 256], [[float('nan')] * 256], [[1] * 128]):
            with self.assertRaises(ValueError):
                backend.templates({'profiles': [{'label': 'bad', 'embeddings': rows}]})

    def test_score_and_labels(self):
        a = np.eye(256, dtype=np.float32)[0]
        b = np.eye(256, dtype=np.float32)[1]
        data, labels = backend.templates({'profiles': [
            {'label': 'a', 'embeddings': [a.tolist()]},
            {'label': 'b', 'embeddings': [b.tolist()]},
        ]})
        value, index = backend.score(b, data)
        self.assertEqual(value, 1)
        self.assertEqual(labels[index], 'b')


class DispatchTests(unittest.TestCase):
    def run_dispatch(self, enabled):
        source = (ROOT / 'config/compare.py.patched').read_text()
        prefix = source.split('# Import time so we can start timing asap')[0]
        def read_config(config, *_):
            config.read_dict({'npu': {'enabled': enabled}})
        with patch('configparser.ConfigParser.read', read_config), \
             patch('sys.argv', ['compare.py', 'exampleuser']), \
             patch('os.execv', side_effect=OSError('simulated exec failure')) as execute:
            try:
                exec(compile(prefix, 'dispatch', 'exec'), {})
            except SystemExit as exc:
                return execute.call_args, exc.code
            return execute.call_args, None

    def test_enabled_dispatch_uses_isolated_python_and_fails_closed(self):
        call, code = self.run_dispatch('true')
        self.assertEqual(code, 12)
        self.assertEqual(call.args, ('/usr/bin/python', [
            '/usr/bin/python', '-I', '/usr/local/lib/howdy-npu/backend.py',
            'auth', '--user', 'exampleuser']))

    def test_disabled_dispatch_preserves_legacy(self):
        call, code = self.run_dispatch('false')
        self.assertIsNone(call)
        self.assertIsNone(code)

    def test_malformed_toggle_fails_closed(self):
        call, code = self.run_dispatch('invalid')
        self.assertIsNone(call)
        self.assertEqual(code, 12)


if __name__ == '__main__':
    unittest.main()
