"""Synthetic real native Light/PDF QA, matching immutable upstream CLI contracts.
Exports light(s), pdf(s) for smoke_craft's runner. No builds, UI, models or user documents.
These scenarios are unexecuted until called with an actual already-built native CLI.
"""
import hashlib
import json
from pathlib import Path
import struct
import zlib


def _png_fixture(path, width=120, height=80):
    # Small deterministic RGBA photographic tone ramp; no external media or encoder dependency.
    data = bytearray()
    for y in range(height):
        data.append(0)
        for x in range(width):
            data.extend((20 + x * 130 // width, 25 + y * 110 // height, 35 + (x + y) * 80 // (width + height), 255))
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(bytes(data))) + chunk(b'IEND', b''))


def _light_rows(s, label, args):
    text = s.call(label, args)
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    s.check(label + ' every native command succeeded', bool(rows) and all(x.get('ok') is True for x in rows), rows)
    return {x['command']: x['result'] for x in rows}


def _rgb_mean(image):
    pixels = image['pixels']
    channels = [value for i, value in enumerate(pixels) if i % 4 != 3]
    return sum(channels) / max(len(channels), 1)


def light(s):
    original = s.out / 'tone-ramp.png'
    _png_fixture(original)
    original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
    plain, exposed = s.out / 'plain.png', s.out / 'exposed-small.png'
    s.call('01-render-original', ['render', original, '-o', plain])
    s.call('02-render-exposure-resize', ['render', original, '-o', exposed, '--set', 'light.exposure=1', '--size', '60'])
    a, b = s.png(plain), s.png(exposed)
    s.check('Light full and resized native render dimensions', (a['width'], a['height']) == (120, 80) and (b['width'], b['height']) == (60, 40))
    s.check('Light exposure changes rendered pixel brightness', _rgb_mean(b) > _rgb_mean(a) + 10, {'before': _rgb_mean(a), 'after': _rgb_mean(b)})
    jpeg = s.out / 'export.jpg'
    s.call('03-export-jpeg', ['render', original, '-o', jpeg, '--size', '60', '--quality', '90'])
    s.check('Light actual JPEG export bytes', jpeg.read_bytes().startswith(b'\xff\xd8') and jpeg.read_bytes().endswith(b'\xff\xd9'))
    library, saved, reopened = s.out / 'library', s.out / 'saved-edit.png', s.out / 'reopened-edit.png'
    result = _light_rows(s, '04-create-persistent-library', ['run', '--library', library, '--import', original,
        'develop.set', 'control=light.exposure', 'value=0.75', 'app.export', 'path=' + str(saved), 'width=60'])
    s.check('Light persistent native export completed', result['app.export']['width'] == 60)
    result = _light_rows(s, '05-reopen-persistent-library', ['run', '--library', library, '--import', original,
        'develop.get', 'library.info', 'app.export', 'path=' + str(reopened), 'width=60'])
    s.check('Light native develop setting survives process exit and reopen', result['develop.get']['light']['exposure'] == 0.75, result['develop.get']['light'])
    c, d = s.png(saved), s.png(reopened)
    s.check('Light persisted edit render survives reopen', (c['width'], c['height']) == (d['width'], d['height']) == (60, 40) and abs(_rgb_mean(c) - _rgb_mean(d)) < 2)
    s.check('Light persistent library files saved', library.is_dir() and any(x.is_file() for x in library.rglob('*')))
    copy = s.out / 'original-copy.png'
    s.call('06-export-original-plus-sidecar', ['render', original, '-o', copy, '--set', 'light.exposure=1', '--opt', 'format=original'])
    sidecar = copy.with_suffix('.xmp')
    s.check('Light original export preserves exact image with editable XMP', copy.read_bytes() == original.read_bytes() and sidecar.is_file() and 'exposure' in sidecar.read_text().lower())
    s.check('Light all original input bytes preserved', hashlib.sha256(original.read_bytes()).hexdigest() == original_sha)


