#!/usr/bin/env python3
"""Read prepared WiX XML against its immutable upstream, without building or executing apps.

This detects installer identity/registry collisions that a branding text check misses.
No network access, registry writes, or install/uninstall operations are performed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = {'w': 'http://wixtoolset.org/schemas/v4/wxs'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _key(value):
    return (value or '').replace('/', '\\').casefold().rstrip('\\')


def _registrations(tree, tag):
    # A value is removed when its component is uninstalled: same key/value name is a collision
    # even when its new string data points at a different, correctly branded executable.
    return {(_key(e.get('Root')), _key(e.get('Key')), _key(e.get('Name'))) for e in tree.findall('.//w:' + tag, NS)}


def _guids(tree):
    return {_key(e.get('Guid')) for e in tree.findall('.//w:Component', NS) if e.get('Guid') not in (None, '*')}


def _upstream(lock, archive_cache=None):
    source = lock['source']
    archive = Path(archive_cache or ROOT / '.cache/archives') / (source['root'] + '.tar.gz')
    require(archive.is_file(), 'Pinned source archive missing; this audit never downloads inputs')
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    require(digest.hexdigest() == source['sha256'] and archive.stat().st_size == source['bytes'], 'Pinned source archive integrity failure')
    relative = 'packaging/windows/' + lock['binaries']['app'] + '.wxs'
    with tarfile.open(archive) as tar:
        member = tar.getmember(source['root'] + '/' + relative)
        require(member.isfile(), 'Original WiX XML must be a regular source file')
        stream = tar.extractfile(member)
        require(stream is not None, 'Original WiX XML missing')
        return relative, stream.read()


def audit(lock, source: Path, *, original_xml: bytes | None = None, archive_cache=None):
    """Return evidence or raise ValueError. ``source`` is the actual prepared source root."""
    relative = 'packaging/windows/' + lock['binaries']['app'] + '.wxs'
    if original_xml is None:
        relative, original_xml = _upstream(lock, archive_cache)
    original = ET.fromstring(original_xml)
    wxs = source / relative
    require(wxs.is_file() and not wxs.is_symlink(), 'Prepared WiX XML missing or symlinked')
    prepared = ET.parse(wxs).getroot()
    package = prepared.find('w:Package', NS)
    old_package = original.find('w:Package', NS)
    require(package is not None and old_package is not None, 'WiX package missing')
    require(package.get('Name') == lock['name'] and package.get('Manufacturer') == 'KIO', 'MSI app/publisher identity mismatch')
    require(package.get('UpgradeCode') and _key(package.get('UpgradeCode')) != _key(old_package.get('UpgradeCode')), 'Upstream UpgradeCode reused')
    if package.get('ProductCode') and old_package.get('ProductCode'):
        require(_key(package.get('ProductCode')) != _key(old_package.get('ProductCode')), 'Upstream fixed ProductCode reused')
    require(not (_guids(prepared) & _guids(original)), 'Upstream fixed component GUID reused')
    directory = prepared.find('.//w:Directory[@Id="INSTALLFOLDER"]', NS)
    require(directory is not None and directory.get('Name') == lock['name'], 'Default install directory must have exact KIO app name')
    gui = [e for e in prepared.findall('.//w:File', NS) if _key(e.get('Source')).endswith('\\' + _key(lock['binaries']['app']) + '.exe')]
    require(len(gui) == 1 and gui[0].get('Name') == lock['name'] + '.exe', 'Installed GUI filename must have exact KIO app name')
    require(not (_registrations(prepared, 'RegistryValue') & _registrations(original, 'RegistryValue')), 'Upstream registry value registration reused')
    require(not (_registrations(prepared, 'RegistrySearch') & _registrations(original, 'RegistrySearch')), 'Upstream install/path RegistrySearch reused')
    old_progids = {_key(e.get('Id')) for e in original.findall('.//w:ProgId', NS)}
    progids = {_key(e.get('Id')) for e in prepared.findall('.//w:ProgId', NS)}
    require(not (old_progids & progids), 'Upstream file association ProgId reused')
    require(all(p.startswith('kio.') for p in progids), 'File association ProgId must be KIO-specific')
    # Extension writes the shared extension's default value. OpenWithProgids preserves the
    # native format handler without claiming an upstream/user's current default application.
    old_ext = {_key(e.get('Id')) for e in original.findall('.//w:Extension', NS)}
    require(not (old_ext & {_key(e.get('Id')) for e in prepared.findall('.//w:Extension', NS)}), 'Shared extension default ownership reused; use unique OpenWithProgids')
    values = prepared.findall('.//w:RegistryValue', NS)
    searches = prepared.findall('.//w:RegistrySearch', NS)
    app_paths = [e for e in values if '\\app paths\\' in _key(e.get('Key'))]
    require(app_paths and all(_key(e.get('Key')).endswith('\\' + _key(lock['name']) + '.exe') for e in app_paths), 'App Paths must name only this KIO GUI')
    for entry in values + searches:
        key = _key(entry.get('Key'))
        if '\\app paths\\' in key:
            require(key.endswith('\\' + _key(lock['name']) + '.exe'), 'Upstream/cross-app App Paths access')
        if '\\applications\\' in key:
            app_segment = key.split('\\applications\\', 1)[1].split('\\', 1)[0]
            require(app_segment == _key(lock['name']) + '.exe', 'OpenWith Applications entry names another executable')
    # All supported upstream types remain offered through the KIO Applications entry.
    old_types = {e.get('Name') for e in original.findall('.//w:RegistryValue', NS) if _key(e.get('Key')).endswith('\\supportedtypes')}
    new_types = {e.get('Name') for e in values if _key(e.get('Key')).endswith('\\supportedtypes')}
    require(old_types <= new_types, 'Supported input types removed from Windows OpenWith')
    for shortcut in prepared.findall('.//w:ShortcutProperty', NS):
        if shortcut.get('Key') == 'System.AppUserModel.ID':
            require(shortcut.get('Value') == lock['bundleId'], 'Shortcut AppUserModelId is not this KIO app')
    return {'app': lock['id'], 'wxs': relative, 'sha256': hashlib.sha256(wxs.read_bytes()).hexdigest(),
            'name': lock['name'], 'upgradeCode': package.get('UpgradeCode'), 'gui': gui[0].get('Name'),
            'fixedComponentGuids': sorted(_guids(prepared)), 'registryValues': len(values), 'registrySearches': len(searches),
            'progIds': sorted(progids), 'supportedTypesRetained': sorted(old_types),
            'checks': {'upstreamRegistryAndComponentIsolation': True, 'upstreamDefaultAppUnchanged': True,
                       'kioAppPathsAndGuiMatch': True, 'kioInstallDirectory': True, 'noNativeExecution': True}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, choices=['photo', 'vector', 'film', 'light', 'pdf', 'effect', 'design', 'ui', 'word', 'sound', 'deck', 'cad', 'grid', 'launcher'])
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    if args.app == 'launcher':
        import launcher_native
        lock = launcher_native.load_lock()
    else:
        import full_native
        lock = full_native.load_lock(args.app)
    print(json.dumps(audit(lock, args.source), indent=2))


if __name__ == '__main__':
    main()
