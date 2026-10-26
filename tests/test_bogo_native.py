import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bogo_native as bogo
import bogo_brand as brand


class BogoNativeIdentity(unittest.TestCase):
    def test_all_fourteen_exact_overlays_preserve_legacy_source_locks(self):
        catalog = json.loads(bogo.CATALOG.read_text())
        self.assertEqual(len(catalog['applications']), 14)
        self.assertEqual({r['id'] for r in catalog['applications']}, set(brand.NAMES))
        for app in brand.NAMES:
            legacy, current = bogo.base_lock(app), bogo.load_lock(app)
            self.assertEqual(current['bundleId'], legacy['bundleId'])
            self.assertEqual(current['source'], legacy['source'])
            self.assertEqual(current['branding'], legacy['branding'])
            self.assertEqual(current['cargoArgs'], legacy['cargoArgs'])
            self.assertEqual(current['name'], 'Bogo ' + brand.NAMES[app])
            self.assertEqual(current['bogoOverlay']['windowsInstallerIdentity']['name'], current['name'])

    def test_native_ico_contains_all_shell_resolutions_and_icns_retains_original_1024(self):
        assets = ROOT / 'assets/bogo-program-icons'
        rows = json.loads((assets / 'native-icons.json').read_text())['items']
        self.assertEqual(len(rows), 14)
        original_hashes = set()
        for row in rows:
            original = (assets / row['original']).read_bytes()
            self.assertEqual(hashlib.sha256(original).hexdigest(), row['originalSha256'])
            self.assertEqual(original[24:26], bytes([8, 6]))  # 8-bit RGBA PNG
            original_hashes.add(row['originalSha256'])
            ico = (assets / row['ico']['path']).read_bytes()
            self.assertEqual(hashlib.sha256(ico).hexdigest(), row['ico']['sha256'])
            self.assertEqual(struct.unpack_from('<HH', ico), (0, 1))
            count = struct.unpack_from('<H', ico, 4)[0]
            sizes = []
            for index in range(count):
                offset = 6 + index * 16
                width = ico[offset] or 256
                length, start = struct.unpack_from('<II', ico, offset + 8)
                self.assertLessEqual(start + length, len(ico))
                self.assertEqual(ico[start:start+8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack_from('>I', ico, start + 16)[0], width)
                sizes.append(width)
            self.assertEqual(sizes, [16, 24, 32, 48, 64, 128, 256])
            icns = (assets / row['icns']['path']).read_bytes()
            self.assertEqual(hashlib.sha256(icns).hexdigest(), row['icns']['sha256'])
            self.assertEqual(icns[:4], b'icns')
            self.assertEqual(struct.unpack_from('>I', icns, 4)[0], len(icns))
            offset, high = 8, None
            while offset < len(icns):
                kind, length = icns[offset:offset+4], struct.unpack_from('>I', icns, offset+4)[0]
                self.assertGreaterEqual(length, 8)
                self.assertLessEqual(offset + length, len(icns))
                if kind == b'ic10':
                    high = icns[offset+8:offset+length]
                offset += length
            self.assertEqual(high, original)
        self.assertEqual(len(original_hashes), 14)

    def test_six_language_and_escaped_newline_labels_keep_correct_brand_case(self):
        self.assertEqual(brand.display('About\\nKIO Grid / KIO Launcher를 / KIO Effectについて / KIO Photo設定 / KIO CAD'), 'About\\nBogo Grid / Bogo Launcher를 / Bogo Effectについて / Bogo Photo設定 / Bogo CAD')
        self.assertEqual(brand.display('KIO Wordu / KIO Wordi / KIO Wordban'), 'Bogo Wordu / Bogo Wordi / Bogo Wordban')

    def test_display_brand_does_not_move_existing_pdf_preferences(self):
        storage = '    eframe::storage_dir("KIO PDF")\n'
        self.assertEqual(brand.rust_display(storage), storage)
        self.assertEqual(brand.rust_display('    .with_title("KIO PDF")\n'), '    .with_title("Bogo PDF")\n')

    def test_launcher_bundles_every_editor_original_in_its_actual_program_list(self):
        lock = bogo.load_lock('launcher')
        files = {item['path']: item['after'] for item in lock['bogoOverlay']['files']}
        originals = {r['id']: r['sha256'] for r in json.loads((ROOT / 'assets/bogo-program-icons/manifest.json').read_text())['items']}
        for app in brand.NAMES:
            if app == 'launcher':
                continue
            stem = 'figcraft' if app == 'ui' else app + 'craft'
            path = 'assets/app-icons/' + stem + '.png'
            self.assertIn(path, files)
            self.assertEqual(files[path]['sha256'], originals[app])

    def test_msi_display_changes_keep_registry_keys_and_guid_inputs(self):
        old = '<Package Name="KIO Grid" Manufacturer="KIO" UpgradeCode="C670EFE0-1FE3-512C-84F0-9804B489A606"><RegistryValue Key="Software\\KIO Grid\\Capabilities" Name="ApplicationName" Value="KIO Grid"/><RegistryValue Key="Software\\RegisteredApplications" Name="KIO Grid" Value="Software\\KIO Grid\\Capabilities"/></Package>'
        new = brand.xml_display(old)
        node = ET.fromstring(new)
        self.assertEqual(node.get('Name'), 'Bogo Grid')
        self.assertEqual(node.get('Manufacturer'), 'Bogo')
        self.assertEqual(node.get('UpgradeCode'), 'C670EFE0-1FE3-512C-84F0-9804B489A606')
        self.assertEqual(node[0].get('Key'), 'Software\\KIO Grid\\Capabilities')
        self.assertEqual(node[0].get('Value'), 'Bogo Grid')
        self.assertEqual(node[1].get('Value'), 'Software\\KIO Grid\\Capabilities')

    def test_installer_localization_changes_visible_text_and_preserves_ids_and_entities(self):
        old = '<WixLocalization><String Id="KIO_Welcome" Value="KIO Launcher opens the KIO App Suite: KIO Photo and the KIO apps.&#13;&#10;Next." /></WixLocalization>'
        new = brand.xml_display(old)
        self.assertIn('Id="KIO_Welcome"', new)
        self.assertIn('Bogo Launcher opens the Bogo App Suite: Bogo Photo and the Bogo apps.&#13;&#10;Next.', new)
        self.assertNotIn('Value="KIO ', new)

    def test_chrome_colours_do_not_recolour_document_or_semantic_palette(self):
        old = '            header_bg: Color32::from_rgb(0, 0, 0),\n            text: Color32::WHITE,\n            grid_bg: Color32::WHITE,\n            danger: Color32::from_rgb(200, 0, 0),\n'
        result = brand.theme(old)
        self.assertIn('header_bg: Color32::from_rgb(0xFF, 0xF3, 0xE8)', result)
        self.assertIn('text: Color32::from_rgb(0x34, 0x2B, 0x26)', result)
        self.assertIn('grid_bg: Color32::WHITE', result)
        self.assertIn('danger: Color32::from_rgb(200, 0, 0)', result)

    def test_chrome_text_reads_on_the_requested_orange_and_pale_hover_fills(self):
        tokens = brand.theme('    on_accent: Color32::WHITE,\n    group_label: Color32::from_rgb(160, 160, 160),\n')
        self.assertEqual(tokens.count('Color32::from_rgb(0x34, 0x2B, 0x26)'), 2)
        def luminance(value):
            channels = [int(value[index:index+2], 16) / 255 for index in (0, 2, 4)]
            linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in channels]
            return sum(channel * weight for channel, weight in zip(linear, (.2126, .7152, .0722)))
        for background in ('FC7501', 'FFE7D4', 'FFF3E8', 'FFFAF6'):
            contrast = (luminance(background) + .05) / (luminance('342B26') + .05)
            self.assertGreaterEqual(contrast, 4.5, background)


if __name__ == '__main__':
    unittest.main()
