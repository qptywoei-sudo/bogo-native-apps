"""Independent synthetic OOXML/PNG/PDF oracles and mocked CLI contracts.

These tests never launch the supplied file or any native application.
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import smoke_word as word
from smoke_craft import png_bytes


NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def docx_bytes(*, bold=True, insertion=True, rows=3, comments=True, header=True, footer=True, body=True, font=True):
    text = word.BODY_TEXT if body else 'Wrong document content'
    formatting = '<w:rPr>' + ('<w:b/>' if bold else '')
    formatting += f'<w:rFonts w:ascii="{word.FONT_NAME}" w:eastAsia="{word.FONT_NAME}"/>' if font else ''
    formatting += '</w:rPr>'
    revision = '<w:ins w:id="1"><w:r><w:t>Tracked revision.</w:t></w:r></w:ins>' if insertion else ''
    table = '<w:tbl>' + '<w:tr><w:tc><w:p/></w:tc></w:tr>' * rows + '</w:tbl>'
    document = f'<w:document xmlns:w="{NS}"><w:body><w:p><w:r>{formatting}<w:t>{text}</w:t></w:r>{revision}</w:p>{table}</w:body></w:document>'
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        archive.writestr('word/document.xml', document)
        for include, name, tag, value in [(comments, 'comments', 'comments', word.COMMENT_TEXT), (header, 'header1', 'hdr', word.HEADER_TEXT), (footer, 'footer1', 'ftr', word.FOOTER_TEXT)]:
            if include:
                archive.writestr('word/' + name + '.xml', f'<w:{tag} xmlns:w="{NS}"><w:p><w:r><w:t>{value}</w:t></w:r></w:p></w:{tag}>')
    return result.getvalue()


def pdf_bytes():
    # A tiny valid cross-reference table, with an actual page dictionary and trailer.
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>', b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>']
    data = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(data)
    data += b'xref\n0 4\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    data += b'trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n'
    return bytes(data)


class FakeWord:
    """A test double which writes independent format fixtures; never an executable."""
    def __init__(self, *, version=word.EXPECTED_VERSION, corrupt=None, fail_format=None, info=None):
        self.version = version
        self.corrupt = corrupt
        self.fail_format = fail_format
        self.info = info
        self.commands = []

    def __call__(self, command, **kwargs):
        args = command[1:]
        self.commands.append(args)
        assert kwargs['encoding'] == 'utf-8'
        assert kwargs['env']['PYTHONUTF8'] == '1'
        assert kwargs['timeout'] == 180
        stdout, stderr, code = '', '', 0
        if args == ['--version']:
            stdout = self.version + '\n'
        elif args[0] == 'run':
            assert '--in' not in args and '--out' not in args
            if '--file' in args:
                assert Path(args[args.index('--file') + 1]).is_file()
            target = Path(args[args.index('--save') + 1])
            features = {}
            if target.name == 'roundtrip.docx' and self.corrupt in ('bold', 'insertion', 'rows', 'comments', 'header', 'footer', 'body', 'font'):
                features[self.corrupt] = 2 if self.corrupt == 'rows' else False
            target.write_bytes(docx_bytes(**features))
        elif args[0] == 'info':
            assert len(args) == 2 and Path(args[1]).is_file()
            stdout = self.info if self.info is not None else json.dumps({'comments': 1, 'paragraphs': 4})
        elif args[0] == 'convert':
            assert len(args) == 3 and Path(args[1]).is_file()
            target = Path(args[2])
            fmt = target.suffix[1:]
            if self.fail_format == fmt:
                return SimpleNamespace(stdout='', stderr='synthetic conversion failure', returncode=7)
            if fmt == 'pdf':
                data = pdf_bytes() if self.corrupt != 'pdf' else b'%PDF-1.4\n' + b'not a document' * 10
            elif fmt == 'png':
                data = png_bytes(64, 80)
                if self.corrupt == 'png':
                    data = data[:-4] + b'bad!'
            elif fmt == 'odt':
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w') as archive:
                    archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
                    archive.writestr('content.xml', '<document>' + word.BODY_TEXT + '</document>')
                data = stream.getvalue()
            else:
                data = ((r'{\rtf1 ' if fmt == 'rtf' else '<html>' if fmt == 'html' else '# ') + word.BODY_TEXT + '\nSynthetic saved document. Tracked revision. ' * 4).encode()
            target.write_bytes(data)
            if self.corrupt == 'input':
                Path(args[1]).write_bytes(b'overwritten by a faulty exporter')
        elif args[0] == 'text':
            assert len(args) == 2 and Path(args[1]).is_file()
            stdout = 'Missing original text' if self.corrupt == 'reimport' else word.BODY_TEXT + '\n'
        else:
            raise AssertionError('Unexpected mock CLI invocation: ' + repr(args))
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=code)


class WordFormatSmoke(unittest.TestCase):
    def run_fixture(self, tmp, fake=None, *, plan=False):
        cli = Path(tmp) / 'CLI With Spaces' / 'wordcraft-cli.exe'
        cli.parent.mkdir(exist_ok=True)
        cli.write_bytes(b'unit fixture, not a native executable')
        output = Path(tmp) / 'Output With Spaces'
        with patch.object(word.subprocess, 'run', side_effect=fake or FakeWord()) as process:
            code, report = word.execute(cli, output, plan=plan)
        return cli, output, process, code, report

    def test_full_save_reopen_export_contract_and_report_are_portable(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeWord()
            cli, output, process, code, report = self.run_fixture(tmp, fake)
            self.assertEqual(code, 0)
            self.assertEqual((report['app'], report['status']), ('word', 'passed'))
            self.assertGreaterEqual(len(report['checks']), 18)
            self.assertTrue(all(check['passed'] for check in report['checks']))
            self.assertEqual(report['cliSha256'], hashlib.sha256(cli.read_bytes()).hexdigest())
            self.assertTrue(all(step['exitCode'] == 0 for step in report['steps']))
            self.assertEqual(len(report['steps']), process.call_count)
            self.assertEqual(json.loads((output / 'report.json').read_text()), report)
            self.assertTrue({'synthetic.docx', 'roundtrip.docx', *('export.' + f for f in word.FORMATS)} <= {entry['name'] for entry in report['files']})
            for entry in report['files']:
                self.assertEqual(entry['sha256'], hashlib.sha256((output / entry['name']).read_bytes()).hexdigest())
            create = next(args for args in fake.commands if args[0] == 'run' and '--file' not in args)
            specs = [create[n + 1].split('=', 1) for n, value in enumerate(create) if value == '--cmd']
            self.assertIn(['insert.table', '{"rows":3,"cols":3}'], specs)
            self.assertIn(['review.trackChanges', '{"value":true}'], specs)
            self.assertIn(['format.bold', '{"value":true}'], specs)
            font = next(json.loads(params) for name, params in specs if name == 'format.font')
            self.assertEqual(font, {'name': 'Noto Sans CJK SC', 'eastAsia': 'Noto Sans CJK SC'})
            inserted = [json.loads(params)['text'] for name, params in specs if name == 'text.insert']
            self.assertIn(word.BODY_TEXT, inserted)
            for expected in ('한글', 'Xin chào Việt Nam', '日本語', '中文測試'):
                self.assertIn(expected, word.BODY_TEXT)
            self.assertIn('--author', create)
            self.assertEqual(next(args for args in fake.commands if args[0] == 'info')[0:1], ['info'])
            self.assertEqual([Path(args[2]).suffix for args in fake.commands if args[0] == 'convert'], ['.pdf', '.odt', '.rtf', '.html', '.md', '.png'])
            self.assertEqual([Path(args[1]).suffix for args in fake.commands if args[0] == 'text'], ['.docx', '.docx', '.odt', '.rtf', '.html'])

    def test_wrong_cli_identity_or_version_stops_before_document_commands(self):
        for version in ['wordcraft 0.7.0', 'wordcraft-cli 0.7.1', 'wordcraft-cli 0.7.0-kio.2', 'wordcraft-cli 0.7.0\nextra output']:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                _, output, process, code, report = self.run_fixture(tmp, FakeWord(version=version))
                self.assertEqual(code, 1)
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(process.call_count, 1)
                self.assertFalse((output / 'synthetic.docx').exists())
                self.assertTrue(any(not check['passed'] for check in report['checks']))

    def test_bad_docx_serialization_cannot_pass_despite_zero_cli_exit_codes(self):
        for kind in ['bold', 'insertion', 'rows', 'comments', 'header', 'footer', 'body', 'font']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                _, output, _, code, report = self.run_fixture(tmp, FakeWord(corrupt=kind))
                self.assertEqual(code, 1)
                self.assertEqual(report['status'], 'failed')
                self.assertFalse((output / 'export.pdf').exists())
                self.assertTrue(any(not check['passed'] for check in report['checks']))

    def test_invalid_pdf_png_reimport_and_input_modification_are_real_failures(self):
        for kind in ['pdf', 'png', 'reimport', 'input']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                _, output, _, code, report = self.run_fixture(tmp, FakeWord(corrupt=kind))
                self.assertEqual(code, 1)
                self.assertEqual(json.loads((output / 'report.json').read_text())['status'], 'failed')
                self.assertTrue(report['error'])

    def test_cli_nonzero_writes_failed_report_and_original_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, output, _, code, report = self.run_fixture(tmp, FakeWord(fail_format='pdf'))
            self.assertEqual(code, 1)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['steps'][-1]['exitCode'], 7)
            self.assertIn('synthetic conversion failure', report['error'])
            self.assertIn('synthetic conversion failure', (output / '04-export-pdf.stderr.txt').read_text())

    def test_malformed_info_json_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, _, code, report = self.run_fixture(tmp, FakeWord(info='not JSON'))
            self.assertEqual(code, 1)
            self.assertEqual(report['status'], 'failed')

    def test_timeout_and_launch_failure_are_recorded_without_false_exit_zero(self):
        failures = [subprocess.TimeoutExpired('unit fixture', 180, output=b'partial\n', stderr=b'timed out'), OSError('cannot launch unit fixture')]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as tmp:
                cli = Path(tmp) / 'wordcraft-cli'
                cli.write_bytes(b'not executable')
                output = Path(tmp) / 'out'
                with patch.object(word.subprocess, 'run', side_effect=failure):
                    code, report = word.execute(cli, output)
                self.assertEqual(code, 1)
                self.assertEqual(report['steps'][0]['exitCode'], None)
                self.assertEqual(report['status'], 'failed')
                self.assertTrue((output / '00-version.stderr.txt').exists())

    def test_plan_is_not_run_and_never_executes_any_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / 'does-not-exist'
            output = Path(tmp) / 'plan'
            with patch.object(word.subprocess, 'run') as process:
                code, report = word.execute(cli, output, plan=True)
            self.assertEqual(code, 0)
            self.assertEqual(report['status'], 'not_run')
            self.assertEqual(report['steps'], [])
            self.assertEqual(report['checks'], [])
            self.assertIsNone(report['cliSha256'])
            self.assertFalse(report['plan']['actualNativeExecution'])
            process.assert_not_called()

    def test_missing_cli_fails_with_a_report_without_running_a_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'out'
            with patch.object(word.subprocess, 'run') as process:
                code, report = word.execute(Path(tmp) / 'missing', output)
            self.assertEqual(code, 1)
            self.assertEqual(report['status'], 'failed')
            self.assertTrue((output / 'report.json').is_file())
            process.assert_not_called()

    def test_existing_user_output_and_symlink_output_are_refused_without_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'existing'
            output.mkdir()
            keep = output / 'user.docx'
            keep.write_bytes(b'untouched')
            with self.assertRaises(ValueError):
                word.execute(Path(tmp) / 'fake-cli', output)
            self.assertEqual(keep.read_bytes(), b'untouched')
            self.assertFalse((output / 'report.json').exists())
            linked = Path(tmp) / 'link'
            try:
                linked.symlink_to(output, target_is_directory=True)
            except OSError:
                return  # Symlink creation can need Windows privileges; main nonempty guard ran.
            with self.assertRaises(ValueError):
                word.prepare_output(linked)
        with self.assertRaises(ValueError):
            word.prepare_output(Path('relative-output'))

    def test_main_returns_nonzero_for_failed_scenario_and_not_run_for_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / 'wordcraft-cli'
            cli.write_bytes(b'unit fixture')
            with contextlib.redirect_stdout(io.StringIO()) as stdout, patch.object(word.subprocess, 'run', side_effect=FakeWord(version='wrong')):
                code = word.main(['--cli', str(cli), '--output', str(Path(tmp) / 'failure')])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stdout.getvalue())['status'], 'failed')
            with contextlib.redirect_stdout(io.StringIO()) as stdout, patch.object(word.subprocess, 'run') as process:
                code = word.main(['--cli', str(cli), '--output', str(Path(tmp) / 'plan'), '--plan'])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())['status'], 'not_run')
            process.assert_not_called()

    def test_malformed_or_incomplete_docx_packages_are_rejected_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.docx'
            path.write_bytes(b'not a zip')
            with self.assertRaises(zipfile.BadZipFile):
                word.docx_features(path)
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('word/document.xml', '<document/>')
            with self.assertRaisesRegex(AssertionError, 'required DOCX'):
                word.docx_features(path)
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('[Content_Types].xml', '<Types/>')
                archive.writestr('_rels/.rels', '<Relationships/>')
                archive.writestr('word/document.xml', '<not-closed')
            with self.assertRaises(Exception):
                word.docx_features(path)


if __name__ == '__main__':
    unittest.main()