def _pdf_fixture(path, pages=2):
    # Standard PDF 1.7, two text and graphic pages, Helvetica built-in font, valid xref.
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>']
    kids = ' '.join(str(4 + 2 * i) + ' 0 R' for i in range(pages))
    objects += [f'<< /Type /Pages /Kids [{kids}] /Count {pages} /MediaBox [0 0 200 300] >>'.encode(), b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for i in range(pages):
        objects.append(f'<< /Type /Page /Parent 2 0 R /Contents {5+2*i} 0 R /Resources << /Font << /F1 3 0 R >> >> >>'.encode())
        content = f'0.1 0.35 0.65 rg 20 30 130 50 re f 0 0 0 rg BT /F1 18 Tf 20 150 Td (KIO QA Page {i+1}) Tj ET'.encode()
        objects.append(b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream')
    data = bytearray(b'%PDF-1.7\n'); offsets = []
    for i, body in enumerate(objects):
        offsets.append(len(data)); data.extend(f'{i+1} 0 obj\n'.encode() + body + b'\nendobj\n')
    xref = len(data); data.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets: data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path.write_bytes(data)


def pdf(s):
    original = s.out / 'synthetic.pdf'
    _pdf_fixture(original)
    original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
    info = s.json('01-inspect-input', ['info', original])
    s.check('PDF native inspector opens two real pages', info['pages'] == 2 and info['first_page_pt'] == [200.0, 300.0], info)
    edited = s.out / 'edited.pdf'
    s.call('02-edit-and-full-save', ['edit', original, '--out', edited, '--rotate', '1:90', '--title', 'KIO Synthetic QA', '--author', 'KIO QA', '--full'])
    info = s.json('03-reopen-edited-document', ['info', edited])
    s.check('PDF metadata and two pages survive full save', info['pages'] == 2 and info['title'] == 'KIO Synthetic QA' and info['author'] == 'KIO QA', info)
    text = s.call('04-extract-edited-text', ['text', edited])
    s.check('PDF text survives edit and native save', 'KIO QA Page 1' in text and 'KIO QA Page 2' in text, text)
    first, second = s.out / 'rotated-page.png', s.out / 'second-page.png'
    s.call('05-render-rotation', ['render', edited, '--page', '1', '--dpi', '72', '--out', first])
    s.call('06-render-page-two', ['render', edited, '--page', '2', '--dpi', '36', '--out', second])
    a, b = s.png(first), s.png(second)
    s.check('PDF saved page rotation renders with swapped bounds', (a['width'], a['height']) == (300, 200), {'width': a['width'], 'height': a['height']})
    s.check('PDF second page renders at actual requested resolution', (b['width'], b['height']) == (100, 150))
    s.check('PDF text and rectangle rendered as nonblank pixels', any(value < 200 for i, value in enumerate(a['pixels']) if i % 4 != 3))
    extracted = s.out / 'extracted.pdf'
    s.call('07-extract-page-two', ['extract', edited, '--pages', '2', '--out', extracted])
    info = s.json('08-reopen-extracted-page', ['info', extracted])
    text = s.call('09-extracted-text', ['text', extracted])
    s.check('PDF page extraction selects the correct saved content', info['pages'] == 1 and 'KIO QA Page 2' in text and 'KIO QA Page 1' not in text)
    combined = s.out / 'combined.pdf'
    s.call('10-combine-documents', ['combine', extracted, edited, '--out', combined])
    info = s.json('11-reopen-combined', ['info', combined])
    text = s.call('12-combined-text', ['text', combined])
    s.check('PDF combine preserves three page order and text', info['pages'] == 3 and text.find('KIO QA Page 2') < text.find('KIO QA Page 1'), text)
    parts = s.out / 'split-pages'
    s.call('13-split-saved-document', ['split', combined, '--every', '1', '--out-dir', parts])
    pieces = [parts / f'combined-p{i}.pdf' for i in (1, 2, 3)]
    s.check('PDF split writes all requested real documents', all(p.is_file() for p in pieces))
    for i, piece in enumerate(pieces):
        info = s.json('14-split-page-' + str(i+1), ['info', piece])
        s.check('PDF split page ' + str(i+1) + ' reopens', info['pages'] == 1)
    # Exercise native document creation and doc_save in one actual engine session too.
    created = s.out / 'created-blank.pdf'; script = s.out / 'create-save.json'
    script.write_text(json.dumps([{'tool': 'doc_create', 'args': {'from': 'blank', 'width': 144, 'height': 96}}, {'tool': 'doc_save', 'args': {'doc': 1, 'path': str(created)}}]), encoding='utf-8')
    s.call('15-native-create-and-save', ['run', '--script', script, '--root', s.out])
    info = s.json('16-reopen-created-document', ['info', created])
    s.check('PDF original native document creation/save/reopen', info['pages'] == 1 and info['first_page_pt'] == [144.0, 96.0], info)
    for p, count in [(edited, 2), (extracted, 1), (combined, 3), (created, 1)]: s.pdf(p, count)
    s.check('PDF all original input bytes preserved', hashlib.sha256(original.read_bytes()).hexdigest() == original_sha)
