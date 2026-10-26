"""Require real PDF home-surface UI regressions in addition to original gates."""
import hashlib
import json
import re
import subprocess
import sys

import full_native as full

KEY = 'bogoPdfHomeSurfaces'
FILTER = 'bogo_home_surface_role_'
TESTS = (
    FILTER + 'covers_real_default_read_and_floating_routes',
    FILTER + 'preserves_document_and_combine_pasteboards',
)
SOURCES = ('crates/ui-egui/src/home.rs', 'crates/ui-egui/tests/ui.rs')


def command(lock, platform):
    full.require(platform in full.common.TARGETS, 'Native PDF UI target is required')
    return ['rustup', 'run', lock['rust'], 'cargo', 'test', '--release', '--locked',
            '--target', full.common.TARGETS[platform], '-p', 'pdfcraft-ui-egui',
            '--test', 'ui', FILTER, '--', '--nocapture']


def source_contract(source):
    result = {}
    for relative in SOURCES:
        path = source / relative
        full.require(path.is_file() and not path.is_symlink(), 'PDF UI regression source is missing')
        result[relative] = full.digest(path)
    tests = (source / SOURCES[1]).read_text(encoding='utf-8')
    for name in TESTS:
        full.require(len(re.findall(r'\bfn\s+' + re.escape(name) + r'\s*\(', tests)) == 1,
                     'Expected original-Harness PDF regression is missing or duplicated')
    return result


def validate_output(output):
    full.require(isinstance(output, str) and len(output.encode('utf-8')) <= 1024 * 1024,
                 'PDF UI test output is absent or too large')
    found = re.findall(r'^test (\S+) \.\.\. (\w+)\s*$', output, re.M)
    full.require(sorted(found) == sorted((name, 'ok') for name in TESTS),
                 'Both actual PDF UI regressions must execute and pass')
    summaries = re.findall(r'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;.*$', output, re.M)
    full.require(summaries == [('2', '0', '0')], 'Expected exactly two PDF UI passes without skips')


def base_record(work, inputs, platform):
    path = work / ('build-' + platform + '.json')
    record = json.loads(path.read_text(encoding='utf-8'))
    full.require(record.get('app') == 'pdf' and record.get('platform') == platform
                 and record.get('inputs') == inputs
                 and record.get('checks', {}).get('originalCoreTests') == 'passed',
                 'Original native PDF build and core-test evidence is required')
    return path, record


def complete(lock, platform):
    if lock['id'] != 'pdf':
        return
    work, source, fonts, inputs = full.prepared(lock)
    sources = source_contract(source)
    path, record = base_record(work, inputs, platform)
    # A failed retry cannot reuse an earlier positive extra-test marker.
    record['checks'].pop(KEY, None)
    full.write_json(path, record)
    target = full.common.TARGETS[platform]
    env = full.build_env(lock, fonts, work / ('target-' + platform), target)
    env['CARGO_TERM_COLOR'] = 'never'
    args = command(lock, platform)
    try:
        output = full.run(args, cwd=source, env=env, capture=True)
    except subprocess.CalledProcessError as error:
        # Keep actual Rust failures visible in hosted/local logs while refusing
        # the package and retaining the original exit status and source gates.
        for label, raw in (('stdout', error.stdout), ('stderr', error.stderr)):
            if isinstance(raw, str):
                raw = raw.encode('utf-8', errors='replace')
            if isinstance(raw, bytes) and raw:
                print('PDF UI regression ' + label + ' (last 65536 bytes):\n'
                      + raw[-65536:].decode('utf-8', errors='replace'), file=sys.stderr)
        raise
    validate_output(output)
    _, _, _, after = full.prepared(lock)
    full.require(after == inputs and source_contract(source) == sources,
                 'PDF source changed during its UI regressions')
    record['checks'][KEY] = {
        'schema': 1, 'status': 'passed', 'platform': platform, 'command': args,
        'testNames': list(TESTS), 'testsPassed': 2, 'testsFailed': 0, 'testsIgnored': 0,
        'sourceTreeSha256': inputs['sourceTreeSha256'], 'sourceSha256': sources,
        'output': output, 'outputSha256': hashlib.sha256(output.encode('utf-8')).hexdigest(),
    }
    full.write_json(path, record)


def require_complete(lock, platform):
    if lock['id'] != 'pdf':
        return
    work, source, _, inputs = full.prepared(lock)
    _, record = base_record(work, inputs, platform)
    proof = record['checks'].get(KEY)
    full.require(isinstance(proof, dict) and proof.get('schema') == 1
                 and proof.get('status') == 'passed' and proof.get('platform') == platform
                 and proof.get('command') == command(lock, platform)
                 and proof.get('testNames') == list(TESTS)
                 and (proof.get('testsPassed'), proof.get('testsFailed'), proof.get('testsIgnored')) == (2, 0, 0)
                 and proof.get('sourceTreeSha256') == inputs['sourceTreeSha256']
                 and proof.get('sourceSha256') == source_contract(source),
                 'Current real PDF home-surface regressions are required before packaging')
    validate_output(proof.get('output'))
    full.require(proof.get('outputSha256') == hashlib.sha256(proof['output'].encode('utf-8')).hexdigest(),
                 'PDF UI regression output changed')
