import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import tomllib
import unittest
import zlib
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bogo_runtime_icons as icons


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def png_bytes(width, height, raw, color=6, depth=8, interlace=0, compressed=None):
    header = struct.pack('>IIBBBBB', width, height, depth, color, 0, 0, interlace)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raw) if compressed is None else compressed) + chunk(b'IEND', b'')


def write_png(path, width, height, pixels, channels=4, method=0):
    stride = width * channels
    previous = bytes(stride)
    rows = bytearray()
    for y in range(height):
        row = pixels[y * stride:(y + 1) * stride]
        encoded = bytearray()
        for x, value in enumerate(row):
            left = row[x - channels] if x >= channels else 0
            up = previous[x]
            corner = previous[x - channels] if x >= channels else 0
            if method == 0:
                predictor = 0
            elif method == 1:
                predictor = left
            elif method == 2:
                predictor = up
            elif method == 3:
                predictor = (left + up) // 2
            else:
                p = left + up - corner
                a, b, c = abs(p - left), abs(p - up), abs(p - corner)
                predictor = left if a <= b and a <= c else up if b <= c else corner
            encoded.append((value - predictor) & 255)
        rows.extend(bytes([method]) + encoded)
        previous = row
    Path(path).write_bytes(png_bytes(width, height, rows, 6 if channels == 4 else 2))


def put_pixel(pixels, x, y, rgba, width=64):
    index = (y * width + x) * 4
    pixels[index:index + 4] = bytes(rgba)


class FakeWindow:
    def __init__(self, owner=42, values=None, owners=None, timeout=False):
        self.pid = owner
        self.owners = iter(owners) if owners is not None else None
        self.values = values or {2: 100, 0: 101, 1: 102}
        self.timeout = timeout
        self.calls = []

    def owner(self, hwnd):
        self.calls.append(('owner', hwnd))
        return True, next(self.owners) if self.owners is not None else self.pid

    def get_icon(self, hwnd, kind, timeout):
        self.calls.append(('get', hwnd, kind, timeout))
        if self.timeout:
            raise TimeoutError('mock bounded window timeout')
        return self.values.get(kind, 0)

    def class_icon(self, hwnd, index):
        self.calls.append(('class', hwnd, index))
        return self.values.get(index, 0)


class OwnershipTests(unittest.TestCase):
    def test_every_message_uses_known_owner_and_timeout_and_borrowed_handles(self):
        api = FakeWindow()
        rows = icons.collect_icon_handles(1234, 42, api)
        self.assertEqual([r['handle'] for r in rows], [100, 101, 102])
        self.assertEqual(api.calls, [('owner', 1234), ('get', 1234, 2, 1000), ('owner', 1234),
                                     ('owner', 1234), ('get', 1234, 0, 1000), ('owner', 1234),
                                     ('owner', 1234), ('get', 1234, 1, 1000), ('owner', 1234)])
        self.assertIn('DestroyIcon(owned)', icons.POWERSHELL)
        self.assertIn('ReleaseReference($ownedReference)', icons.POWERSHELL)
        self.assertNotIn('ReleaseReference($handle)', icons.POWERSHELL)
        self.assertNotIn('DestroyIcon($handle)', icons.POWERSHELL)
        self.assertIn('$borrowed.Clone()', icons.POWERSHELL)
        self.assertIn('$clone.Dispose()', icons.POWERSHELL)
        self.assertNotIn('$borrowed.Dispose()', icons.POWERSHELL)
        self.assertNotIn('EnumWindows', icons.POWERSHELL)
        self.assertNotIn('GetDesktopWindow', icons.POWERSHELL)
        source = (Path(__file__).resolve().parents[1] / 'scripts/bogo_runtime_icons.py').read_text(encoding='utf-8')
        self.assertNotIn("'-ExecutionPolicy'", source)
        self.assertNotIn('from PIL', source)
        self.assertIn('CreateIconFromResourceEx(png, (uint)png.Length, true, 0x00030000, width, height, 0)', icons.POWERSHELL)

    def test_mismatched_or_changed_owner_stops_before_more_native_calls(self):
        api = FakeWindow(owner=99)
        with self.assertRaises(ValueError):
            icons.collect_icon_handles(1234, 42, api)
        self.assertEqual(api.calls, [('owner', 1234)])
        api = FakeWindow(owners=[42, 99])
        with self.assertRaises(ValueError):
            icons.collect_icon_handles(1234, 42, api)
        self.assertEqual(api.calls, [('owner', 1234), ('get', 1234, 2, 1000), ('owner', 1234)])

    def test_fallback_is_owner_checked_and_missing_or_hung_icons_refuse(self):
        api = FakeWindow(values={-34: 500, -14: 501})
        rows = icons.collect_icon_handles(1234, 42, api)
        self.assertEqual([r['handle'] for r in rows], [500, 500, 501])
        self.assertTrue(all(r['source'].startswith('GetClassLongPtr/') for r in rows))
        with self.assertRaises(ValueError):
            icons.collect_icon_handles(1234, 42, FakeWindow(values={9: 0}))
        with self.assertRaises(TimeoutError):
            icons.collect_icon_handles(1234, 42, FakeWindow(timeout=True))
        for hwnd, pid in [(0, 42), (-1, 42), (1234, 0)]:
            with self.assertRaises(ValueError):
                icons.collect_icon_handles(hwnd, pid, FakeWindow())


