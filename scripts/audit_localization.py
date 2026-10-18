#!/usr/bin/env python3
"""Audit the real native workspaces; never equate a catalog with complete GUI QA.

Python 3.11+. No network, external translation service, credentials or user data.
Counts use the union of existing catalog keys plus literal translation calls. The
separate direct-UI list is a review queue, not an assertion that every literal is
user-facing (IDs, document text and expressions require contextual review).
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib

LANGUAGES = ('vi', 'en', 'ko', 'ja', 'zh-TW', 'zh-CN')
APPS = ('photo', 'vector', 'film', 'light', 'pdf', 'effect', 'design', 'ui', 'word', 'sound', 'deck', 'cad', 'grid', 'launcher')
ALIASES = {'zh': 'zh-CN', 'zh-cn': 'zh-CN', 'zh-hans': 'zh-CN', 'zh-tw': 'zh-TW', 'zh-hant': 'zh-TW'}
RSTRING = r'"(?:[^"\\]|\\.)*"'
PLACEHOLDER = re.compile(r'(?<!\{)\{([A-Za-z_][\w]*(?::[^{}]*)?)\}(?!\})')
DIRECT_UI = re.compile(r'\.(?:label|button|small_button|heading|menu_button|on_hover_text|hint_text|selectable_label|checkbox)\s*\(\s*(?:[^,\n]+,\s*)?(' + RSTRING + ')')
LOOKUP = re.compile(r'(?:\btl!\s*\(|\b(?:i18n::)?(?:t|tr|tr_noop|trf|trn)\s*\()\s*(' + RSTRING + ')')
OFFICIAL_NAMES = {'launcher': {('', value) for value in ('KIO App Suite', 'Discord', 'GitHub', 'KIO Launcher {version}', 'KIO Launcher', 'ArtCraft', '{name} {version}')}}


def canonical_language(code):
    code = code.lower().replace('_', '-')
    return ALIASES.get(code, code)


def literal(raw):
    # Rust's Unicode escapes use braces rather than JSON's four-digit spelling.
    raw = re.sub(r'\\u\{([0-9a-fA-F_]+)\}', lambda m: chr(int(m[1].replace('_', ''), 16)), raw)
    try:
        return json.loads(raw)
    except ValueError:
        return raw[1:-1].replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')


def unescape_tsv(text):
    return re.sub(r'\\([nt\\])', lambda m: {'n': '\n', 't': '\t', '\\': '\\'}[m[1]], text)


def read_tsv(path):
    rows, errors = {}, []
    for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line or line.startswith('#'):
            continue
        cols = line.split('\t')
        if len(cols) != 3:
            errors.append({'line': n, 'type': 'invalidColumns'})
            continue
        context, source, translation = map(unescape_tsv, cols)
        key = (context, source)
        if key in rows:
            errors.append({'line': n, 'type': 'duplicate', 'key': list(key)})
        rows[key] = translation
    return rows, errors


def collect_catalogs(source):
    root = source / 'crates/ui-egui'
    catalogs, files, errors = {}, [], []
    def put(code, rows, path):
        lang = canonical_language(code)
        catalogs.setdefault(lang, {}).update(rows)
        files.append({'path': str(path.relative_to(source)), 'language': lang, 'keys': len(rows), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    for f in sorted((root / 'src/i18n').glob('*.tsv')):
        rows, bad = read_tsv(f)
        errors.extend({'file': str(f.relative_to(source)), **e} for e in bad)
        put(f.stem, rows, f)
    for f in sorted((root / 'locales').glob('*.json')):
        if f.stem.endswith('-formats'):
            continue  # format patterns are audited separately; they are not interface messages
        data = json.loads(f.read_text())
        put(f.stem, {('', k): v for k, v in data.items() if isinstance(v, str)}, f)
    for f in sorted((root / 'locales').glob('*.toml')):
        data, rows = tomllib.loads(f.read_text()), {}
        for section in ('ui', 'commands', 'menu'):
            for k, value in data.get(section, {}).items():
                rows[('' if section == 'ui' else '@' + section, k)] = value if isinstance(value, str) else value.get('other', '')
        put(f.stem, rows, f)
    main = root / 'src/i18n.rs'
    if main.is_file() and not list((root / 'locales').glob('*')):
        text = main.read_text().split('#[cfg(test)]')[0]
        # Design's five-language column table.
        for m in re.finditer(r'\(\s*(' + RSTRING + r')\s*,\s*\[\s*((?:' + RSTRING + r'\s*,?\s*)+)\]\s*\)', text):
            values = re.findall(RSTRING, m[2])
            if len(values) == 5:
                for lang, raw in zip(('de', 'fr', 'es', 'ja', 'zh-CN'), values):
                    catalogs.setdefault(lang, {})[('', literal(m[1]))] = literal(raw)
        # Grid's Japanese pairs and its per-language match tables.
        if source.parent.name == 'grid':
            for m in re.finditer(r'\(\s*(' + RSTRING + r')\s*,\s*(' + RSTRING + r')\s*\)', text):
                catalogs.setdefault('ja', {})[('', literal(m[1]))] = literal(m[2])
            for f in (root / 'src/i18n').glob('*.rs'):
                code = canonical_language(f.stem)
                rows = {('', literal(m[1])): literal(m[2]) for m in re.finditer('(' + RSTRING + r')\s*=>\s*(' + RSTRING + ')', f.read_text().split('#[cfg(test)]')[0])}
                if rows:
                    put(code, rows, f)
        # Effect uses separate command/source/translation and plain-source tables.
        if source.parent.name == 'effect':
            names = {'JAPANESE': 'ja', 'SIMPLIFIED_CHINESE': 'zh-CN', 'TRADITIONAL_CHINESE': 'zh-TW', 'KOREAN': 'ko', 'VIETNAMESE': 'vi'}
            for f in [main, *sorted((root / 'src/i18n').glob('*.rs'))]:
                body = f.read_text().split('#[cfg(test)]')[0]
                for m in re.finditer(r'(?:const|static)\s+(\w+)[^=]+?=\s*&\[(.*?)\n\];', body, re.S):
                    lang = next((v for k, v in names.items() if m[1].startswith(k)), None)
                    if not lang:
                        continue
                    for row in re.finditer(r'\(\s*(' + RSTRING + r')\s*,\s*(' + RSTRING + r')(?:\s*,\s*(' + RSTRING + r'))?\s*\)', m[2]):
                        if row[3]:
                            key, value = (literal(row[1]), literal(row[2])), literal(row[3])
                        else:
                            key, value = ('', literal(row[1])), literal(row[2])
                        catalogs.setdefault(lang, {})[key] = value
    return catalogs, files, errors


def source_literals(source):
    keys, review = set(), []
    root = source / 'crates/ui-egui/src'
    for f in sorted(root.rglob('*.rs')):
        if 'i18n' in f.parts or f.name.startswith('i18n') or f.name.endswith('_tests.rs'):
            continue
        text = f.read_text().split('#[cfg(test)]')[0]
        for m in LOOKUP.finditer(text):
            keys.add(('', literal(m[1])))
        for m in DIRECT_UI.finditer(text):
            value = literal(m[1])
            if re.search('[A-Za-z]{2}', value):
                review.append({'path': str(f.relative_to(source)), 'line': text.count('\n', 0, m.start()) + 1, 'text': value})
    return keys, review


def placeholders(text):
    return Counter(PLACEHOLDER.findall(text))


def audit_app(app, source):
    if not source.is_dir():
        return {'id': app, 'sourceAvailable': False, 'complete': False}
    catalogs, inputs, parse_errors = collect_catalogs(source)
    literal_keys, direct = source_literals(source)
    keys = set().union(*[set(c) for c in catalogs.values()], literal_keys)
    rows = {}
    for lang in LANGUAGES:
        data = {key: key[1] for key in keys} if lang == 'en' else catalogs.get(lang, {})
        missing = sorted(keys - data.keys())
        empty, mismatch, unchanged = [], [], []
        for key, value in data.items():
            context, english = key
            if not str(value).strip():
                empty.append(list(key))
            if context != '@id' and context not in ('@commands', '@menu'):
                # Invariant-noun languages use a single plural form.
                expected = placeholders(english.split('|')[0] if context == '@plural' else english)
                if any(placeholders(form) != expected for form in (value.split('|') if context == '@plural' else [value])):
                    mismatch.append(list(key))
            if lang != 'en' and value == english and key not in OFFICIAL_NAMES.get(app, set()) and re.search('[A-Za-z]{3}', english):
                unchanged.append(list(key))  # review queue, including legitimate official names
        rows[lang] = {'keys': len(data), 'missing': len(missing), 'empty': len(empty), 'placeholderErrors': len(mismatch), 'sameAsEnglishReview': len(unchanged), 'missingKeys': [list(k) for k in missing], 'emptyKeys': empty, 'placeholderKeys': mismatch, 'unchangedKeys': unchanged}
    complete = not direct and not parse_errors and all(not (r['missing'] or r['empty'] or r['placeholderErrors'] or r['sameAsEnglishReview']) for r in rows.values())
    return {'id': app, 'sourceAvailable': True, 'catalogKeyUnion': len(keys), 'catalogFiles': inputs, 'parseErrors': parse_errors, 'languages': rows, 'directUiReview': direct, 'complete': complete, 'guiTested': False, 'officialNameExceptions': [list(k) for k in sorted(OFFICIAL_NAMES.get(app, set()))]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--app', choices=(*APPS, 'all'), default='all')
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    apps = [audit_app(app, args.root / ('.work/launcher/source' if app == 'launcher' else '.work/full-native/' + app + '/source')) for app in (APPS if args.app == 'all' else (args.app,))]
    report = {'schemaVersion': 1, 'languages': list(LANGUAGES), 'method': 'catalog union plus literal lookups; direct UI calls require contextual review; static coverage does not prove screen or native execution', 'apps': apps}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for app in apps:
        print(app['id'], 'keys', app.get('catalogKeyUnion', 0), 'missing', {k: v['missing'] for k, v in app.get('languages', {}).items()}, 'directUIReview', len(app.get('directUiReview', [])), 'complete', app['complete'])
    return int(args.require_complete and not all(a['complete'] for a in apps))


if __name__ == '__main__':
    sys.exit(main())
