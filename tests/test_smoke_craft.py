"""Test independent format checks and honest reporting; never fake a native QA pass."""
import contextlib
import hashlib
import io
import json
import math
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import smoke_craft as smoke
import smoke_craft_documents as documents


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def png(raw, width=2, height=2, depth=8, color=6):
    header = struct.pack('>IIBBBBB', width, height, depth, color, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


def wav(audio, encoding=1, bits=24):
    alignment = bits // 8
    fmt = struct.pack('<HHIIHH', encoding, 1, 48000, 48000 * alignment, alignment, bits)
    def riff_chunk(kind, data):
        return kind + struct.pack('<I', len(data)) + data + b'\0' * (len(data) % 2)
    body = b'WAVE' + riff_chunk(b'fmt ', fmt) + riff_chunk(b'data', audio)
    return b'RIFF' + struct.pack('<I', len(body)) + body


class CraftSmokeChecks(unittest.TestCase):
    def pdf_version_output(self):
        return ('pdfcraft-cli 0.8.0\n'
                'Discord: https://discord.gg/artcraft  (help and feedback)\n'
                'Web:     https://getartcraft.com/apps/pdfcraft\n'
                'Source:  https://github.com/storytold/pdfcraft\n')

    def test_exact_pinned_pdf_original_four_lines_normalize_only_after_full_validation(self):
        raw = self.pdf_version_output()
        commit = '9931329b9fae0b05373b4dc3ac7c58541f0891a4'
        self.assertEqual(smoke.pinned_cli_version('pdf', raw, 'pdfcraft-cli', '0.8.0', commit), 'pdfcraft-cli 0.8.0')
        self.assertEqual(smoke.pinned_cli_version('pdf', raw.replace('\n', '\r\n'), 'pdfcraft-cli', '0.8.0', commit), 'pdfcraft-cli 0.8.0')
        for name, version, source in [('KIO PDF', '0.8.0', commit), ('pdfcraft-cli', '0.8.1', commit),
                                      ('pdfcraft-cli', '0.8.0', '0' * 40)]:
            with self.subTest(name=name, version=version, source=source):
                self.assertIsNone(smoke.pinned_cli_version('pdf', raw, name, version, source))

    def test_pdf_missing_arbitrary_or_modified_footer_and_extra_lines_are_rejected(self):
        raw = self.pdf_version_output()
        invalid = [raw.splitlines()[0], raw.splitlines()[0] + '\n', raw[:-1], '\n' + raw, raw + '\n', raw + 'extra\n',
                   raw.replace('0.8.0', '0.8.1'), raw.replace('pdfcraft-cli', 'other-cli'),
                   raw.replace('0.8.0\n', '0.8.0 (123abc)\n'), raw.replace('0.8.0\n', '0.8.0 secret-token\n'),
                   raw.replace('https://discord.gg/artcraft', 'https://discord.gg/other'),
                   raw.replace('https://getartcraft.com/apps/pdfcraft', 'https://getartcraft.com/apps/pdfcraft?token=private'),
                   raw.replace('https://github.com/storytold/pdfcraft', 'https://unrelated.example/source'),
                   raw.replace('  (help and feedback)', ' (help and feedback)'),
                   raw.replace('Web:     ', 'Web: '), raw.replace('Source:', 'Source: ' + chr(27) + '[31m'),
                   raw + '\0', raw.replace('Discord:', 'Discord:\r'), raw + 'Authorization: Bearer private\n',
                   raw + raw, 'pdfcraft-cli 0.8.0\nSome unrelated footer\n']
        for output in invalid:
            with self.subTest(output=repr(output)):
                self.assertIsNone(smoke.pinned_cli_version('pdf', output, 'pdfcraft-cli', '0.8.0', smoke.APPS['pdf'][2]))

    def test_other_app_lock_names_versions_and_single_line_contract_stay_strict(self):
        root = Path(__file__).resolve().parents[1]
        locks = json.loads((root / 'manifests/full-native-apps.json').read_text())['applications']
        for lock in locks:
            if lock['id'] == 'pdf':
                continue
            app, name, version, commit = lock['id'], lock['versionOutputNames']['cli'], lock['upstreamVersion'], lock['source']['commit']
            raw = name + ' ' + version
            with self.subTest(app=app):
                self.assertEqual(smoke.pinned_cli_version(app, raw + '\n', name, version, commit), raw)
                self.assertEqual(smoke.pinned_cli_version(app, raw + ' (123abc)\n', name, version, commit), raw + ' (123abc)')
                for invalid in [raw + '\nDiscord: https://discord.gg/artcraft\n', raw + '\nextra\n', raw + ' token',
                                raw.replace(version, '99.0.0'), raw.replace(name, 'wrong-cli'), raw + '\0']:
                    self.assertIsNone(smoke.pinned_cli_version(app, invalid, name, version, commit))
                self.assertIsNone(smoke.pinned_cli_version(app, self.pdf_version_output(), name, version, commit))
        self.assertIsNone(smoke.pinned_cli_version('unknown', 'unknown-cli 0.8.0', 'unknown-cli', '0.8.0', '0' * 40))

    def test_main_uses_shared_pinned_version_check_and_keeps_raw_stdout_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'version-check'
            with patch.object(smoke, 'pinned_cli_version', wraps=smoke.pinned_cli_version) as helper, contextlib.redirect_stdout(io.StringIO()):
                result = smoke.main(['--app', 'photo', '--cli', str(Path(sys.executable).resolve()), '--output', str(output)])
            self.assertEqual(result, 1)
            raw = (output / '00-version.stdout.txt').read_text()
            helper.assert_called_once_with('photo', raw, 'photocraft-cli', '0.9.0', smoke.APPS['photo'][2])
            report = json.loads((output / 'report.json').read_text())
            self.assertEqual(report['checks'][0]['detail'], raw)
            self.assertFalse(report['checks'][0]['passed'])

    def test_plans_match_all_ten_immutable_native_sources_without_claiming_execution(self):
        root = Path(__file__).resolve().parents[1]
        locks = {row['id']: row for row in json.loads((root / 'manifests/full-native-apps.json').read_text())['applications']}
        self.assertEqual(set(smoke.APPS), {'photo', 'vector', 'film', 'light', 'pdf', 'effect', 'design', 'ui', 'sound', 'cad'})
        for app, (_, version, commit, _) in smoke.APPS.items():
            with self.subTest(app=app):
                self.assertEqual(commit, locks[app]['source']['commit'])
                self.assertEqual(version, locks[app]['upstreamVersion'])
                self.assertEqual(smoke.plan(app)['status'], 'not_run')
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(smoke.main(['--app', app, '--plan']), 0)
                self.assertEqual(json.loads(output.getvalue())['status'], 'not_run')

    def test_all_five_png_filters_decode_known_red_green_blue_white_pixels(self):
        # Manually specified PNG scanlines for the same 2x2 image. The expected
        # pixel colors do not depend on the application's renderer or decoder.
        scanlines = [
            bytes([0, 255,0,0,255, 0,255,0,255, 0, 0,0,255,255, 255,255,255,255]),
            bytes([1, 255,0,0,255, 1,255,0,0, 1, 0,0,255,255, 255,255,0,0]),
            bytes([2, 255,0,0,255, 0,255,0,255, 2, 1,0,255,0, 255,0,255,0]),
            bytes([3, 255,0,0,255, 129,255,0,128, 3, 129,0,255,128, 255,128,128,0]),
            bytes([4, 255,0,0,255, 1,255,0,0, 4, 1,0,255,0, 255,0,0,0]),
        ]
        expected = bytes([255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,255,255])
        for mode, raw in enumerate(scanlines):
            with self.subTest(mode=mode):
                image = smoke.decode_png(png(raw))
                self.assertEqual((image['width'], image['height']), (2, 2))
                self.assertEqual(image['pixels'], expected)

    def test_png_16bit_gray_alpha_and_corrupt_or_excessive_payloads(self):
        image = smoke.decode_png(png(b'\0\x12\x34\xab\xcd', width=1, height=1, depth=16, color=4))
        self.assertEqual(image['pixels'], b'\x12\x12\x12\xab')
        valid = png(bytes([0,1,2,3,255]), width=1, height=1)
        invalid = bytearray(valid)
        invalid[-1] ^= 1
        for data in (bytes(invalid), valid[:-5], png(bytes([0,1,2,3,255,7]), width=1, height=1), png(b'\0', width=100000, height=1)):
            with self.assertRaises((AssertionError, zlib.error)):
                smoke.decode_png(data)

    def test_pcm24_and_float_waveforms_have_independent_sample_oracles(self):
        pcm = smoke.decode_wav(wav(b'\0\0\0\xff\xff\x7f\0\0\x80'))
        self.assertEqual((pcm['rate'], pcm['frames'], pcm['bits']), (48000, 3, 24))
        self.assertEqual(pcm['samples'], [0, 1 - 2**-23, -1])
        self.assertAlmostEqual(pcm['rms'], math.sqrt(((1 - 2**-23)**2 + 1) / 3))
        floating = smoke.decode_wav(wav(struct.pack('<fff', .25, -.5, .75), encoding=3, bits=32))
        self.assertEqual(floating['samples'], [.25, -.5, .75])
        self.assertAlmostEqual(floating['rms'], math.sqrt((.25**2 + .5**2 + .75**2) / 3))

    def test_wave_truncation_frame_alignment_and_nonfinite_samples_fail(self):
        valid = wav(b'\0\0\0')
        for data in (valid[:-1], valid + b'trailing', wav(b'\0\0'), wav(struct.pack('<f', float('nan')), encoding=3, bits=32)):
            with self.assertRaises(AssertionError):
                smoke.decode_wav(data)

    def test_dxf_readback_uses_real_group_pairs_and_requires_complete_eof(self):
        text = '0\nSECTION\n2\nENTITIES\n0\nLINE\n10\n0\n20\n0\n11\n3\n21\n4\n0\nCIRCLE\n10\n10\n20\n10\n40\n2.5\n0\nENDSEC\n0\nEOF\n'
        entities = smoke.dxf_entities(text)
        self.assertEqual([row['type'] for row in entities], ['LINE', 'CIRCLE'])
        line = entities[0]['groups']
        self.assertEqual([float(line[key][0]) for key in (10, 20, 11, 21)], [0, 0, 3, 4])
        self.assertEqual(float(entities[1]['groups'][40][0]), 2.5)
        for malformed in (text[:-4], text + '0\n'):
            with self.assertRaises((AssertionError, ValueError)):
                smoke.dxf_entities(malformed)

    def test_pdf_fixture_cross_reference_and_actual_uncompressed_page_count(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'fixture.pdf'
            documents._pdf_fixture(file)
            data = file.read_bytes()
            result = smoke.inspect_pdf(data)
            self.assertEqual(result['pageObjects'], 2)
            self.assertEqual(result['objectStreams'], 0)
            self.assertTrue(data[result['xrefOffset']:].startswith(b'xref'))
            for invalid in (data[:-20], data.replace(b'startxref\n', b'startxref\n999999999', 1)):
                with self.assertRaises(AssertionError):
                    smoke.inspect_pdf(invalid)

    def test_pdf_flate_object_stream_contains_real_page_not_only_signature(self):
        encoded = zlib.compress(b'4 0 << /Type /Page /Parent 2 0 R >>')
        data = b'%PDF-1.7\n'
        offset = len(data)
        data += b'1 0 obj\n<< /Type /ObjStm /N 1 /First 4 /Filter /FlateDecode /Length ' + str(len(encoded)).encode() + b' >>\nstream\n' + encoded + b'\nendstream\nendobj\n'
        data += b'startxref\n' + str(offset).encode() + b'\n%%EOF\n'
        result = smoke.inspect_pdf(data)
        self.assertEqual((result['pageObjects'], result['objectStreams']), (1, 1))
        with self.assertRaises(AssertionError):
            smoke.inspect_pdf(data.replace(b'/FlateDecode', b'/LZWDecode'))

    def test_wrong_real_executable_is_failed_report_with_actual_hash_not_a_mock_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'fresh'
            with contextlib.redirect_stdout(io.StringIO()):
                status = smoke.main(['--app', 'photo', '--cli', str(Path(sys.executable).resolve()), '--output', str(output)])
            self.assertEqual(status, 1)
            report = json.loads((output / 'report.json').read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['steps'][0]['args'], ['--version'])
            self.assertFalse(report['checks'][0]['passed'])
            self.assertNotIn('status', report['contract'])
            self.assertEqual(report['cliSha256'], hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest())
            self.assertEqual(len(report['steps']), 1)

    def test_existing_output_is_preserved_and_relative_cli_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sentinel = output / 'keep.txt'
            sentinel.write_text('untouched')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                smoke.main(['--app', 'photo', '--cli', str(Path(sys.executable).resolve()), '--output', str(output)])
            self.assertEqual(sentinel.read_text(), 'untouched')
            self.assertFalse((output / 'report.json').exists())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                smoke.main(['--app', 'photo', '--cli', 'relative-cli', '--output', str(output / 'fresh')])


if __name__ == '__main__':
    unittest.main()