class PngDecoderTests(unittest.TestCase):
    def test_rgb_and_rgba_all_five_filters_decode_exact_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'pixels.png'
            for channels in (3, 4):
                pixels = bytes((x * 17 + y * 43 + c * 61) % 256 for y in range(4) for x in range(5) for c in range(channels))
                expected = pixels if channels == 4 else b''.join(pixels[i:i + 3] + b'\xff' for i in range(0, len(pixels), 3))
                for method in range(5):
                    with self.subTest(channels=channels, method=method):
                        write_png(path, 5, 4, pixels, channels, method)
                        size, decoded, digest = icons._png_rgba(path)
                        self.assertEqual(size, (5, 4))
                        self.assertEqual(decoded, expected)
                        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_crc_geometry_zlib_bombs_and_unsupported_formats_are_refused(self):
        valid = png_bytes(1, 1, b'\0\1\2\3\xff')
        wrong_crc = valid[:-1] + bytes([valid[-1] ^ 1])
        cases = [wrong_crc, valid[:-1], valid + b'extra',
                 png_bytes(513, 1, b''), png_bytes(1, 513, b''),
                 png_bytes(1, 1, bytes(2 * 1024 * 1024)),
                 png_bytes(1, 1, b'\5\1\2\3\xff'),
                 png_bytes(1, 1, b'\0\1\2\3\xff', depth=16),
                 png_bytes(1, 1, b'\0\1\2\3\xff', color=3),
                 png_bytes(1, 1, b'\0\1\2\3\xff', interlace=1),
                 png_bytes(1, 1, b'', compressed=zlib.compress(b'\0\1\2\3\xff') + b'junk')]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'bad.png'
            for number, data in enumerate(cases):
                with self.subTest(number=number):
                    path.write_bytes(data)
                    with self.assertRaises(ValueError):
                        icons._png_rgba(path)
            path.write_bytes(b'\x89PNG\r\n\x1a\n' + bytes(icons.MAX_PNG_BYTES))
            with self.assertRaises(ValueError):
                icons._png_rgba(path)

    def test_chunk_order_transparency_and_unknown_critical_chunks_refuse(self):
        header = chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
        body = zlib.compress(b'\0\1\2\3\xff')
        cases = [chunk(b'IDAT', body) + header + chunk(b'IEND', b''),
                 header + chunk(b'ABCD', b'') + chunk(b'IDAT', body) + chunk(b'IEND', b''),
                 header + chunk(b'tRNS', b'\0\0') + chunk(b'IDAT', body) + chunk(b'IEND', b''),
                 header + chunk(b'IDAT', body[:2]) + chunk(b'tEXt', b'a\0b') + chunk(b'IDAT', body[2:]) + chunk(b'IEND', b'')]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'bad.png'
            for data in cases:
                path.write_bytes(b'\x89PNG\r\n\x1a\n' + data)
                with self.assertRaises(ValueError):
                    icons._png_rgba(path)

    def test_1024_requires_explicit_approved_source_bound_and_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'approved-runtime.png'
            rgba = bytes((252, 117, 1, 255)) * (1024 * 1024)
            raw = b''.join(b'\0' + rgba[y * 4096:(y + 1) * 4096] for y in range(1024))
            path.write_bytes(png_bytes(1024, 1024, raw))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                icons._png_rgba(path)
            approved, size, decoded = icons.approved_runtime_png(path, digest)
            self.assertEqual((approved, size), (path.resolve(), (1024, 1024)))
            self.assertEqual(decoded, rgba)
            with self.assertRaises(ValueError):
                icons.approved_runtime_png(path, '0' * 64)
            path.write_bytes(png_bytes(1025, 1, b''))
            with self.assertRaises(ValueError):
                icons.approved_runtime_png(path, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_reference_uses_exact_winit_bgra_and_wrapping_alpha_mask_without_scaling(self):
        raw = bytes((1, 2, 3, 0, 4, 5, 6, 128, 7, 8, 9, 255))
        mask, bgra = icons.winit_reference_bytes(raw, 3, 1)
        self.assertEqual(mask, bytes((1, 129, 0)))
        self.assertEqual(bgra, bytes((3, 2, 1, 0, 6, 5, 4, 128, 9, 8, 7, 255)))
        self.assertEqual(raw, bytes((1, 2, 3, 0, 4, 5, 6, 128, 7, 8, 9, 255)))
        with self.assertRaises(ValueError):
            icons.winit_reference_bytes(raw, 4, 1)
        self.assertIn('CreateIcon(IntPtr.Zero, width, height, 1, 32, mask, bgra)', icons.POWERSHELL)
        self.assertIn('runtime dimensions differ from approved PNG; no resizing is permitted', icons.POWERSHELL)


class ReferenceContractTests(unittest.TestCase):
    def test_source_manifest_and_entire_transitive_lock_are_pinned(self):
        tool = Path(__file__).resolve().parents[1] / 'tools/runtime-icon-reference'
        contract = json.loads((tool / 'reference-contract.json').read_text(encoding='utf-8'))
        for relative, key in [('Cargo.toml', 'referenceCargoManifestSha256'), ('Cargo.lock', 'referenceCargoLockSha256'), ('src/main.rs', 'referenceRustSourceSha256')]:
            self.assertEqual(hashlib.sha256((tool / relative).read_bytes()).hexdigest(), contract[key])
        manifest = tomllib.loads((tool / 'Cargo.toml').read_text(encoding='utf-8'))
        self.assertEqual(manifest['dependencies']['image'], {'version': '=0.25.10', 'default-features': False, 'features': ['png']})
        self.assertEqual(len(contract['reviewedApplicationLocks']), 14)
        for app, digest in contract['reviewedApplicationLocks'].items():
            lock = icons.application_lock_for(app)
            self.assertEqual(hashlib.sha256(lock.read_bytes()).hexdigest(), digest)
        with self.assertRaises(ValueError):
            icons.application_lock_for('../../unrelated')
        for package in tomllib.loads((tool / 'Cargo.lock').read_text(encoding='utf-8'))['package']:
            if package.get('source'):
                self.assertEqual(len(package['checksum']), 64)
        self.assertEqual(contract['imageVersion'], '0.25.10')
        self.assertEqual(contract['eframeVersion'], '0.36.2')
        source = (tool / 'src/main.rs').read_text(encoding='utf-8')
        self.assertIn('image::imageops::Lanczos3', source)
        self.assertIn('image::ImageFormat::Png', source)
        self.assertIn('width != height', source)

    def test_unknown_application_lock_is_refused_without_compiling(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'Cargo.lock'
            path.write_text('version = 4\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'not reviewed'):
                icons.reference_contract(path)

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES'), 'set BOGO_NATIVE_ARCHIVES for all14 authenticated lock checks')
    def test_every_published_application_lock_matches_the_reference_closure(self):
        tool = Path(__file__).resolve().parents[1] / 'tools/runtime-icon-reference'
        contract = json.loads((tool / 'reference-contract.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'Cargo.lock'
            for app in contract['reviewedApplicationLocks']:
                archive = next((Path(os.environ['BOGO_NATIVE_ARCHIVES']) / app).glob('*-source.zip'))
                with zipfile.ZipFile(archive) as z:
                    choices = [n for n in z.namelist() if len(Path(n).parts) == 2 and Path(n).name == 'Cargo.lock'
                               and hashlib.sha256(z.read(n)).hexdigest() == contract['reviewedApplicationLocks'][app]]
                    self.assertEqual(len(choices), 1)
                    path.write_bytes(z.read(choices[0]))
                _, checked = icons.reference_contract(path)
                self.assertEqual(checked['applicationCargoLockSha256'], contract['reviewedApplicationLocks'][app])


class PixelTests(unittest.TestCase):
    def icon(self, path, alternate=False):
        pixels = bytearray(64 * 64 * 4)
        for y in range(8, 56):
            for x in range(8, 56):
                color = (255, 255, 255, 255) if 21 <= x <= 42 and 21 <= y <= 42 else (252, 117, 1, 255)
                if alternate and 27 <= x <= 36:
                    color = (252, 117, 1, 255)
                put_pixel(pixels, x, y, color)
        write_png(path, 64, 64, pixels)
        return pixels

    def test_exact_pixels_and_invisible_rgb_normalization(self):
        with tempfile.TemporaryDirectory() as temporary:
            a, b = Path(temporary) / 'a.png', Path(temporary) / 'b.png'
            pixels = self.icon(a)
            put_pixel(pixels, 0, 0, (123, 99, 88, 0))
            write_png(b, 64, 64, pixels)
            result = icons.compare_icon_pngs(a, b)
            self.assertTrue(result['passed'] and result['exact'])
            self.assertEqual(result['actualRgbaSha256'], result['expectedRgbaSha256'])
            self.assertNotEqual(result['actualPngSha256'], result['expectedPngSha256'])

    def test_small_edge_quantization_passes_but_wrong_program_recolor_and_blank_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            a, b = Path(temporary) / 'a.png', Path(temporary) / 'b.png'
            pixels = self.icon(a)
            put_pixel(pixels, 8, 28, (251, 117, 1, 255))
            write_png(b, 64, 64, pixels)
            result = icons.compare_icon_pngs(b, a)
            self.assertTrue(result['passed'] and not result['exact'])
            self.assertFalse(icons.compare_icon_pngs(b, a, allow_edge_tolerance=False)['passed'])
            self.icon(b, alternate=True)
            self.assertFalse(icons.compare_icon_pngs(b, a)['passed'])
            pixels = self.icon(b)
            write_png(b, 64, 64, bytes(max(0, value - 30) for value in pixels))
            self.assertFalse(icons.compare_icon_pngs(b, a)['passed'])
            write_png(b, 64, 64, bytes(64 * 64 * 4))
            self.assertFalse(icons.compare_icon_pngs(b, a)['passed'])
            self.assertFalse(icons.compare_icon_pngs(b, b)['passed'])
            write_png(b, 32, 32, bytes((252, 117, 1, 255)) * (32 * 32))
            self.assertFalse(icons.compare_icon_pngs(b, a)['passed'])

    def test_owner_derived_ico_hash_is_mandatory_and_links_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            png, ico = root / 'owner.png', root / 'owner.ico'
            self.icon(png)
            image = png.read_bytes()
            ico.write_bytes(struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', 64, 64, 0, 0, 1, 32, len(image), 22) + image)
            digest = hashlib.sha256(ico.read_bytes()).hexdigest()
            self.assertEqual(icons.approved_ico(ico, digest), ico.resolve())
            for bad in ('', 'a' * 64):
                with self.assertRaises(ValueError):
                    icons.approved_ico(ico, bad)
            if os.name != 'nt':
                link = root / 'link.ico'
                link.symlink_to(ico)
                with self.assertRaises(ValueError):
                    icons.approved_ico(link, digest)
            invalid = root / 'invalid.ico'
            invalid.write_bytes(b'not an icon')
            with self.assertRaises(ValueError):
                icons.approved_ico(invalid, hashlib.sha256(invalid.read_bytes()).hexdigest())

    def test_nonwindows_entry_reports_real_execution_pending(self):
        if os.name == 'nt':
            self.skipTest('non-Windows refusal is platform specific')
        with self.assertRaisesRegex(OSError, 'execution pending'):
            icons.check_runtime_icons(1, 2, 'unused.ico', 'a' * 64, 'unused-output')


if __name__ == '__main__':
    unittest.main()
