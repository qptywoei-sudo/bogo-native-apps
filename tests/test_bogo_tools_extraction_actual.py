"""BUILD-only black-box tests for the exact proposed embedded PowerShell.

Run on a clean Windows VM; never launches the downloaded program. These are
not claimed as executed by the macOS proposal preflight.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import platform
import re
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import sys
import unittest
import zipfile

BASE = Path(__file__).resolve().parent
# The actual tested code comes from the exact proposed C++ literal, not a test-only extractor.
_options = argparse.ArgumentParser(add_help=False)
_options.add_argument('--source-cpp', type=Path, default=BASE / 'PortableLauncher.cpp')
_options.add_argument('--qa-root', type=Path, required=True)
_options.add_argument('--workflow-context', required=True)
_inputs, _remaining = _options.parse_known_args()
sys.argv = [sys.argv[0]] + _remaining
_CONTEXT = json.loads(_inputs.workflow_context)
if (set(_CONTEXT) != {'expectedSha', 'headSha', 'repository', 'runId', 'runAttempt', 'ref', 'workflowRef', 'event', 'runnerEnvironment'}
        or not re.fullmatch('[0-9a-f]{40}', _CONTEXT['expectedSha'])
        or _CONTEXT['headSha'] != _CONTEXT['expectedSha']
        or _CONTEXT['repository'] != 'qptywoei-sudo/bogo-native-apps'
        or _CONTEXT['event'] != 'workflow_dispatch' or _CONTEXT['runnerEnvironment'] != 'github-hosted'
        or not _CONTEXT['runId'].isdigit() or not _CONTEXT['runAttempt'].isdigit()
        or not _CONTEXT['ref'].startswith('refs/heads/codex/')
        or _CONTEXT['workflowRef'] != _CONTEXT['repository'] + '/.github/workflows/bogo-tools-acceptance.yml@' + _CONTEXT['ref']):
    raise RuntimeError('Exact reviewed hosted-workflow context mismatch')
_source = _inputs.source_cpp
if _source.is_symlink() or not _source.is_file() or _source.stat().st_size > 131072:
    raise RuntimeError('Expected a bounded regular exact candidate C++ source')
_source_bytes = _source.read_bytes()
if hashlib.sha256(_source_bytes).hexdigest() != '718136871df5ec36550d4dca50dc8249362ee61c32ed1442f48f76d8844f3629':
    raise RuntimeError('Candidate C++ source digest mismatch')
_cpp = _source_bytes.decode('utf-8')
SCRIPT = _cpp.split('script+=LR"BOGO_EXTRACT(\n', 1)[1].split(')BOGO_EXTRACT";', 1)[0]
# Keep Windows ordinary profile/temp paths, while never forwarding CI credentials.
# Values are inherited unchanged. No HOME or machine setting is reassigned.
_CHILD_ALLOWED = frozenset({
    'systemroot', 'windir', 'comspec', 'pathext', 'path', 'temp', 'tmp',
    'userprofile', 'localappdata', 'appdata', 'programdata', 'programfiles',
    'programfiles(x86)', 'programw6432', 'commonprogramfiles', 'commonprogramfiles(x86)',
    'commonprogramw6432', 'os', 'processor_architecture', 'processor_identifier',
    'processor_level', 'processor_revision', 'number_of_processors', 'computername',
    'username', 'userdomain', 'homedrive', 'homepath',
})
_CHILD_ENV = {key: value for key, value in os.environ.items() if key.lower() in _CHILD_ALLOWED}
if any(any(word in key.lower() for word in ('token', 'secret', 'password', 'credential')) for key in _CHILD_ENV):
    raise RuntimeError('Credential-bearing environment key reached child')
_QA = _inputs.qa_root.absolute()
if _QA.exists() or _QA.is_symlink():
    raise RuntimeError('QA root must be a new task-owned directory')
_QA.mkdir(parents=True, exist_ok=False)
_OUTPUT = _QA / 'output'
_FIXTURES = _QA / 'fixtures'
_OUTPUT.mkdir()
_FIXTURES.mkdir()
_PROCESS_PROOF = []
ROOT = "KIO-Control-Windows/"
UNICODE = (
    "USB드라이버/Samsung-USB-Driver-1.9.5.0.exe",
    "tools/licenses/previous-release-notices/KIO-4.5.0-시작하기.txt",
    "tools/licenses/previous-release-notices/시작 안내.txt",
)


def literal(value: str) -> str:
    encoded = base64.b64encode(value.encode("utf-16-le")).decode("ascii")
    return "[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('" + encoded + "'))"


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        if os.name != "nt":
            raise RuntimeError("Actual Windows/.NET tests must run on Windows; no skipped acceptance")
        self.temp = Path(tempfile.mkdtemp(prefix="bogo-extract-proposal-", dir=_FIXTURES))
        self.root = self.temp / "cache"
        self.archive = self.temp / "authenticated.zip"
        self.junctions: list[Path] = []

    def tearDown(self):
        for path in self.junctions:
            if path.is_dir():
                os.rmdir(path)  # Remove this junction itself; never recurse into its target.
        shutil.rmtree(self.temp)

    def package(self, entries=None, *, raw_names=False, attrs=None):
        if entries is None:
            entries = [("KIOControl.exe", b"synthetic-executable-not-run"), ("data/ascii.txt", b"same")]
            entries += [(name, ("public synthetic " + name).encode()) for name in UNICODE]
        with zipfile.ZipFile(self.archive, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries:
                entry = zipfile.ZipInfo(name if raw_names else ROOT + name)
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = (stat.S_IFREG | 0o644) << 16 if attrs is None else attrs
                archive.writestr(entry, data)
        return entries

    def invoke(self, expected=None):
        digest = expected or hashlib.sha256(self.archive.read_bytes()).hexdigest()
        code = "$zip=" + literal(str(self.archive)) + ";$root=" + literal(str(self.root)) + ";$expected='" + digest + "';\n" + SCRIPT
        system = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(system), "-NoProfile", "-NonInteractive", "-Command", code],
                                capture_output=True, timeout=120,
                                creationflags=subprocess.CREATE_NO_WINDOW, env=_CHILD_ENV)
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 16384)
        _PROCESS_PROOF.append({
            'case': self.id(), 'tool': 'normal-system-WindowsPowerShell',
            'returncode': result.returncode, 'credentialEnvironmentRemoved': True,
            'stdoutBytes': len(result.stdout), 'stdoutSha256': hashlib.sha256(result.stdout).hexdigest(),
            'stderrBytes': len(result.stderr), 'stderrSha256': hashlib.sha256(result.stderr).hexdigest(),
            'noProgramOrProfileExecuted': True,
        })
        if len(_PROCESS_PROOF) > 64:
            raise RuntimeError('Public child-process proof limit exceeded')
        return result.returncode

    def managed(self, relative):
        return self.root / ROOT / relative

    def put(self, relative, data):
        target = self.managed(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def test_fresh_all_unicode_names_exact(self):
        entries = self.package()
        self.assertEqual(self.invoke(), 0)
        for name, data in entries:
            self.assertEqual(self.managed(name).read_bytes(), data)
        self.assertFalse(list(self.root.glob(".bogo-extract-*")))
        self.assertFalse((self.root / "ready").exists())  # Only the native parent owns this marker.

    def test_partial_ascii_cache_preserves_existing_file_ids_and_canaries(self):
        entries = self.package()
        before = {}
        for name, data in entries:
            if name.isascii():
                path = self.put(name, data)
                before[name] = path.stat().st_ino
        ini = self.put("KIOControl.ini", b"[input]\r\nkeyboard=uhid\r\nmouse=uhid\r\n")
        document = self.put("user-folder/keep.txt", b"private synthetic canary")
        self.assertEqual(self.invoke(), 0)
        for name, data in entries:
            self.assertEqual(self.managed(name).read_bytes(), data)
        for name, file_id in before.items():
            self.assertEqual(self.managed(name).stat().st_ino, file_id)
        self.assertEqual(ini.read_bytes(), b"[input]\r\nkeyboard=uhid\r\nmouse=uhid\r\n")
        self.assertEqual(document.read_bytes(), b"private synthetic canary")

    def test_changed_managed_file_has_recovery_copy(self):
        self.package()
        self.put("data/ascii.txt", b"user modified managed file")
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.managed("data/ascii.txt").read_bytes(), b"same")
        backups = list(self.root.glob(".bogo-extract-*/previous/KIO-Control-Windows/data/ascii.txt"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"user modified managed file")

    def test_hardlink_is_replaced_without_changing_other_link(self):
        self.package()
        original = self.temp / "unmanaged-hardlink-canary.txt"
        original.write_bytes(b"must remain exact")
        target = self.managed("data/ascii.txt")
        target.parent.mkdir(parents=True)
        os.link(original, target)
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(original.read_bytes(), b"must remain exact")
        self.assertEqual(target.read_bytes(), b"same")
        self.assertNotEqual(original.stat().st_ino, target.stat().st_ino)

    def test_quoted_unicode_paths_are_data_only(self):
        self.root = self.temp / "cache ';&$()! 한글"
        self.archive = self.temp / "payload ';&$()! 日本語.zip"
        self.package()
        self.assertEqual(self.invoke(), 0)
        self.assertTrue(self.managed(UNICODE[0]).is_file())

    def test_wrong_digest_changes_nothing(self):
        self.package()
        canary = self.put("user.txt", b"keep")
        self.assertNotEqual(self.invoke("0" * 64), 0)
        self.assertEqual(canary.read_bytes(), b"keep")
        self.assertFalse(self.managed("KIOControl.exe").exists())
        self.assertFalse(list(self.root.glob(".bogo-extract-*")))

    def invalid_archive(self, entries, *, attrs=None):
        self.package(entries, raw_names=True, attrs=attrs)
        canary = self.put("user.txt", b"keep")
        self.assertNotEqual(self.invoke(), 0)
        self.assertEqual(canary.read_bytes(), b"keep")
        self.assertFalse(self.managed("KIOControl.exe").exists())
        self.assertFalse(list(self.root.glob(".bogo-extract-*")))

    def test_traversal(self):
        self.invalid_archive([(ROOT + "KIOControl.exe", b"safe"), (ROOT + "../escape.txt", b"bad")])

    def test_absolute_path(self):
        self.invalid_archive([("C:/escape.txt", b"bad")])

    def test_foreign_root(self):
        self.invalid_archive([("Foreign/data.txt", b"bad")])

    def test_backslash_name(self):
        self.invalid_archive([(ROOT + "nested\\escape.txt", b"bad")])

    def test_duplicate_casefold_target(self):
        self.invalid_archive([(ROOT + "same.txt", b"one"), (ROOT + "SAME.TXT", b"two")])

    def test_ntfs_stream(self):
        self.invalid_archive([(ROOT + "data.txt:stream", b"bad")])

    def test_reserved_device(self):
        self.invalid_archive([(ROOT + "NUL.txt", b"bad")])

    def test_trailing_dot(self):
        self.invalid_archive([(ROOT + "directory./file.txt", b"bad")])

    def test_control_character(self):
        self.invalid_archive([(ROOT + "bad\x01.txt", b"bad")])

    def test_zip_symlink(self):
        self.invalid_archive([(ROOT + "link", b"../../foreign")], attrs=(stat.S_IFLNK | 0o777) << 16)

    def test_directory_entry(self):
        self.invalid_archive([(ROOT + "directory/", b"")], attrs=(stat.S_IFDIR | 0o755) << 16)

    def test_count_limit_before_changes(self):
        self.invalid_archive([(ROOT + str(index), b"") for index in range(5001)])

    def test_existing_managed_directory_is_refused_without_deleting_it(self):
        self.package([("data/ascii.txt", b"new")])
        existing = self.managed("data/ascii.txt")
        existing.mkdir(parents=True)
        (existing / "user.txt").write_bytes(b"keep")
        self.assertNotEqual(self.invoke(), 0)
        self.assertEqual((existing / "user.txt").read_bytes(), b"keep")

    def test_junction_parent_is_refused_without_modifying_foreign_tree(self):
        self.package([("data/ascii.txt", b"new")])
        foreign = self.temp / "foreign"
        foreign.mkdir()
        (foreign / "canary.txt").write_bytes(b"keep")
        junction = self.managed("data")
        junction.parent.mkdir(parents=True)
        system = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
        result = subprocess.run([str(system), "/d", "/c", "mklink", "/J", str(junction), str(foreign)],
                                capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW, env=_CHILD_ENV)
        self.assertEqual(result.returncode, 0, "Normal own-directory junction fixture must work; no skipped guard")
        self.junctions.append(junction)
        self.assertNotEqual(self.invoke(), 0)
        self.assertEqual((foreign / "canary.txt").read_bytes(), b"keep")
        self.assertFalse((foreign / "ascii.txt").exists())

    def test_root_junction_is_refused_without_modifying_foreign_tree(self):
        self.package()
        foreign = self.temp / "foreign-root"
        foreign.mkdir()
        (foreign / "canary.txt").write_bytes(b"keep")
        system = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
        result = subprocess.run([str(system), "/d", "/c", "mklink", "/J", str(self.root), str(foreign)],
                                capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW, env=_CHILD_ENV)
        self.assertEqual(result.returncode, 0, "Normal own-directory junction fixture must work")
        self.junctions.append(self.root)
        self.assertNotEqual(self.invoke(), 0)
        self.assertEqual((foreign / "canary.txt").read_bytes(), b"keep")
        self.assertFalse((foreign / ROOT).exists())

    def test_parent_file_collision_is_refused_without_overwrite(self):
        self.package([("data/ascii.txt", b"new")])
        collision = self.put("data", b"existing user file")
        self.assertNotEqual(self.invoke(), 0)
        self.assertEqual(collision.read_bytes(), b"existing user file")

    def test_failure_after_replacement_retains_backup_and_allows_retry(self):
        self.package([("KIOControl.exe", b"new synthetic executable"), ("data/ascii.txt", b"new data")])
        self.put("KIOControl.exe", b"old truncated synthetic executable")
        collision = self.managed("data/ascii.txt")
        collision.mkdir(parents=True)
        (collision / "user.txt").write_bytes(b"preserve user data")
        self.assertNotEqual(self.invoke(), 0)
        self.assertFalse((self.root / "ready").exists())
        self.assertEqual(self.managed("KIOControl.exe").read_bytes(), b"new synthetic executable")
        backups = list(self.root.glob(".bogo-extract-*/previous/KIO-Control-Windows/KIOControl.exe"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"old truncated synthetic executable")
        retained = collision.with_name("saved-user-folder")
        collision.rename(retained)  # Test-only explicit owner repair; production never moves unknown data.
        self.assertEqual(self.invoke(), 0)
        self.assertEqual((retained / "user.txt").read_bytes(), b"preserve user data")
        self.assertEqual(self.managed("data/ascii.txt").read_bytes(), b"new data")
        self.assertEqual(backups[0].read_bytes(), b"old truncated synthetic executable")

    def test_locked_changed_file_fails_safely_then_repairs_after_normal_close(self):
        import ctypes
        from ctypes import wintypes
        self.package([("data/ascii.txt", b"new")])
        target = self.put("data/ascii.txt", b"old truncated content")
        native = ctypes.WinDLL("kernel32", use_last_error=True)
        native.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        native.CreateFileW.restype = wintypes.HANDLE
        native.CloseHandle.argtypes = [wintypes.HANDLE]
        native.CloseHandle.restype = wintypes.BOOL
        handle = native.CreateFileW(str(target), 0x80000000, 1, None, 3, 0x80, None)
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
        try:
            self.assertNotEqual(self.invoke(), 0)
            self.assertEqual(target.read_bytes(), b"old truncated content")
            self.assertFalse((self.root / "ready").exists())
        finally:
            self.assertTrue(native.CloseHandle(handle))
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(target.read_bytes(), b"new")
        backups = list(self.root.glob(".bogo-extract-*/previous/KIO-Control-Windows/data/ascii.txt"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"old truncated content")


if __name__ == "__main__":
    started = time.monotonic()
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ExtractionTests)
    names = [test.id() for test in suite]
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    log = stream.getvalue()
    if len(log.encode('utf-8')) > 262144:
        raise RuntimeError('Public synthetic-fixture test log exceeded limit')
    (_OUTPUT / 'windows-extraction-tests.log').write_text(log, encoding='utf-8')
    passed = (result.testsRun == 24 and len(names) == 24 and result.wasSuccessful()
              and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses)
    report = {
        'workflowContext': _CONTEXT,
        'schemaVersion': 1, 'purpose': 'Actual Windows tests of the exact proposed extractor; no program acceptance',
        'candidateCppSha256': hashlib.sha256(_source_bytes).hexdigest(),
        'scriptSha256': hashlib.sha256(SCRIPT.encode('utf-8')).hexdigest(),
        'actualWindows': os.name == 'nt', 'pythonVersion': platform.python_version(),
        'elapsedSeconds': round(time.monotonic() - started, 3),
        'expectedTests': 24, 'testsRun': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'expectedFailures': len(result.expectedFailures), 'unexpectedSuccesses': len(result.unexpectedSuccesses),
        'passedAll24': passed, 'cases': names,
        'freshTaskOwnedFixtures': True, 'fixtureRoot': str(_FIXTURES),
        'credentialEnvRemovedBeforeEveryChild': True, 'childEnvironmentKeyNames': sorted(_CHILD_ENV),
        'executionPolicyOrMachineSettingsChanged': False, 'downloadedProgramsExecuted': False,
        'draftAssetsFetched': False, 'childProcesses': _PROCESS_PROOF,
    }
    (_OUTPUT / 'windows-extraction-tests-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(log)
    print(json.dumps({key: value for key, value in report.items() if key not in ('cases', 'childProcesses', 'childEnvironmentKeyNames')}, indent=2))
    raise SystemExit(0 if passed else 1)
