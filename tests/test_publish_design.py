import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_design as release


class DesignPublicationGuards(unittest.TestCase):
    def fixture(self, directory, change=None):
        lock = {'version': '0.8.0-kio.1', 'source': {'commit': 'a' * 40}}
        collection = {'artifact': {'id': 7}, 'headSha': 'b' * 40,
                      'files': [{'path': 'release/design.zip', 'sha256': 'c' * 64}]}
        bundle = json.dumps({'archiveSha256': 'c' * 64}).encode()
        native = {'status': 'passed', 'app': 'design', 'checks': [{'passed': True}] * 11,
                  'steps': [{'exitCode': 0}] * 5, 'cliSha256': 'd' * 64}
        report = {'schema': 'kio.native-file-qa.v1', 'status': 'passed', 'app': 'design',
                  'platform': 'windows-x64', 'run': release.BUILD_RUN, 'repository': release.REPO,
                  'nativeQaPerformed': True, 'executedNativeBinaries': True, 'tokenPassedToNative': False,
                  'version': lock['version'], 'sourceCommit': 'a' * 40, 'headSha': 'b' * 40,
                  'artifact': {'id': 7}, 'checks': 11, 'commands': 5, 'cliSha256': 'd' * 64,
                  'bundleManifestSha256': hashlib.sha256(bundle).hexdigest()}
        if change:
            change(report, native)
        payload = json.dumps(native).encode()
        report['files'] = [{'path': 'smoke/report.json', 'bytes': len(payload),
                            'sha256': hashlib.sha256(payload).hexdigest()}]
        archive = Path(directory) / 'qa.zip'
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('report.json', json.dumps(report))
            zipped.writestr('smoke/report.json', payload)
            zipped.writestr('bundle-manifest.json', bundle)
        return archive, collection, lock

    def test_matching_real_execution_report_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, collection, lock = self.fixture(directory)
            evidence = release.read_qa(archive, 'windows-x64', collection, lock)
            self.assertEqual(evidence['report']['checks'], 11)

    def test_unexecuted_failed_or_different_artifact_report_is_rejected(self):
        cases = [('status', 'failed'), ('nativeQaPerformed', False), ('executedNativeBinaries', False),
                 ('tokenPassedToNative', True), ('artifact', {'id': 8}), ('run', release.BUILD_RUN + 1),
                 ('platform', 'macos-arm64'), ('checks', 10), ('commands', 4), ('sourceCommit', 'e' * 40),
                 ('bundleManifestSha256', 'f' * 64)]
        for key, value in cases:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                archive, collection, lock = self.fixture(directory, lambda report, native: report.update({key: value}))
                with self.assertRaises(Exception):
                    release.read_qa(archive, 'windows-x64', collection, lock)

    def test_failed_command_or_assertion_is_rejected(self):
        for kind in ('checks', 'steps'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                def change(report, native):
                    native[kind][0] = {'passed': False} if kind == 'checks' else {'exitCode': 1}
                archive, collection, lock = self.fixture(directory, change)
                with self.assertRaises(Exception):
                    release.read_qa(archive, 'windows-x64', collection, lock)

    def test_other_portable_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, collection, lock = self.fixture(directory)
            collection['files'][0]['sha256'] = 'e' * 64
            with self.assertRaises(Exception):
                release.read_qa(archive, 'windows-x64', collection, lock)


if __name__ == '__main__':
    unittest.main()
