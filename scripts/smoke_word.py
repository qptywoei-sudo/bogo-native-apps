#!/usr/bin/env python3
"""Synthetic save/reopen/export QA for the complete pinned KIO Word CLI.

Supply an existing absolute CLI path and a fresh or empty output directory.
Only synthetic documents are created; no GUI, build, install, network, MCP or
remote-control command is used. --plan is explicitly not a passing native run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile
import xml.etree.ElementTree as ET

from smoke_craft import decode_png, inspect_pdf

EXPECTED_VERSION = 'wordcraft-cli 0.7.0'
BODY_TEXT = 'KIO Word full native QA | 한글 저장과 다시 열기 | Xin chào Việt Nam — tiếng Việt có dấu | 日本語の文章と中文測試'
FONT_NAME = 'Noto Sans CJK SC'
COMMENT_TEXT = 'KIO QA comment'
HEADER_TEXT = 'KIO QA header'
FOOTER_TEXT = 'KIO QA footer'
FORMATS = ('pdf', 'odt', 'rtf', 'html', 'md', 'png')
NAMESPACES = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
COMMANDS = (
    ('file.new', {}),
    ('format.font', {'name': FONT_NAME, 'eastAsia': FONT_NAME}),
    ('format.bold', {'value': True}),
    ('text.insert', {'text': BODY_TEXT}),
    ('format.bold', {'value': False}),
    ('text.insert', {'text': '\nSynthetic saved document.'}),
    ('review.trackChanges', {'value': True}),
    ('text.insert', {'text': ' Tracked revision.'}),
    ('review.newComment', {'text': COMMENT_TEXT}),
    ('review.trackChanges', {'value': False}),
    ('insert.header', {'text': HEADER_TEXT}),
    ('insert.footer', {'text': FOOTER_TEXT}),
    ('insert.closeHeader', {}),
    ('caret.docEnd', {}),
    ('insert.table', {'rows': 3, 'cols': 3}),
)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def run_arguments(commands, *, source=None, save=None, author=None):
    """Word uses --file/--save and id=JSON, unlike Grid's --in/--out."""
    args = ['run']
    if source is not None:
        args += ['--file', str(source)]
    if author is not None:
        args += ['--author', author]
    for name, params in commands:
        args += ['--cmd', name + '=' + json.dumps(params, ensure_ascii=False, separators=(',', ':'))]
    if save is not None:
        args += ['--save', str(save)]
    return args


