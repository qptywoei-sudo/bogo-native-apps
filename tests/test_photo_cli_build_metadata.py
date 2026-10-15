"""Exact Photo CLI build provenance; no native binary execution or relaxed identity."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import smoke_craft as smoke


class PhotoCliBuildMetadata(unittest.TestCase):
    NAME = 'photocraft-cli'
    VERSION = '0.9.0'
    COMMIT = 'c699e3cda69f4852b43c0b191ab0091aaeff9d6a'
    EPOCH = 1791987365
    DATE = '2026-10-14'
    LINE = 'photocraft-cli 0.9.0 (c699e3cda, 2026-10-14)'

    def parse(self, output, name=None, version=None, commit=None):
        return smoke.pinned_cli_version('photo', output, name or self.NAME,
                                        version or self.VERSION, commit or self.COMMIT)

    def test_complete_original_lf_and_crlf_build_output(self):
        self.assertEqual(self.parse(self.LINE + '\n'), self.LINE)
        self.assertEqual(self.parse(self.LINE + '\r\n'), self.LINE)

    def test_reviewed_build_epoch_name_version_and_source_pin_match_lock(self):
        lock = next(row for row in json.loads((ROOT / 'manifests/full-native-apps.json').read_text(encoding='utf-8'))['applications']
                    if row['id'] == 'photo')
        self.assertEqual(lock['versionOutputNames']['cli'], self.NAME)
        self.assertEqual(lock['upstreamVersion'], self.VERSION)
        self.assertEqual(lock['source']['commit'], self.COMMIT)
        self.assertEqual(lock['sourceDateEpoch'], self.EPOCH)
        self.assertEqual(smoke.PHOTO_SOURCE_DATE_EPOCH, self.EPOCH)
        self.assertEqual(time.strftime('%Y-%m-%d', time.gmtime(self.EPOCH)), self.DATE)
        self.assertEqual(smoke.APPS['photo'][:3], ('photocraft', self.VERSION, self.COMMIT))

    def test_wrong_claimed_name_version_or_full_source_commit_is_rejected(self):
        for change in ({'name': 'KIO Photo'}, {'name': 'other-cli'}, {'version': '0.9.1'},
                       {'version': '0.9.0-kio.1'}, {'commit': '0' * 40},
                       {'commit': self.COMMIT[:9] + '0' * 31}, {'commit': self.COMMIT[:9]}):
            with self.subTest(change=change):
                self.assertIsNone(self.parse(self.LINE + '\n', **change))

    def test_wrong_actual_metadata_is_rejected(self):
        invalid = [self.LINE.replace('c699e3cda', 'c699e3cdb'),
                   self.LINE.replace('c699e3cda', self.COMMIT),
                   self.LINE.replace('c699e3cda', 'c699e3cd'),
                   self.LINE.replace('2026-10-14', '2026-10-15'),
                   self.LINE.replace('2026-10-14', '2026-02-30'),
                   self.LINE.replace('2026-10-14', str(self.EPOCH)),
                   self.LINE.replace('0.9.0', '0.9.1'),
                   self.LINE.replace('photocraft-cli', 'other-cli')]
        for line in invalid:
            with self.subTest(output=line):
                self.assertIsNone(self.parse(line + '\n'))

    def test_partial_or_dev_provenance_is_rejected(self):
        first = self.NAME + ' ' + self.VERSION
        for line in (first, first + ' (123abc)', first + ' (c699e3cda)',
                     first + ' (2026-10-14)', first + ' (dev build)'):
            with self.subTest(output=line):
                self.assertIsNone(self.parse(line + '\n'))

    def test_no_added_footer_control_characters_whitespace_or_trailing_text(self):
        raw = self.LINE + '\n'
        invalid = [self.LINE, raw + '\n', '\n' + raw, raw + 'extra\n',
                   raw + 'Source: https://github.com/storytold/photocraft\n',
                   self.LINE + ' trailing\n', self.LINE + ' \n', ' ' + raw,
                   raw + '\0', self.LINE + '\r', self.LINE + '\r\r\n',
                   self.LINE.replace(', ', ',') + '\n', raw + raw,
                   self.LINE + '\x1b[0m\n', self.LINE + '\u2028', 'x' * 4097,
                   None, raw.encode('utf-8')]
        for output in invalid:
            with self.subTest(output=repr(output)):
                self.assertIsNone(self.parse(output))

    def test_other_apps_keep_existing_single_line_version_contract(self):
        locks = json.loads((ROOT / 'manifests/full-native-apps.json').read_text(encoding='utf-8'))['applications']
        for lock in locks:
            if lock['id'] in ('photo', 'pdf'):
                continue
            app, name, version, commit = lock['id'], lock['versionOutputNames']['cli'], lock['upstreamVersion'], lock['source']['commit']
            first = name + ' ' + version
            with self.subTest(app=app):
                self.assertEqual(smoke.pinned_cli_version(app, first + '\n', name, version, commit), first)
                self.assertEqual(smoke.pinned_cli_version(app, first + ' (123abc)\r\n', name, version, commit), first + ' (123abc)')
                self.assertIsNone(smoke.pinned_cli_version(app, first + '\nextra\n', name, version, commit))

    def test_actual_photo_metadata_is_not_accepted_for_another_app(self):
        for app in set(smoke.APPS) - {'photo'}:
            stem, version, commit, _ = smoke.APPS[app]
            name = 'SoundCraft CLI' if app == 'sound' else stem + '-cli'
            with self.subTest(app=app):
                self.assertIsNone(smoke.pinned_cli_version(app, self.LINE + '\n', name, version, commit))

    def test_shared_main_gate_retains_original_stdout_and_failed_fixture_is_not_a_pass(self):
        # Stop before document commands. This tests only the gate/report and does
        # not execute or claim to validate any native editing functionality.
        raw = self.LINE + '\r\n'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'fresh'
            with patch.object(smoke.Smoke, 'call', return_value=raw) as call, \
                    patch.object(smoke, 'photo', side_effect=AssertionError('fixture stops before native document QA')), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = smoke.main(['--app', 'photo', '--cli', str(Path(sys.executable).resolve()), '--output', str(output)])
            call.assert_called_once_with('00-version', ['--version'])
            report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(result, 1)
            self.assertEqual(report['status'], 'failed')
            self.assertTrue(report['checks'][0]['passed'])
            self.assertEqual(report['checks'][0]['detail'], raw)
            self.assertEqual(report['error'], 'fixture stops before native document QA')


if __name__ == '__main__':
    unittest.main()
