#!/usr/bin/env python3
"""Offline lexical audit of display-name corruption in pinned native Rust source.

This is a source guard, not a Rust compiler or a claim of native execution.
The archive mode authenticates the complete original source archive and exact
reviewed patches, then applies only Rust files in an isolated temporary tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DISPLAY_NAMES = ('Photo', 'Vector', 'Film', 'Light', 'PDF', 'Effect', 'Design',
                 'UI', 'Word', 'Sound', 'Deck', 'CAD', 'Grid', 'Launcher', 'Studio')
DISPLAY_CODE = re.compile(r'\bKIO\s+(?:' + '|'.join(DISPLAY_NAMES) + r')\b')
RAW_STRING = re.compile(r'(?:br|cr|r)(#{0,255})"')
CHARACTER = re.compile(r"'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|[^\r\n])|[^'\\\r\n])'")


def sha256(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(part)
    return result.hexdigest()


def executable_code(text):
    """Mask literals and nested comments, retaining offsets and line numbers.

    Rust lifetimes are not character literals. Raw/byte/C strings, escaped
    strings, Unicode characters and nested block comments are handled explicitly.
    """
    result = list(text)
    i, size = 0, len(text)

    def mask(start, end):
        for offset in range(start, end):
            if text[offset] not in '\r\n':
                result[offset] = ' '

    while i < size:
        start = i
        if text.startswith('//', i):
            end = text.find('\n', i + 2)
            i = size if end < 0 else end
        elif text.startswith('/*', i):
            depth, i = 1, i + 2
            while i < size and depth:
                if text.startswith('/*', i):
                    depth, i = depth + 1, i + 2
                elif text.startswith('*/', i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            if depth:
                raise ValueError('Unterminated Rust block comment')
        elif (raw := RAW_STRING.match(text, i)) and (i == 0 or not (text[i-1].isalnum() or text[i-1] == '_')):
            ending = '"' + raw[1]
            end = text.find(ending, raw.end())
            if end < 0:
                raise ValueError('Unterminated Rust raw string')
            i = end + len(ending)
        elif text[i] == '"':
            i += 1
            while i < size and text[i] != '"':
                i += 2 if text[i] == '\\' else 1
            if i >= size:
                raise ValueError('Unterminated Rust string')
            i += 1
        elif text[i] == "'" and (character := CHARACTER.match(text, i)):
            i = character.end()
        else:
            i += 1
            continue
        mask(start, i)
    return ''.join(result)


def audit_text(text, path='<source>'):
    code = executable_code(text)
    findings = []
    for match in DISPLAY_CODE.finditer(code):
        findings.append({'path': str(path), 'line': text.count('\n', 0, match.start()) + 1,
                         'expression': text[match.start():match.end()]})
    return findings


def audit_source(source):
    paths = sorted(source.rglob('*.rs'))
    findings = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Rust source link/special file refused: ' + str(path))
        findings += audit_text(path.read_text(encoding='utf-8'), path.relative_to(source).as_posix())
    return {'rustFiles': len(paths), 'findings': findings,
            'scope': 'Known spaced KIO display names outside Rust comments and literals; not semantic compilation'}


def audit_lock(lock, *, archive_cache=None):
    cache = archive_cache or ROOT / '.cache/archives'
    archive = cache / (lock['source']['root'] + '.tar.gz')
    if not archive.is_file() or archive.is_symlink() or archive.stat().st_size != lock['source']['bytes'] or sha256(archive) != lock['source']['sha256']:
        raise ValueError('Pinned source archive missing or changed: ' + lock['id'])
    pins = [lock['branding'], *lock.get('functionalFixes', [])]
    for pin in pins:
        patch = ROOT / pin['patch']
        if not patch.is_file() or patch.is_symlink() or sha256(patch) != pin['sha256']:
            raise ValueError('Pinned patch missing or changed: ' + str(patch))
    with tempfile.TemporaryDirectory(prefix='kio-rust-branding-') as temporary:
        source = Path(temporary)
        prefix = lock['source']['root'] + '/'
        with tarfile.open(archive) as original:
            for member in original:
                if not member.isfile() or not member.name.endswith('.rs'):
                    continue
                if not member.name.startswith(prefix):
                    raise ValueError('Rust member outside pinned root')
                relative = member.name[len(prefix):]
                pure = PurePosixPath(relative)
                if pure.is_absolute() or '..' in pure.parts or '\\' in relative or not pure.parts:
                    raise ValueError('Unsafe Rust source member')
                destination = source.joinpath(*pure.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(original.extractfile(member).read())
        for pin in pins:
            subprocess.run(['git', 'apply', '--check', '--binary', '--include=*.rs', str(ROOT / pin['patch'])], cwd=source, check=True, capture_output=True)
            subprocess.run(['git', 'apply', '--binary', '--include=*.rs', str(ROOT / pin['patch'])], cwd=source, check=True, capture_output=True)
        result = audit_source(source)
    result.update(app=lock['id'], sourceCommit=lock['source']['commit'],
                  sourceArchiveSha256=lock['source']['sha256'],
                  patches=[{'path': p['patch'], 'sha256': p['sha256']} for p in pins],
                  passed=result['rustFiles'] > 0 and not result['findings'], nativeBuildRun=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', default='all')
    parser.add_argument('--archive-cache', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    locks = json.loads((ROOT / 'manifests/full-native-apps.json').read_text())['applications']
    locks += [json.loads((ROOT / 'manifests/launcher.lock.json').read_text())]
    if args.app != 'all':
        locks = [lock for lock in locks if lock['id'] == args.app]
        if not locks:
            parser.error('Unknown app')
    results = [audit_lock(lock, archive_cache=args.archive_cache) for lock in locks]
    report = {'schema': 'kio.rust-branding-audit.v1', 'passed': all(r['passed'] for r in results),
              'applications': results, 'nativeBuildRun': False}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'applications': len(results),
                      'rustFiles': sum(r['rustFiles'] for r in results),
                      'findings': [f for r in results for f in r['findings']]}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
