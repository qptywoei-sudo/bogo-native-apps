#!/usr/bin/env python3
"""Convert owner-supplied Bogo PNGs without recolouring or redrawing the originals."""
import hashlib
import io
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets/bogo-program-icons'
SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_SIZES = {'icp4': 16, 'icp5': 32, 'icp6': 64, 'ic07': 128, 'ic08': 256, 'ic09': 512, 'ic10': 1024}


def originals():
    from PIL import Image
    manifest = json.loads((ASSETS / 'manifest.json').read_text(encoding='utf-8'))
    rows = manifest['items']
    expected = ('cad', 'design', 'vector', 'film', 'light', 'pdf', 'effect', 'ui', 'word', 'sound', 'deck', 'grid', 'launcher', 'photo')
    if len(rows) != 14 or tuple(r['id'] for r in rows) != expected:
        raise ValueError('Bogo icon ID/order mismatch')
    hashes = set()
    for index, row in enumerate(rows, 1):
        if row['filename'] != f'{index:02}-bogo-{row["id"]}.png':
            raise ValueError('Bogo original filename mismatch')
        path = ASSETS / row['filename']
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        image = Image.open(io.BytesIO(raw))
        if digest != row['sha256'] or digest in hashes or image.size != (1024, 1024) or image.mode != 'RGBA' or image.getextrema()[3][0] != 0:
            raise ValueError('Bogo original hash/RGBA/transparency mismatch: ' + row['id'])
        hashes.add(digest)
        yield row, path, image


def generate():
    from PIL import Image
    rows = []
    for row, source, image in originals():
        icon = ASSETS / (row['id'] + '.ico')
        image.save(icon, format='ICO', sizes=[(n, n) for n in SIZES])
        chunks = []
        for kind, size in ICNS_SIZES.items():
            stream = io.BytesIO()
            image.resize((size, size), Image.Resampling.LANCZOS).save(stream, format='PNG')
            data = source.read_bytes() if size == 1024 else stream.getvalue()
            chunks.append(kind.encode('ascii') + struct.pack('>I', len(data) + 8) + data)
        data = b''.join(chunks)
        icns = ASSETS / (row['id'] + '.icns')
        icns.write_bytes(b'icns' + struct.pack('>I', len(data) + 8) + data)
        rows.append({'id': row['id'], 'original': row['filename'], 'originalSha256': row['sha256'], 'ico': {'path': icon.name, 'sha256': hashlib.sha256(icon.read_bytes()).hexdigest(), 'sizes': SIZES}, 'icns': {'path': icns.name, 'sha256': hashlib.sha256(icns.read_bytes()).hexdigest(), 'sizes': list(ICNS_SIZES.values())}})
    (ASSETS / 'native-icons.json').write_text(json.dumps({'schema': 1, 'brand': 'Bogo', 'items': rows}, indent=2) + '\n')


if __name__ == '__main__':
    generate()
