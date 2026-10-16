"""Read only the pinned Design Windows dependency license layout before compilation."""
import hashlib
import json
import os
from pathlib import Path
import full_native as full

lock = full.load_lock('design')
work, source, fonts, _ = full.prepared(lock)
target = 'x86_64-pc-windows-msvc'
full.assert_host('windows-x64')
env = full.build_env(lock, fonts, work / 'target-windows-x64', target)
metadata = json.loads(full.common.run(['rustup', 'run', lock['rust'], 'cargo', 'metadata', '--locked',
    '--format-version', '1', '--filter-platform', target], cwd=source, env=env, capture=True, timeout=600))
rows = [p for p in metadata['packages'] if p['name'] == 'winit' and p['version'] == '0.30.13']
full.require(len(rows) == 1, 'Expected the pinned winit dependency')
package = rows[0]
root = Path(package['manifest_path']).parent
result = {'package': {k: package[k] for k in ['name', 'version', 'source']}, 'files': []}
for relative in ['dpi/LICENSE', 'LICENSE']:
    path = root / relative
    data = path.read_bytes()
    result['files'].append({'path': relative, 'symlink': path.is_symlink(),
        'linkText': os.readlink(path) if path.is_symlink() else None,
        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
        'shortText': repr(data) if len(data) < 128 else None})
print(json.dumps(result, indent=2), flush=True)
full.common.dependency_source_files(package, root)
print('Exact pinned dependency notice layout passed before native compilation.')
