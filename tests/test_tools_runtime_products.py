"""Actual 3.13.16 compiler fixtures, never cache/source execution."""
from pathlib import Path
import hashlib
import importlib.util
import contextlib
import io
import json
import marshal
import os
import py_compile
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if not (HERE/'tools_runtime_products.py').is_file():
    sys.path.insert(0,str(HERE.parent/'scripts'))
import tools_runtime_products as v

WINDOWS_ROOT = r'D:\a\_temp\bogo-owned-acceptance\prior\KIO-Control-Windows'
SOURCE = b'"Trusted fixture."\nVALUE = 7\ndef outer(value):\n    def nested(extra=2):\n        return value + extra\n    return nested\n'
CACHE = 'tools/engine/__pycache__/engine.cpython-313.pyc'


class ActualCompilerFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        v.runtime_identity()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='owned-pyc-fixture-', dir=HERE)
        self.root = Path(self.temp.name)
        self.source = self.root / 'tools/engine/engine.py'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(SOURCE)
        os.utime(self.source, (1793000000, 1793000000))
        self.cache = self.root / CACHE
        self.cache.parent.mkdir()
        self.identity = {'bytes': len(SOURCE), 'sha256': v.sha256(SOURCE)}
        py_compile.compile(str(self.source), cfile=str(self.cache),
                           dfile=v.windows_filename(WINDOWS_ROOT, 'tools/engine/engine.py'),
                           doraise=True, optimize=0)
        self.data = self.cache.read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def check(self, data=None, *, path=CACHE, source=SOURCE, identity=None, optimize=0):
        return v.verify_pyc(path, self.data if data is None else data, source,
                            self.identity if identity is None else identity,
                            WINDOWS_ROOT, int(self.source.stat().st_mtime), optimize)

    def test_actual_31316_py_compile_timestamp_and_nested_code_match(self):
        result = self.check()
        self.assertEqual(result['header'], 'timestamp')
        self.assertEqual(result['source']['sha256'], self.identity['sha256'])
        self.assertEqual(len(result['recursiveTrustedCodeObjects']), 3)
        self.assertFalse(result['cacheExecuted'])
        self.assertFalse(result['untrustedCacheDeserialized'])

    def test_separate_actual_interpreter_processes_compile_the_same_trusted_payload(self):
        # A real import's compiler and this verifier run in different processes.
        source=SOURCE+b'KNOWN = {"z", "alpha", "middle", "unicode_\xe2\x98\x83"}\n'
        self.source.write_bytes(source);os.utime(self.source,(1793000000,1793000000))
        child='import py_compile,sys;py_compile.compile(sys.argv[1],cfile=sys.argv[2],dfile=sys.argv[3],doraise=True,optimize=0)'
        for _ in range(2):
            subprocess.run([sys.executable,'-I','-S','-B','-c',child,str(self.source),str(self.cache),
                            v.windows_filename(WINDOWS_ROOT,'tools/engine/engine.py')],check=True,capture_output=True,timeout=20)
            self.check(self.cache.read_bytes(),source=source,identity={'bytes':len(source),'sha256':v.sha256(source)})

    def test_actual_hash_headers_are_independently_source_bound(self):
        for mode in (py_compile.PycInvalidationMode.CHECKED_HASH, py_compile.PycInvalidationMode.UNCHECKED_HASH):
            with self.subTest(mode=mode):
                py_compile.compile(str(self.source), cfile=str(self.cache),
                                   dfile=v.windows_filename(WINDOWS_ROOT, 'tools/engine/engine.py'),
                                   doraise=True, optimize=0, invalidation_mode=mode)
                self.check(self.cache.read_bytes())
        invalid = bytearray(self.cache.read_bytes()); invalid[8] ^= 1
        with self.assertRaisesRegex(v.Rejected, 'source hash differs'):
            self.check(bytes(invalid))

    def test_actual_optimization_is_required_not_inferred_from_attacker_filename(self):
        for optimize in (1, 2):
            path = CACHE.replace('.pyc', f'.opt-{optimize}.pyc')
            py_compile.compile(str(self.source), cfile=str(self.cache),
                               dfile=v.windows_filename(WINDOWS_ROOT, 'tools/engine/engine.py'),
                               doraise=True, optimize=optimize)
            self.check(self.cache.read_bytes(), path=path, optimize=optimize)
            with self.assertRaisesRegex(v.Rejected, 'optimization differs'):
                self.check(self.cache.read_bytes(), path=path, optimize=0)

    def test_malicious_code_objects_and_noncode_payloads_are_never_deserialized_or_executed(self):
        marker = self.root / 'MALICIOUS_CACHE_WAS_EXECUTED'
        malicious = f'from pathlib import Path\nPath({str(marker)!r}).write_text("bad")\n'.encode()
        code = compile(malicious, v.windows_filename(WINDOWS_ROOT, 'tools/engine/engine.py'), 'exec')
        payloads = [marshal.dumps(code, 4), marshal.dumps({'not': 'code'}, 4), b'not-marshal', self.data[16:] + b'trailing']
        with mock.patch.object(marshal, 'loads', side_effect=AssertionError('Untrusted deserialization attempted')):
            for payload in payloads:
                with self.subTest(payloadSha=v.sha256(payload)), self.assertRaisesRegex(v.Rejected, 'exact trusted compiler output'):
                    self.check(self.data[:16] + payload)
        self.assertFalse(marker.exists())

    def test_source_bytes_hash_and_size_stay_mandatory_even_for_semantic_equivalence(self):
        for source in (SOURCE + b'\n', SOURCE.replace(b'7', b'8')):
            with self.subTest(sha=v.sha256(source)), self.assertRaisesRegex(v.Rejected, 'authenticated managed file'):
                self.check(source=source)
        with self.assertRaises(v.Rejected):
            self.check(identity={**self.identity, 'sha256': '0' * 64})

    def test_magic_flags_mtime_size_truncation_tampering_and_wrong_filename_fail(self):
        changes = []
        for at in (0, 8, 12, 20):
            bad = bytearray(self.data); bad[at] ^= 1; changes.append(bytes(bad))
        changes.extend([self.data[:4] + struct.pack('<I', flag) + self.data[8:] for flag in (2, 4, 0xffffffff)])
        changes.extend([b'', self.data[:16], self.data[:-1]])
        wrong = compile(SOURCE, r'C:\arbitrary\engine.py', 'exec', dont_inherit=True, optimize=0)
        changes.append(self.data[:16] + marshal.dumps(wrong, 4))
        for data in changes:
            with self.subTest(sha=v.sha256(data)), self.assertRaises(v.Rejected):
                self.check(data)

    def test_noncanonical_or_unknown_cache_paths_fail(self):
        invalid = ['../' + CACHE, '/' + CACHE, CACHE.replace('/', '\\'),
                   'tools//engine/__pycache__/engine.cpython-313.pyc', CACHE.replace('313', '312'),
                   CACHE.replace('cpython-313', 'pypy-313'), CACHE.replace('.pyc', '.opt-0.pyc'),
                   CACHE.replace('engine.cpython', 'other.cpython') + ':stream',
                   'tools/engine/__pycache__/__pycache__/engine.cpython-313.pyc',
                   'tools/engine/__pycache__/engine.cpython-313.pyc\x00']
        for path in invalid:
            with self.subTest(path=repr(path)), self.assertRaises(v.Rejected):
                self.check(path=path)