def docx_features(path):
    """Read real OOXML parts, including formatting/revisions and auxiliary content."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 4096 or sum(e.file_size for e in entries) > 64 * 1024 * 1024:
            raise AssertionError('Excessive synthetic DOCX package')
        if archive.testzip() is not None:
            raise AssertionError('DOCX ZIP CRC failure')
        if len({e.filename for e in entries}) != len(entries):
            raise AssertionError('Duplicate DOCX package parts')
        names = set(archive.namelist())
        required = {'[Content_Types].xml', '_rels/.rels', 'word/document.xml'}
        if not required <= names:
            raise AssertionError('Missing required DOCX package parts')
        root = ET.fromstring(archive.read('word/document.xml'))
        auxiliary = {}
        for prefix in ('word/comments', 'word/header', 'word/footer'):
            parts = sorted(n for n in names if n.startswith(prefix) and n.endswith('.xml'))
            auxiliary[prefix] = ''.join(''.join(ET.fromstring(archive.read(n)).itertext()) for n in parts)
    return {
        'zipCrc': True,
        'bodyText': ''.join(root.itertext()),
        'bold': root.find('.//w:b', NAMESPACES) is not None,
        'trackedInsertion': root.find('.//w:ins', NAMESPACES) is not None,
        'cjkFont': any(font.get('{' + NAMESPACES['w'] + '}ascii') == FONT_NAME and
                       font.get('{' + NAMESPACES['w'] + '}eastAsia') == FONT_NAME
                       for font in root.findall('.//w:rFonts', NAMESPACES)),
        'tableRows': len(root.findall('.//w:tbl/w:tr', NAMESPACES)),
        'auxiliary': auxiliary,
    }


class WordSmoke:
    def __init__(self, cli, output):
        self.cli = cli
        self.out = output
        self.steps = []
        self.checks = []
        self.env = os.environ.copy()
        self.env['PYTHONUTF8'] = '1'
        self.env['WORDCRAFT_CONFIG_DIR'] = str(output / '.profile')

    def check(self, name, condition, detail=None):
        self.checks.append({'name': name, 'passed': bool(condition), 'detail': detail})
        if not condition:
            raise AssertionError(name + ': ' + str(detail))

    def call(self, label, args):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', label):
            raise ValueError('Unsafe step label')
        args = list(map(str, args))
        started = time.monotonic()
        try:
            process = subprocess.run([str(self.cli), *args], capture_output=True, text=True,
                                     encoding='utf-8', errors='replace', env=self.env,
                                     cwd=self.out, timeout=180)
        except (subprocess.TimeoutExpired, OSError) as error:
            stdout = getattr(error, 'stdout', None) or ''
            stderr = getattr(error, 'stderr', None) or str(error)
            if isinstance(stdout, bytes):
                stdout = stdout.decode('utf-8', 'replace')
            if isinstance(stderr, bytes):
                stderr = stderr.decode('utf-8', 'replace')
            self.record(label, args, stdout, stderr, None, started)
            raise AssertionError(label + ' could not complete: ' + str(error)) from error
        self.record(label, args, process.stdout, process.stderr, process.returncode, started)
        if process.returncode:
            raise AssertionError(label + ' failed with exit ' + str(process.returncode) + ': ' + process.stderr[-2000:])
        return process.stdout

    def record(self, label, args, stdout, stderr, code, started):
        for kind, value in [('stdout', stdout), ('stderr', stderr)]:
            (self.out / (label + '.' + kind + '.txt')).write_text(value, encoding='utf-8')
        self.steps.append({'label': label, 'args': args, 'exitCode': code,
                           'elapsedSeconds': round(time.monotonic() - started, 3),
                           'stdout': label + '.stdout.txt', 'stderr': label + '.stderr.txt'})


def word(smoke):
    original = smoke.out / 'synthetic.docx'
    roundtrip = smoke.out / 'roundtrip.docx'
    version = smoke.call('00-version', ['--version']).strip()
    smoke.check('exact pinned Word CLI version', version == EXPECTED_VERSION, version)
    smoke.call('01-create', run_arguments(COMMANDS, author='KIO synthetic QA', save=original))
    info = json.loads(smoke.call('02-info', ['info', original]))
    smoke.check('DOCX reopened with comment and table paragraphs', info.get('comments') == 1 and info.get('paragraphs', 0) >= 1, info)
    smoke.call('03-reopen-save', run_arguments([('caret.docEnd', {})], source=original, save=roundtrip))
    for path in (original, roundtrip):
        features = docx_features(path)
        smoke.check(path.name + ' ZIP CRC and OOXML package', features['zipCrc'])
        smoke.check(path.name + ' body/bold/table/tracked insertion',
                    BODY_TEXT in features['bodyText'] and features['bold'] and
                    features['tableRows'] == 3 and features['trackedInsertion'],
                    {key: value for key, value in features.items() if key != 'auxiliary'})
        smoke.check(path.name + ' comments/header/footer content',
                    all(text in features['auxiliary'][part] for part, text in
                        [('word/comments', COMMENT_TEXT), ('word/header', HEADER_TEXT), ('word/footer', FOOTER_TEXT)]))
        smoke.check(path.name + ' explicit Latin and East Asian font', features['cjkFont'])
        text = smoke.call('03-text-' + path.stem, ['text', path])
        smoke.check(path.name + ' exact Korean/Vietnamese/Japanese/Chinese text reimport', BODY_TEXT in text)
    saved_hash = digest(roundtrip)
    for fmt in FORMATS:
        target = smoke.out / ('export.' + fmt)
        smoke.call('04-export-' + fmt, ['convert', roundtrip, target])
        data = target.read_bytes()
        smoke.check(fmt + ' nonempty export', len(data) > 80, {'bytes': len(data)})
        if fmt == 'pdf':
            parsed = inspect_pdf(data)
            smoke.check('PDF actual structure and pages', parsed['pageObjects'] >= 1, parsed)
        if fmt == 'png':
            image = decode_png(data)
            smoke.check('PNG actual dimensions/CRC/decoded pixels', image['width'] > 50 and image['height'] > 50,
                        {'width': image['width'], 'height': image['height']})
        if fmt in ('odt', 'rtf', 'html'):
            text = smoke.call('05-import-' + fmt, ['text', target])
            smoke.check(fmt + ' text reimport', BODY_TEXT in text)
    smoke.check('export leaves saved DOCX unchanged', digest(roundtrip) == saved_hash)


def prepare_output(output):
    if not output.is_absolute():
        raise ValueError('--output must be an absolute path')
    if output.is_symlink():
        raise ValueError('--output may not be a symlink')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('--output must be a fresh or empty directory')
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    return output


def execute(cli, output, *, plan=False):
    """Return (exit code, report); callers must supply an empty prepared output directory."""
    output = prepare_output(output)
    smoke = WordSmoke(cli, output)
    error = None
    cli_hash = None
    status = 'not_run' if plan else 'failed'
    try:
        if not cli.is_absolute():
            raise ValueError('--cli must be an absolute path')
        if plan:
            if cli.is_file():
                cli_hash = digest(cli)
        else:
            cli = cli.resolve(strict=True)
            if not cli.is_file():
                raise ValueError('--cli must be an existing file')
            smoke.cli = cli
            cli_hash = digest(cli)
            word(smoke)
            smoke.check('CLI bytes unchanged during QA', digest(cli) == cli_hash)
            status = 'passed'
    except Exception as failure:
        error = str(failure)
        smoke.checks.append({'name': 'scenario completed', 'passed': False, 'detail': error})
        status = 'failed'
    files = [{'name': path.name, 'bytes': path.stat().st_size, 'sha256': digest(path)}
             for path in sorted(output.iterdir()) if path.is_file() and not path.is_symlink() and path.name != 'report.json']
    report = {'schema': 'kio.native-word-smoke.v1', 'app': 'word', 'status': status,
              'cli': str(cli), 'cliSha256': cli_hash, 'expectedCliVersion': EXPECTED_VERSION,
              'scope': 'Synthetic complete native CLI document save/reopen/export; GUI and commercial compatibility are not certified.',
              'checks': smoke.checks, 'steps': smoke.steps, 'files': files, 'error': error}
    if plan:
        report['plan'] = {'commands': [{'id': name, 'params': params} for name, params in COMMANDS],
                          'exports': list(FORMATS), 'actualNativeExecution': False}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return (1 if status == 'failed' else 0), report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args(argv)
    try:
        output = prepare_output(args.output.expanduser())
    except (ValueError, OSError) as error:
        parser.error(str(error))
    code, report = execute(args.cli.expanduser(), output, plan=args.plan)
    print(json.dumps({'app': 'word', 'status': report['status'], 'checks': len(report['checks']),
                      'report': str(output / 'report.json'), 'error': report['error']}, ensure_ascii=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
