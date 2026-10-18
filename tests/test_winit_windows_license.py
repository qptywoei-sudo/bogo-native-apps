import base64
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import kio_native as builder

PIN = {'name': 'winit', 'version': '0.30.13', 'source': 'git+https://github.com/skylartaylor/winit.git?rev=3d51077fd1a966f84df9ef287839dc84fd5b4ca7#3d51077fd1a966f84df9ef287839dc84fd5b4ca7'}
ORIGINAL = base64.b64decode((Path(__file__).parent / 'fixtures/winit-LICENSE.txt.b64').read_text(encoding='ascii').strip(), validate=True)


class WinitWindowsLicense(unittest.TestCase):
    def folder(self, root, data):
        (root / 'dpi').mkdir()
        (root / 'LICENSE').write_bytes(data)
        return root / 'dpi/LICENSE'

    def test_actual_original_and_windows_checkout_bytes_are_authenticated(self):
        self.assertEqual(hashlib.sha256(ORIGINAL).hexdigest(), '6dc0e068dcf3a5bc8e054205b85b7720e1d49265bbc64bf515d2cf79197df69a')
        for data in [ORIGINAL, ORIGINAL.replace(b'\n', b'\r\n')]:
            with self.subTest(bytes=len(data)), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                link = self.folder(root, data)
                link.write_bytes(b'../LICENSE')
                files = dict(builder.dependency_source_files(PIN, root))
                self.assertEqual(files['dpi/LICENSE'].read_bytes(), data)
                (root / 'LICENSE').write_bytes(data + b'X')
                with self.assertRaisesRegex(ValueError, 'original license changed'):
                    builder.dependency_source_files(PIN, root)

    @unittest.skipIf(os.name == 'nt', 'Unix fixture creates a real link; actual Windows symlink is checked by the native preflight')
    def test_windows_link_spelling_keeps_the_same_real_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            # macOS aliases /var to /private/var. Match the builder's canonical
            # path so this actually exercises the Windows link spelling there.
            root = Path(temporary).resolve()
            link = self.folder(root, ORIGINAL.replace(b'\n', b'\r\n'))
            link.symlink_to('../LICENSE')
            original_readlink = os.readlink
            first = True
            def windows_spelling(path, *args, **kwargs):
                nonlocal first
                if Path(path) == link and first:
                    first = False
                    return '..\\LICENSE'
                return original_readlink(path, *args, **kwargs)
            with patch.object(builder.os, 'readlink', side_effect=windows_spelling):
                self.assertEqual(dict(builder.dependency_source_files(PIN, root))['dpi/LICENSE'], root / 'LICENSE')
            self.assertFalse(first, 'the simulated Windows spelling must be exercised')

    def test_other_link_or_package_identity_is_not_an_exception(self):
        for text in [b'../OTHER', b'../LICENSE\n', b'../../LICENSE', b'..\\LICENSE']:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                link = self.folder(root, ORIGINAL)
                link.write_bytes(text)
                with self.assertRaisesRegex(ValueError, 'link target changed'):
                    builder.dependency_source_files(PIN, root)


if __name__ == '__main__':
    unittest.main()