class ExactManagedTreeAndPreferences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='owned-managed-tree-', dir=HERE)
        cls.root = Path(cls.temp.name)
        cls.windows_root = str(cls.root.resolve()) if os.name == 'nt' else WINDOWS_ROOT
        cls.source = cls.root / 'tools/engine/engine.py'; cls.source.parent.mkdir(parents=True)
        cls.source.write_bytes(SOURCE); os.utime(cls.source, (1793000000, 1793000000))
        cls.inventory = {'tools/engine/engine.py': {'bytes': len(SOURCE), 'sha256': v.sha256(SOURCE)}}
        for i in range(v.MANAGED_FILE_COUNT-1):
            relative = f'managed/{i:04d}.bin'; path = cls.root / relative
            path.parent.mkdir(exist_ok=True); path.write_bytes(b'S')
            cls.inventory[relative] = {'bytes': 1, 'sha256': v.sha256(b'S')}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_3905_files_plus_real_cache_and_preexisting_ini_and_canary(self):
        ini = self.root / v.INI; canary = self.root / v.CANARY
        ini.write_bytes(b'[input]\r\nkeyboard=sdk\r\nmouse=uhid\r\n')
        canary.write_bytes(b'owned synthetic user-data sentinel')
        pre = v.capture_preimage(self.root, self.windows_root)
        sentinel = v.capture_preimage(self.root, self.windows_root, v.CANARY)
        cache = self.root / CACHE; cache.parent.mkdir()
        py_compile.compile(str(self.source), cfile=str(cache),
                           dfile=v.windows_filename(self.windows_root, 'tools/engine/engine.py'), doraise=True, optimize=0)
        try:
            result = v.verify_installation(self.root, self.windows_root, self.inventory, pre, canary_before=sentinel)
            self.assertEqual(result['managedFilesExact'], 3905)
            self.assertEqual(result['runtimeCachesSourceVerified'], 1)
            self.assertTrue(result['preferences']['unchanged'])
            self.assertTrue(result['canary']['unchanged'])
            self.assertNotIn('keyboard=sdk', json.dumps(result))
        finally:
            cache.unlink(); cache.parent.rmdir(); ini.unlink(); canary.unlink()

    def test_signed_source_or_executable_change_and_missing_file_are_never_runtime_waivers(self):
        pre = v.capture_preimage(self.root, self.windows_root)
        path = self.root / 'managed/0000.bin'
        for mutation in ('changed', 'missing'):
            with self.subTest(mutation=mutation):
                if mutation == 'changed': path.write_bytes(b'X')
                else: path.unlink()
                try:
                    with self.assertRaisesRegex(v.Rejected, 'Signed managed'):
                        v.verify_installation(self.root, self.windows_root, self.inventory, pre)
                finally:
                    path.write_bytes(b'S')
        with self.assertRaisesRegex(v.Rejected, '3905'):
            v.verify_installation(self.root, self.windows_root, {}, pre)

    def test_unknown_extra_and_cache_without_signed_source_fail_closed(self):
        pre = v.capture_preimage(self.root, self.windows_root)
        for relative in ('arbitrary.exe', 'tools/engine/__pycache__/unknown.cpython-313.pyc'):
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'no')
            try:
                with self.assertRaises(v.Rejected):
                    v.verify_installation(self.root, self.windows_root, self.inventory, pre)
            finally:
                path.unlink()
                if path.parent.name == '__pycache__': path.parent.rmdir()

    def test_ini_new_missing_changed_and_wrong_installation_are_rejected(self):
        path = self.root / v.INI; absent = v.capture_preimage(self.root, self.windows_root)
        self.assertTrue(v.verify_preimage(self.root, self.windows_root, absent)['unchanged'])
        path.write_bytes(b'[input]\r\nkeyboard=uhid\r\nmouse=uhid\r\n')
        try:
            with self.assertRaisesRegex(v.Rejected, 'no captured preimage'):
                v.verify_preimage(self.root, self.windows_root, absent)
            pre = v.capture_preimage(self.root, self.windows_root)
            path.write_bytes(b'changed synthetic preferences')
            with self.assertRaisesRegex(v.Rejected, 'bytes changed'):
                v.verify_preimage(self.root, self.windows_root, pre)
            path.unlink()
            with self.assertRaisesRegex(v.Rejected, 'missing'):
                v.verify_preimage(self.root, self.windows_root, pre)
            with self.assertRaisesRegex(v.Rejected, 'another installation'):
                v.verify_preimage(self.root, r'C:\another-install', absent)
        finally:
            path.unlink(missing_ok=True)

    def test_symlink_hardlink_and_reparse_files_and_directories_fail(self):
        link = self.root / 'owned-link'; target = self.root / 'managed/0001.bin'
        link.symlink_to(target)
        try:
            with self.assertRaisesRegex(v.Rejected, 'Linked/nonregular'):
                v.read_owned(self.root, link.name, 8)
        finally: link.unlink()
        os.link(target, link)
        try:
            with self.assertRaisesRegex(v.Rejected, 'Hardlinked'):
                v.read_owned(self.root, link.name, 8)
        finally: link.unlink()
        link.symlink_to(target.parent, target_is_directory=True)
        try:
            with self.assertRaisesRegex(v.Rejected, 'ancestry'):
                v.read_owned(self.root, link.name + '/0001.bin', 8)
        finally: link.unlink()
        fake = mock.Mock(); real = target.lstat(); fake.lstat.return_value = mock.Mock(
            st_mode=real.st_mode, st_file_attributes=0x400, st_nlink=1)
        with self.assertRaisesRegex(v.Rejected, 'Linked/nonregular'):
            v._regular_unlinked(fake)

    def test_raw_identity_diagnostic_retains_every_guard_and_only_relative_metadata(self):
        from types import SimpleNamespace
        file=self.root/'managed/0001.bin';before=file.lstat()
        fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_mode','st_nlink','st_file_attributes')
        values={key:getattr(before,key,None)for key in fields}
        after=SimpleNamespace(**dict(values,st_ino=before.st_ino+1))
        with mock.patch.object(v.os,'fstat',return_value=after),self.assertRaisesRegex(v.Rejected,'File changed while opening')as caught:
            v.read_owned(self.root,'managed/0001.bin',8)
        proof=caught.exception.file_identity_diagnostic
        self.assertEqual(proof['phase'],'after-open-fstat');self.assertEqual(proof['before']['st_ino'],before.st_ino)
        self.assertEqual(proof['after']['st_ino'],before.st_ino+1);self.assertTrue(proof['identityGateUnchanged'])
        self.assertEqual(proof['relativePath'],'managed/0001.bin');self.assertNotIn(str(self.root),json.dumps(proof))
        self.assertLessEqual(len(json.dumps(proof,separators=(',',':'))),1536)

    def test_wrong_actual_windows_root_remains_rejected(self):
        if os.name=='nt':
            pre=v.capture_preimage(self.root,self.windows_root)
            with self.assertRaisesRegex(v.Rejected,'Actual Windows installation root differs'):
                v.verify_installation(self.root,r'C:\another-install',self.inventory,pre)
        else:
            # Cross-platform preimage identity is always installation-specific.
            absent=v.capture_preimage(self.root,self.windows_root)
            with self.assertRaisesRegex(v.Rejected,'another installation'):
                v.verify_preimage(self.root,r'C:\another-install',absent)


