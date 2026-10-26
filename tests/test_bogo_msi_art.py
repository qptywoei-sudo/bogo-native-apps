import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bogo_msi_art as art


def bitmap(app, role, top_down=False, override=None):
    """Synthetic unit bytes only; these are never actual installer evidence."""
    width, height = 493, 58 if role == 'banner' else 312
    stride = ((width * 3 + 3) // 4) * 4
    rows = []
    for y in range(height):
        row = bytearray(stride)
        for x in range(width):
            colour = art.expected_pixel(app, role, x, y) or (12, 34, 56)
            if override and (x, y) in override:
                colour = override[(x, y)]
            red, green, blue = colour
            row[x * 3:x * 3 + 3] = bytes((blue, green, red))
        rows.append(bytes(row))
    pixels = b''.join(rows if top_down else reversed(rows))
    return b'BM' + struct.pack('<III', 54 + len(pixels), 0, 54) + struct.pack('<IiiHHIIiiII', 40, width, -height if top_down else height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0) + pixels


class Function:
    def __init__(self, implementation):
        self.implementation = implementation
    def __call__(self, *args):
        return self.implementation(*args)


class FakeMsi:
    """Only the read-only database/view/record API vocabulary is implemented."""
    def __init__(self, app='photo', rows=None, streams=None):
        self.rows = rows if rows is not None else [('WelcomeDlg', 'DialogBitmap', 'Custom.Dialog'), ('ProgressDlg', 'BannerBitmap', 'Custom.Banner')]
        self.streams = streams if streams is not None else {'Custom.Banner': bitmap(app, 'banner'), 'Custom.Dialog': bitmap(app, 'dialog'), 'Unreferenced.Secret': b'must not be read'}
        self.views, self.records, self.queries, self.closed, self.view_closed = {}, {}, [], [], []
        self.reads, self.open_modes = [], []
        self.advertised_size = None
        self.fail_read = False
        self.next_handle = 10
        for name, method in [('MsiOpenDatabaseW', self.open_database), ('MsiDatabaseOpenViewW', self.open_view), ('MsiViewExecute', self.execute), ('MsiViewFetch', self.fetch), ('MsiRecordGetStringW', self.string), ('MsiRecordReadStream', self.stream), ('MsiViewClose', self.close_view), ('MsiCloseHandle', self.close_handle)]:
            setattr(self, name, Function(method))

    def number(self, value):
        return value.value if hasattr(value, 'value') else value

    def allocate(self):
        self.next_handle += 1
        return self.next_handle

    def open_database(self, path, persistence, output):
        self.open_modes.append(persistence)
        output._obj.value = 1
        return 0

    def open_view(self, database, query, output):
        assert self.number(database) == 1
        self.queries.append(query)
        if query == "SELECT `Dialog_`, `Control`, `Text` FROM `Control` WHERE `Type` = 'Bitmap'":
            records = [('strings', row) for row in self.rows]
        else:
            match = re.fullmatch(r"SELECT `Data` FROM `Binary` WHERE `Name` = '([A-Za-z_][A-Za-z0-9_.]*)'", query)
            assert match, 'No other SQL operation is supported by this API fixture'
            records = [('stream', self.streams[match[1]])] if match[1] in self.streams else []
        handle = self.allocate()
        self.views[handle] = {'rows': records, 'offset': 0}
        output._obj.value = handle
        return 0

    def execute(self, view, parameters):
        assert parameters == 0
        return 0

    def fetch(self, view, output):
        data = self.views[self.number(view)]
        if data['offset'] >= len(data['rows']):
            return 259
        kind, value = data['rows'][data['offset']]
        data['offset'] += 1
        handle = self.allocate()
        self.records[handle] = {'kind': kind, 'data': value, 'offset': 0}
        output._obj.value = handle
        return 0

    def string(self, record, field, buffer, count):
        value = self.records[self.number(record)]['data'][field - 1]
        if buffer is None:
            count._obj.value = len(value)
            return 234
        buffer.value = value
        count._obj.value = len(value)
        return 0

    def stream(self, record, field, buffer, count):
        assert field == 1
        data = self.records[self.number(record)]
        if buffer is None:
            count._obj.value = self.advertised_size if self.advertised_size is not None else len(data['data'])
            return 0
        self.reads.append(count._obj.value)
        if self.fail_read:
            return 1603
        chunk = data['data'][data['offset']:data['offset'] + count._obj.value]
        ctypes.memmove(buffer, chunk, len(chunk))
        count._obj.value = len(chunk)
        data['offset'] += len(chunk)
        return 0

    def close_view(self, handle):
        self.view_closed.append(self.number(handle))
        return 0

    def close_handle(self, handle):
        self.closed.append(self.number(handle))
        return 0


class MsiArtworkTests(unittest.TestCase):
    def test_profile_coordinates_match_reviewed_installer_generator_geometry(self):
        for app in ('photo', 'ui', 'vector'):
            self.assertEqual(art.expected_pixel(app, 'banner', 20, 20), art.BACKGROUND)
            self.assertEqual(art.expected_pixel(app, 'dialog', 10, 40), art.HEADER)
            self.assertEqual(art.expected_pixel(app, 'dialog', 161, 40), art.ACCENT)
            self.assertEqual(art.expected_pixel(app, 'dialog', 200, 40), art.BACKGROUND)
            self.assertIsNone(art.expected_pixel(app, 'dialog', 20, 80))
        self.assertEqual(art.expected_pixel('launcher', 'banner', 400, 40), art.BACKGROUND)
        self.assertEqual(art.expected_pixel('launcher', 'banner', 406, 40), art.ACCENT)
        self.assertEqual(art.expected_pixel('launcher', 'banner', 490, 40), art.HEADER)
        self.assertIsNone(art.expected_pixel('launcher', 'banner', 440, 20))
        self.assertEqual(art.expected_pixel('launcher', 'dialog', 163, 40), art.ACCENT)
        self.assertIsNone(art.expected_pixel('launcher', 'dialog', 40, 150))
        self.assertEqual(art.expected_pixel('light', 'banner', 400, 40), art.HEADER)
        self.assertEqual(art.expected_pixel('light', 'dialog', 100, 40), art.HEADER)
        self.assertEqual(art.expected_pixel('light', 'dialog', 200, 40), art.BACKGROUND)

    def test_exact_five_profiles_accept_flat_backgrounds_and_exclude_approved_icons_and_text(self):
        self.assertEqual(art.CUSTOM_APPS, {'launcher', 'photo', 'ui', 'vector', 'light'})
        for app in sorted(art.CUSTOM_APPS):
            for role in ('banner', 'dialog'):
                with self.subTest(app=app, role=role):
                    raw = bitmap(app, role)
                    width, height, rows = art.decode_bmp(raw)
                    report = art.verify_palette(app, role, width, height, rows)
                    self.assertGreater(report['verifiedFlatPixels'], 10000)
                    if app != 'light':
                        self.assertGreater(report['excludedIconTextAndEdgePixels'], 0)
                    png = art.png_bytes(width, height, rows)
                    self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
                    self.assertEqual(struct.unpack_from('>II', png, 16), (493, 58 if role == 'banner' else 312))
                    # Decode the generated IDAT to prove preview pixels are the original BMP pixels.
                    offset, compressed = 8, b''
                    while offset < len(png):
                        length = struct.unpack_from('>I', png, offset)[0]
                        kind, data = png[offset + 4:offset + 8], png[offset + 8:offset + 8 + length]
                        self.assertEqual(struct.unpack_from('>I', png, offset + 8 + length)[0], zlib.crc32(kind + data) & 0xffffffff)
                        if kind == b'IDAT': compressed += data
                        offset += length + 12
                    self.assertEqual(zlib.decompress(compressed), b''.join(b'\0' + row for row in rows))

    def test_old_dark_blue_yellow_or_one_changed_flat_pixel_is_rejected(self):
        for app in sorted(art.CUSTOM_APPS):
            for wrong in ((18, 19, 22), (45, 129, 255), (253, 215, 4)):
                with self.subTest(app=app, colour=wrong):
                    width, height, rows = art.decode_bmp(bitmap(app, 'banner', override={(20, 20): wrong}))
                    with self.assertRaisesRegex(ValueError, 'flat-pixel mismatch'):
                        art.verify_palette(app, 'banner', width, height, rows)

    def test_bmp_orientation_bounds_compression_and_dimensions_are_checked(self):
        bottom = art.decode_bmp(bitmap('light', 'dialog'))
        top = art.decode_bmp(bitmap('light', 'dialog', top_down=True))
        self.assertEqual(bottom, top)
        raw = bitmap('photo', 'banner')
        malformed = [raw[:-1], b'XX' + raw[2:], raw + b'outside']
        for offset, fmt, value in [(10, '<I', 2), (18, '<i', 10000), (22, '<i', -2147483648), (28, '<H', 32), (30, '<I', 1)]:
            changed = bytearray(raw)
            struct.pack_into(fmt, changed, offset, value)
            malformed.append(bytes(changed))
        for data in malformed:
            with self.assertRaises(ValueError): art.decode_bmp(data)
        with patch.object(art, 'MAX_BITMAP_BYTES', 100), self.assertRaises(ValueError): art.decode_bmp(raw)

    def test_msi_database_is_read_only_and_reads_only_actual_bitmap_control_references(self):
        api = FakeMsi()
        with art._Database('synthetic-owned-candidate.msi', _api=api) as database:
            with self.assertRaisesRegex(ValueError, 'unreferenced'):
                database.binary('Unreferenced.Secret')
            controls = database.bitmap_controls()
            self.assertEqual({row['binary'] for row in controls}, {'Custom.Banner', 'Custom.Dialog'})
            self.assertEqual(database.binary('Custom.Banner'), api.streams['Custom.Banner'])
            self.assertEqual(database.binary('Custom.Dialog'), api.streams['Custom.Dialog'])
        self.assertEqual(api.open_modes, [None], 'MSIDBOPEN_READONLY is null; no write/transaction mode')
        self.assertFalse(any('Unreferenced.Secret' in query for query in api.queries))
        self.assertTrue(all(query.startswith('SELECT ') for query in api.queries))
        self.assertTrue(api.reads and max(api.reads) <= art.CHUNK)
        self.assertEqual(set(api.closed), {1, *api.views, *api.records})
        self.assertEqual(set(api.view_closed), set(api.views))
        self.assertEqual(ctypes.sizeof(api.MsiRecordReadStream.argtypes[-1]._type_), 4)

    def test_msi_api_stub_refuses_huge_stream_unbound_strings_and_closes_handles_on_read_failure(self):
        for advertised, fail_read in [(art.MAX_BITMAP_BYTES + 1, False), (None, True)]:
            api = FakeMsi()
            api.advertised_size, api.fail_read = advertised, fail_read
            with self.assertRaises(ValueError), art._Database('synthetic.msi', _api=api) as database:
                database.bitmap_controls()
                database.binary('Custom.Banner')
            self.assertEqual(set(api.closed), {1, *api.views, *api.records})
            if advertised:
                self.assertEqual(api.reads, [], 'oversized stream must be rejected before reading content')
        invalid_rows = [[('Welcome', 'Bitmap', "Bad' SQL")], [('Welcome', 'Bitmap', '[DynamicProperty]')], [('Welcome', 'Bitmap', 'A' * 129)], [('A', 'Bitmap', 'A'), ('B', 'Bitmap', 'B'), ('C', 'Bitmap', 'C')], [('D' + str(index), 'Bitmap', 'A' if index % 2 else 'B') for index in range(129)]]
        for rows in invalid_rows:
            api = FakeMsi(rows=rows)
            with self.assertRaises(ValueError), art._Database('synthetic.msi', _api=api) as database:
                database.bitmap_controls()
            self.assertEqual(api.reads, [])

    def test_public_hook_saves_original_bmp_exact_preview_and_bound_receipt_without_running_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            msi = base / 'unit-fixture.msi'
            msi.write_bytes(b'opaque MSI API stub input; never installed')
            lock = {'version': '0.9.0-bogo.1', 'bogoOverlay': {'sourceTreeSha256': 'a' * 64, 'patchSha256': 'b' * 64}}
            api, database_type = FakeMsi(), art._Database
            with patch.object(art, 'runner_scope', return_value=base), patch.object(art, 'validated_input', return_value=(msi, lock, art.bogo.digest(msi))), patch.object(art, '_Database', side_effect=lambda path: database_type(path, _api=api)):
                report = art.verify_msi_art(msi, 'photo', base / 'readback')
                self.assertEqual(report['status'], 'passed')
                self.assertFalse(report['installerActionsExecuted'])
                self.assertTrue(report['msiUnchanged'])
                self.assertEqual(report['actualBinaryStreamsRead'], 2)
                for row in report['bitmaps']:
                    self.assertEqual((base / 'readback' / row['originalBmp']).read_bytes(), api.streams[row['binary']])
                    self.assertEqual(hashlib.sha256(api.streams[row['binary']]).hexdigest(), row['sha256'])
                with self.assertRaisesRegex(ValueError, 'fresh'):
                    art.verify_msi_art(msi, 'photo', base / 'readback')
                with self.assertRaises(ValueError):
                    art.verify_msi_art(msi, 'photo', base.parent / 'outside')

    def test_failed_palette_retains_true_readback_and_other_nine_are_explicitly_not_applicable(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            msi = base / 'unit-fixture.msi'
            msi.write_bytes(b'opaque unit input')
            lock = {'version': '0.9.0-bogo.1', 'bogoOverlay': {'sourceTreeSha256': 'a' * 64, 'patchSha256': 'b' * 64}}
            api, database_type = FakeMsi(), art._Database
            api.streams['Custom.Banner'] = bitmap('photo', 'banner', override={(20, 20): (255, 215, 4)})
            with patch.object(art, 'runner_scope', return_value=base), patch.object(art, 'validated_input', return_value=(msi, lock, art.bogo.digest(msi))), patch.object(art, '_Database', side_effect=lambda path: database_type(path, _api=api)):
                with self.assertRaisesRegex(ValueError, 'flat-pixel mismatch'):
                    art.verify_msi_art(msi, 'photo', base / 'failed')
            report = json.loads((base / 'failed/msi-art.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'failed')
            self.assertTrue(report['bitmaps'])
            self.assertFalse(report['installerActionsExecuted'])
        with patch.object(art, '_Database', side_effect=AssertionError('No database read expected')):
            other = set(art.bogo.NAMES) - set(art.CUSTOM_APPS)
            self.assertEqual(len(other), 9)
            for app in other:
                result = art.verify_msi_art('/not-read', app, '/not-created')
                self.assertEqual(result['status'], 'not-applicable')
                self.assertEqual(result['actualBinaryStreamsRead'], 0)

    def test_actual_input_is_exact_candidate_provenance_bound_and_private_or_non_ci_paths_are_refused(self):
        lock = art.bogo.load_lock('photo')
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            candidate = base / 'input/candidate'
            candidate.mkdir(parents=True)
            prefix = art.bogo.full.artifact_base(lock, 'windows-x64')
            (candidate / (prefix + '.msi')).write_bytes(b'opaque MSI fixture; no executable actions')
            (candidate / (prefix + '.zip')).write_bytes(b'opaque ZIP fixture')
            provenance = {'schema': 1, 'app': 'photo', 'version': lock['version'], 'platform': 'windows-x64', 'inputs': {'lock': lock, 'sourceTreeSha256': lock['bogoOverlay']['sourceTreeSha256'], 'bogoOverlay': {'path': lock['bogoOverlay']['patch'], 'sha256': lock['bogoOverlay']['patchSha256']}}}
            (candidate / (prefix + '-provenance.json')).write_text(json.dumps(provenance), encoding='utf-8')
            art.bogo.full.finalize(candidate, lock, 'windows-x64')
            msi = candidate / (prefix + '.msi')
            receipt = {'schema': 'bogo.windows-artifact-input.v1', 'repository': 'qptywoei-sudo/bogo-native-apps', 'app': 'photo', 'status': 'verified', 'harnessSha': 'c' * 40, 'sourceTreeSha256': lock['bogoOverlay']['sourceTreeSha256'], 'overlaySha256': lock['bogoOverlay']['patchSha256'], 'files': [{'filename': msi.name, 'sha256': art.bogo.digest(msi), 'bytes': msi.stat().st_size}]}
            receipt_path = candidate.parent / 'authenticated-build.json'
            receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
            with patch.dict(os.environ, {'GITHUB_WORKSPACE': str(ROOT.resolve()), 'GITHUB_SHA': 'c' * 40}):
                accepted = art.validated_input(msi, 'photo', base)
                self.assertEqual(accepted[0], msi)
                receipt['files'][0]['sha256'] = 'd' * 64
                receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'candidate MSI hash'):
                    art.validated_input(msi, 'photo', base)
                private = base / msi.name
                private.write_bytes(b'not an owned candidate')
                with self.assertRaisesRegex(ValueError, 'outside the fixed'):
                    art.validated_input(private, 'photo', base)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'hosted Windows'):
                art.runner_scope()


if __name__ == '__main__':
    unittest.main()
