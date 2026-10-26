"""Exercise extra native UI gate failures and its source-bound package proof."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bogo_home_gate as gate


class PdfHomeGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        self.source = self.root / 'source'
        self.fonts = self.root / 'fonts'
        self.work.mkdir()
        self.fonts.mkdir()
        for relative in gate.SOURCES:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('original home bytes\n' if relative.endswith('home.rs') else
                            '\n'.join('#[test]\nfn ' + name + '() {}' for name in gate.TESTS), encoding='utf-8')
        self.lock = {'id': 'pdf', 'rust': '1.95.0'}
        self.platform = 'macos-arm64'
        self.inputs = {'sourceTreeSha256': 'a' * 64, 'lock': self.lock}
        self.path = self.work / ('build-' + self.platform + '.json')
        self.record = {'app': 'pdf', 'platform': self.platform, 'inputs': self.inputs,
                       'checks': {'originalCoreTests': 'passed'}, 'binaries': {'app': {'sha256': 'b' * 64}}}
        gate.full.write_json(self.path, self.record)
        self.output = ('running 2 tests\n' + '\n'.join('test ' + name + ' ... ok' for name in gate.TESTS)
                       + '\ntest result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 301 filtered out; finished in 0.25s\n')
        self.prepared = patch.object(gate.full, 'prepared', return_value=(self.work, self.source, self.fonts, self.inputs))
        self.env = patch.object(gate.full, 'build_env', return_value={'HOME': '/unchanged-home'})
        self.prepared.start()
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.prepared.stop()
        self.temp.cleanup()

    def test_other_apps_keep_the_original_pipeline_without_extra_source_reads(self):
        with patch.object(gate.full, 'prepared', side_effect=AssertionError('unrelated source access')):
            self.assertIsNone(gate.complete({'id': 'cad'}, self.platform))
            self.assertIsNone(gate.require_complete({'id': 'launcher'}, self.platform))

    def test_two_real_tests_are_required_not_an_empty_or_weaker_filtered_success(self):
        gate.validate_output(self.output)
        cases = [self.output.replace('2 passed', '0 passed'),
                 self.output.replace('0 ignored', '1 ignored'),
                 self.output.replace('0 failed', '1 failed'),
                 self.output.replace('test ' + gate.TESTS[1] + ' ... ok', ''),
                 self.output.replace(gate.TESTS[1], gate.TESTS[0]),
                 self.output.replace(' ... ok', ' ... ignored', 1)]
        for text in cases:
            with self.subTest(output=text), self.assertRaises(ValueError):
                gate.validate_output(text)

    def test_exact_native_command_and_real_output_are_bound_before_package(self):
        with patch.object(gate.full, 'run', return_value=self.output) as run:
            gate.complete(self.lock, self.platform)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ['rustup', 'run', '1.95.0', 'cargo', 'test', '--release', '--locked',
                                  '--target', 'aarch64-apple-darwin', '-p', 'pdfcraft-ui-egui',
                                  '--test', 'ui', gate.FILTER, '--', '--nocapture'])
        self.assertEqual(kwargs['cwd'], self.source)
        self.assertEqual(kwargs['env']['HOME'], '/unchanged-home')
        self.assertEqual(kwargs['env']['CARGO_TERM_COLOR'], 'never')
        gate.require_complete(self.lock, self.platform)
        record = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(record['binaries'], self.record['binaries'])
        self.assertEqual(record['checks']['originalCoreTests'], 'passed')
        self.assertEqual(record['checks'][gate.KEY]['outputSha256'], hashlib.sha256(self.output.encode()).hexdigest())

    def test_package_refuses_missing_extra_evidence(self):
        with self.assertRaisesRegex(ValueError, 'required before packaging'):
            gate.require_complete(self.lock, self.platform)

    def test_actual_rust_failure_keeps_its_exit_status_and_bounded_diagnostics(self):
        with patch.object(gate.full, 'run', return_value=self.output):
            gate.complete(self.lock, self.platform)
        error = subprocess.CalledProcessError(101, ['cargo'], output=b'running 2 tests\n',
                                              stderr=b'x' * 70000 + b'actual Rust assertion failure\n')
        captured = io.StringIO()
        with patch.object(gate.full, 'run', side_effect=error), patch.object(sys, 'stderr', captured):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                gate.complete(self.lock, self.platform)
        self.assertIs(raised.exception, error)
        self.assertEqual(raised.exception.returncode, 101)
        self.assertIn('running 2 tests', captured.getvalue())
        self.assertIn('actual Rust assertion failure', captured.getvalue())
        self.assertLess(len(captured.getvalue().encode('utf-8')), 66000)
        self.assertNotIn(gate.KEY, json.loads(self.path.read_text(encoding='utf-8'))['checks'])

    def test_failed_retry_cannot_reuse_an_older_positive_marker(self):
        with patch.object(gate.full, 'run', return_value=self.output):
            gate.complete(self.lock, self.platform)
        with patch.object(gate.full, 'run', return_value='running 0 tests\ntest result: ok. 0 passed; 0 failed; 0 ignored;'):
            with self.assertRaises(ValueError):
                gate.complete(self.lock, self.platform)
        self.assertNotIn(gate.KEY, json.loads(self.path.read_text(encoding='utf-8'))['checks'])
        with self.assertRaises(ValueError):
            gate.require_complete(self.lock, self.platform)

    def test_changed_source_or_test_output_is_refused_at_package_time(self):
        with patch.object(gate.full, 'run', return_value=self.output):
            gate.complete(self.lock, self.platform)
        accepted = json.loads(self.path.read_text(encoding='utf-8'))
        mutations = [('platform', 'windows-x64'), ('sourceTreeSha256', 'c' * 64),
                     ('command', ['cargo', 'test']), ('testsPassed', 0),
                     ('outputSha256', '0' * 64), ('output', self.output + 'altered')]
        for key, value in mutations:
            changed = copy.deepcopy(accepted)
            changed['checks'][gate.KEY][key] = value
            gate.full.write_json(self.path, changed)
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.require_complete(self.lock, self.platform)
        gate.full.write_json(self.path, accepted)
        (self.source / gate.SOURCES[0]).write_text('changed after testing', encoding='utf-8')
        with self.assertRaises(ValueError):
            gate.require_complete(self.lock, self.platform)

    def test_missing_or_duplicate_actual_harness_test_is_refused(self):
        path = self.source / gate.SOURCES[1]
        for source in ['fn unrelated() {}', path.read_text(encoding='utf-8') + '\nfn ' + gate.TESTS[0] + '() {}']:
            path.write_text(source, encoding='utf-8')
            with self.assertRaises(ValueError):
                gate.complete(self.lock, self.platform)

    def test_original_core_or_input_evidence_cannot_be_replaced(self):
        for key, value in [('app', 'other'), ('platform', 'windows-x64'), ('inputs', {}), ('checks', {})]:
            changed = copy.deepcopy(self.record)
            changed[key] = value
            gate.full.write_json(self.path, changed)
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.complete(self.lock, self.platform)

    def test_unreviewed_native_target_is_refused(self):
        with self.assertRaises(ValueError):
            gate.command(self.lock, 'linux-x64')


if __name__ == '__main__':
    unittest.main()