class CliPreimageAndFactory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ExactManagedTreeAndPreferences.setUpClass.__func__(cls)
        cls.evidence=Path(tempfile.mkdtemp(prefix='owned-cli-evidence-',dir=HERE))
        cls.source_archive=cls.evidence/'owned-source-fixture.zip'
        cls.factory_source=b'/* Owned public-code fixture; never compiled or executed. */\n'
        import zipfile
        with zipfile.ZipFile(cls.source_archive,'w')as z:
            z.writestr('windows/GalaxyControl.c',cls.factory_source)
            z.writestr('SOURCE-MANIFEST.json',json.dumps({'files':[{'path':'windows/GalaxyControl.c','sha256':v.sha256(cls.factory_source),'bytes':len(cls.factory_source)}]}))
            z.writestr('agent/mac_bundle_migration.py',b'# owned source fixture\n')
            for i in range(437):z.writestr(f'owned-source/{i:03d}.txt',b'fixture')

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.evidence)
        ExactManagedTreeAndPreferences.tearDownClass.__func__(cls)

    def call(self,args):
        with contextlib.redirect_stdout(io.StringIO()):return v.cli(args)

    def capture(self,label,fresh=False,root=None):
        path=self.evidence/(label+'-before.json');args=['capture','--root',str(root or self.root),'--output',str(path)]
        if fresh:args.append('--fresh-portable')
        self.assertEqual(self.call(args),0)
        return path

    def verify(self,label,preimage,extra=(),root=None):
        result=self.evidence/(label+'-report.json')
        with mock.patch.object(v,'pinned_update_inventory',return_value=self.inventory),mock.patch.multiple(v,
             SOURCE_ZIP_SHA256=v.sha256(self.source_archive.read_bytes()),SOURCE_ZIP_BYTES=self.source_archive.stat().st_size,
             INI_FACTORY_SOURCE_SHA256=v.sha256(self.factory_source)):
            code=self.call(['verify','--root',str(root or self.root),'--archive',str(self.evidence/'authenticated-archive-fixture.zip'),
                            '--preimage',str(preimage),'--output',str(result),*extra])
        return code,json.loads(result.read_text())

    def test_cli_upgrade_captures_exact_ini_and_known_canary_without_content_output(self):
        ini=self.root/v.INI;canary=self.root/v.CANARY
        ini.write_bytes(b'owned synthetic preferences');canary.write_bytes(b'owned synthetic document')
        try:
            pre=self.capture('upgrade-positive');value=json.loads(pre.read_text())
            self.assertEqual(value['mode'],'upgrade');self.assertTrue(value['ini']['present']);self.assertTrue(value['canary']['present'])
            self.assertNotIn('owned synthetic',pre.read_text())
            code,report=self.verify('upgrade-positive',pre)
            self.assertEqual(code,0);self.assertEqual(report['checks']['managedFilesExact'],3905)
            self.assertTrue(report['checks']['preferences']['unchanged']);self.assertTrue(report['checks']['canary']['unchanged'])
        finally:ini.unlink();canary.unlink()

    def test_cli_upgrade_new_ini_cannot_use_fresh_factory_waiver(self):
        pre=self.capture('upgrade-absent');ini=self.root/v.INI;ini.write_bytes(v.INI_DEFAULT_BYTES)
        try:
            code,report=self.verify('upgrade-new-default',pre)
            self.assertEqual(code,1);self.assertIn('no captured preimage',report['message'])
            code,report=self.verify('upgrade-mode-forgery',pre,extra=['--fresh-portable','--source',str(self.source_archive),'--exe',str(self.root/'KIOControl.exe')])
            self.assertEqual(code,1);self.assertIn('matching-mode',report['message'])
        finally:ini.unlink()

    def test_fresh_capture_requires_absent_root_and_cannot_recapture_after_start(self):
        output=self.evidence/'existing-fresh-rejected.json'
        self.assertEqual(self.call(['capture','--root',str(self.root),'--output',str(output),'--fresh-portable']),1)
        self.assertEqual(json.loads(output.read_text())['status'],'failed')

    def test_closed_source_factory_accepts_only_absent_first_start_and_exact_default(self):
        fresh=self.evidence/'fresh-cache';pre=self.capture('fresh-first-start',fresh=True,root=fresh)
        # A fixture clone, not a normal SFX execution; parent actual OS/SFX gates remain mandatory.
        import shutil
        shutil.copytree(self.root,fresh)
        exe=fresh/'KIOControl.exe';exe.write_bytes(b'owned native byte fixture')
        removed=self.inventory.pop('managed/0000.bin');(fresh/'managed/0000.bin').unlink()
        self.inventory['KIOControl.exe']={'bytes':exe.stat().st_size,'sha256':v.sha256(exe.read_bytes())}
        ini=fresh/v.INI;ini.write_bytes(v.INI_DEFAULT_BYTES)
        try:
            flags=['--fresh-portable','--source',str(self.source_archive),'--exe',str(exe)]
            code,report=self.verify('fresh-default',pre,flags,root=fresh)
            self.assertEqual(code,0,report)
            self.assertTrue(report['checks']['preferences']['sourceFactoryUsed'])
            self.assertFalse(report['checks']['preferences']['unchanged'])
            self.assertTrue(report['factory']['actualSfxStartupPidPeHealthAndSignatureEvidenceRequiredFromParent'])
            ini.write_bytes(v.INI_DEFAULT_BYTES.replace(b'uhid',b'sdk!'))
            code,report=self.verify('fresh-altered-default',pre,flags,root=fresh)
            self.assertEqual(code,1);self.assertIn('exact approved source factory',report['message'])
            code,report=self.verify('fresh-wrong-exe',pre,['--fresh-portable','--source',str(self.source_archive),'--exe',str(fresh/'managed/0001.bin')],root=fresh)
            self.assertEqual(code,1);self.assertIn('exact owned installed native path',report['message'])
            with self.assertRaises(v.Rejected):v.verified_fresh_factory(fresh,self.source_archive,exe,{'mode':'fresh-portable','rootAbsentBeforeFirstStart':False},self.inventory)
        finally:
            self.inventory.pop('KIOControl.exe');self.inventory['managed/0000.bin']=removed;shutil.rmtree(fresh)

    def test_factory_flags_unknown_outputs_and_missing_signature_archive_fail_closed(self):
        pre=self.capture('bad-flags')
        for label,flags in [('missing-source',['--fresh-portable']),('source-without-mode',['--source',str(self.source_archive)])]:
            code,report=self.verify(label,pre,flags)
            self.assertEqual(code,1);self.assertIn('factory flags',report['message'])
        bad=self.evidence/'unknown-archive.zip';bad.write_bytes(b'not an authenticated archive')
        with self.assertRaises(v.Rejected):v.pinned_update_inventory(bad)
        output=self.root/'forbidden-evidence.json'
        self.assertEqual(self.call(['capture','--root',str(self.root),'--output',str(output)]),1)
        self.assertFalse(output.exists())

    def test_actual_repinned_source_factory_and_new_runtime_module_are_current(self):
        self.assertEqual(v.SOURCE_COMMIT,'0821a5aec13aeb9b6bbb3bd86bab42b482497e4e')
        self.assertEqual(v.MANAGED_FILE_COUNT,3905)
        self.assertEqual(v.SOURCE_ZIP_SHA256,'2bc1e8b7faf069f5055b7a16ad656aa5fd366bdb015e0c7dd9ed267c10edf999')
        self.assertEqual(v.UPDATE_ZIP_SHA256,'0f4310aee34470d0400cefb1d249bf13e98e9fc8bc50484719ca628315ffe6ed')
        self.assertEqual(v.INI_FACTORY_SOURCE_SHA256,'2b6d16a1ec80403bfba281b4457f4fa01448598951a4dd7a2b00978506b19f46')
        import zipfile
        with zipfile.ZipFile(self.source_archive)as z:
            self.assertEqual(len(z.namelist()),440)
            self.assertIn('agent/mac_bundle_migration.py',z.namelist())
        self.assertEqual(len(v.INI_DEFAULT_BYTES),36);self.assertEqual(v.sha256(v.INI_DEFAULT_BYTES),v.INI_DEFAULT_SHA256)


if __name__ == '__main__':
    unittest.main(verbosity=2)
