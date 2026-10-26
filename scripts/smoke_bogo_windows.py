#!/usr/bin/env python3
"""Real MSI/portable smoke, permitted only in an explicitly selected ephemeral Windows CI VM."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile

import bogo_native as bogo


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_guid(value):
    pattern = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
    require(isinstance(value, str) and re.fullmatch('(?:' + pattern + r'|\{' + pattern + r'\})', value), 'Invalid Windows Installer GUID: expected a complete UUID with balanced optional braces')
    return str(uuid.UUID(value[1:-1] if value.startswith('{') else value)).upper()


def ico_frames(data):
    require(len(data) >= 6 and struct.unpack_from('<HH', data) == (0, 1), 'Invalid source ICO header')
    count = struct.unpack_from('<H', data, 4)[0]
    require(0 < count <= 32 and len(data) >= 6 + count * 16, 'Invalid source ICO directory')
    result = {}
    for index in range(count):
        offset = 6 + index * 16
        width, height = data[offset] or 256, data[offset + 1] or 256
        length, start = struct.unpack_from('<II', data, offset + 8)
        require(0 < length < 16 * 1024 * 1024 and start >= 6 + count * 16 and start + length <= len(data), 'Invalid ICO frame bounds')
        require((width, height) not in result, 'Duplicate ICO resolution')
        result[(width, height)] = data[start:start + length]
    return result


def pe_identity(path):
    with Path(path).open('rb') as stream:
        header = stream.read(64)
        require(header[:2] == b'MZ', 'Installed executable has no DOS header')
        offset = struct.unpack_from('<I', header, 60)[0]
        require(64 <= offset < Path(path).stat().st_size - 112, 'Invalid PE offset')
        stream.seek(offset)
        pe = stream.read(112)
    require(pe[:4] == b'PE\0\0' and struct.unpack_from('<H', pe, 4)[0] == 0x8664 and struct.unpack_from('<H', pe, 24)[0] == 0x20B, 'Expected a real Windows x64 PE32+ executable')
    require(struct.unpack_from('<H', pe, 92)[0] == 2, 'Expected the native Windows GUI subsystem')
    return {'machine': 'AMD64', 'format': 'PE32+', 'subsystem': 'Windows GUI'}


def extract_primary_icon(executable, source_ico, output):
    """Read actual PE RT_GROUP_ICON/RT_ICON resources without executing a DLL entry point."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD]
    kernel.LoadLibraryExW.restype = ctypes.c_void_p
    kernel.FindResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    kernel.FindResourceW.restype = ctypes.c_void_p
    kernel.SizeofResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel.SizeofResource.restype = wintypes.DWORD
    kernel.LoadResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel.LoadResource.restype = ctypes.c_void_p
    kernel.LockResource.argtypes = [ctypes.c_void_p]
    kernel.LockResource.restype = ctypes.c_void_p
    kernel.FreeLibrary.argtypes = [ctypes.c_void_p]
    module = kernel.LoadLibraryExW(str(executable), None, 0x00000002 | 0x00000020)
    require(module, 'Could not load PE resources as data')
    try:
        names = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.LPARAM)
        def found(_module, _kind, name, _value):
            names.append(name if name <= 0xFFFF else ctypes.wstring_at(name))
            return True
        callback = callback_type(found)
        kernel.EnumResourceNamesW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, callback_type, wintypes.LPARAM]
        require(kernel.EnumResourceNamesW(module, ctypes.c_void_p(14), callback, 0) and names, 'Executable has no icon group')
        name = min((n for n in names if isinstance(n, int)), default=names[0])
        def resource(resource_name, kind):
            buffer = ctypes.create_unicode_buffer(resource_name) if isinstance(resource_name, str) else None
            pointer = ctypes.cast(buffer, ctypes.c_void_p) if buffer is not None else ctypes.c_void_p(resource_name)
            info = kernel.FindResourceW(module, pointer, ctypes.c_void_p(kind))
            require(info, 'Missing actual PE icon resource')
            size = kernel.SizeofResource(module, info)
            require(0 < size < 16 * 1024 * 1024, 'PE icon resource size refused')
            data = kernel.LockResource(kernel.LoadResource(module, info))
            require(data, 'Could not read actual PE icon resource')
            return ctypes.string_at(data, size)
        group = resource(name, 14)
        require(len(group) >= 6 and struct.unpack_from('<HH', group) == (0, 1), 'Invalid PE icon group')
        count = struct.unpack_from('<H', group, 4)[0]
        require(0 < count <= 32 and len(group) >= 6 + count * 14, 'Invalid PE icon group bounds')
        expected = ico_frames(Path(source_ico).read_bytes())
        payloads, directory, actual = [], [], {}
        start = 6 + count * 16
        for index in range(count):
            item = group[6 + index * 14:20 + index * 14]
            width, height = item[0] or 256, item[1] or 256
            size, identifier = struct.unpack_from('<IH', item, 8)
            payload = resource(identifier, 3)
            require(len(payload) == size, 'PE icon group/resource size mismatch')
            actual[(width, height)] = payload
            directory.append(item[:8] + struct.pack('<II', size, start))
            payloads.append(payload)
            start += size
        require(actual == expected, 'Installed PE icon pixels/resources differ from the owner-derived multiresolution ICO')
        extracted = struct.pack('<HHH', 0, 1, count) + b''.join(directory + payloads)
        Path(output).write_bytes(extracted)
        return {'resourceGroup': str(name), 'frames': sorted([list(size) for size in actual]), 'allFrameBytesMatchOwnerDerivedIco': True, 'extractedIco': str(output), 'sha256': hashlib.sha256(extracted).hexdigest()}
    finally:
        kernel.FreeLibrary(module)


def powershell(code, extra):
    environment = dict(public_process_environment(), **{key: str(value) for key, value in extra.items()})
    result = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', code], env=environment, capture_output=True, text=True, timeout=90)
    require(result.returncode == 0, result.stderr or result.stdout)
    return json.loads(result.stdout)


def msi_properties(path):
    return powershell("$ErrorActionPreference='Stop'; $w=New-Object -ComObject WindowsInstaller.Installer; $d=$w.OpenDatabase($env:BOGO_QA_MSI,0); $o=@{}; foreach($k in @('ProductName','Manufacturer','ProductVersion','ProductCode','UpgradeCode')) {$v=$d.OpenView(\"SELECT Value FROM Property WHERE Property='$k'\"); $v.Execute(); $r=$v.Fetch(); if($null -eq $r){throw \"Missing MSI property $k\"}; $o[$k]=$r.StringData(1); $v.Close()}; $o | ConvertTo-Json -Compress", {'BOGO_QA_MSI': path})


def msi_shortcuts(path):
    return powershell("$ErrorActionPreference='Stop'; $w=New-Object -ComObject WindowsInstaller.Installer; $d=$w.OpenDatabase($env:BOGO_QA_MSI,0); $v=$d.OpenView('SELECT Name, Directory_ FROM Shortcut'); $v.Execute(); $o=@(); while($null -ne ($r=$v.Fetch())) {$o+=@{name=$r.StringData(1);directory=$r.StringData(2)}}; $v.Close(); ConvertTo-Json -InputObject @($o) -Compress", {'BOGO_QA_MSI': path})


def file_version(path):
    return powershell("$v=[Diagnostics.FileVersionInfo]::GetVersionInfo($env:BOGO_QA_EXE); @{ProductName=$v.ProductName;FileDescription=$v.FileDescription;CompanyName=$v.CompanyName;ProductVersion=$v.ProductVersion;FileVersion=$v.FileVersion} | ConvertTo-Json -Compress", {'BOGO_QA_EXE': path})


def product_state(code):
    function = ctypes.WinDLL('msi').MsiQueryProductStateW
    function.argtypes = [ctypes.c_wchar_p]
    function.restype = ctypes.c_int
    return function(code)


def msi_run(arguments, log):
    result = subprocess.run(['msiexec.exe', *arguments, '/qn', '/norestart', '/l*v', str(log)], env=public_process_environment(), timeout=600)
    require(result.returncode in (0, 3010), 'Actual Windows Installer failed with code ' + str(result.returncode) + '; ' + str(log))
    return result.returncode


def public_process_environment():
    return {key: value for key, value in os.environ.items() if not any(word in key.upper() for word in ('TOKEN', 'SECRET', 'PASSWORD', 'PRIVATE_KEY', 'GITHUB', 'ACTIONS_'))}


def child_environment(directory):
    environment = public_process_environment()
    environment['APPDATA'] = str(directory / 'AppData/Roaming')
    environment['LOCALAPPDATA'] = str(directory / 'AppData/Local')
    environment['BOGO_QA_ROOT'] = str(directory / 'app-profile')
    environment['BOGO_QA_MODE'] = '1'
    environment['TEMP'] = environment['TMP'] = str(directory / 'temp')
    for key in ('APPDATA', 'LOCALAPPDATA', 'BOGO_QA_ROOT', 'TEMP'):
        Path(environment[key]).mkdir(parents=True, exist_ok=True)
    return environment


def runtime_source_png(app, output):
    assets = bogo.ROOT / 'assets/bogo-program-icons'
    icons = json.loads((assets / 'native-icons.json').read_text(encoding='utf-8'))['items']
    icon = next(row for row in icons if row['id'] == app)
    icns = (assets / (app + '.icns')).read_bytes()
    require(hashlib.sha256(icns).hexdigest() == icon['icns']['sha256'], 'Approved ICNS resource changed')
    require(icns[:4] == b'icns' and struct.unpack_from('>I', icns, 4)[0] == len(icns), 'Invalid ICNS directory')
    chunks, offset = [], 8
    while offset < len(icns):
        require(offset + 8 <= len(icns), 'Truncated ICNS chunk')
        length = struct.unpack_from('>I', icns, offset + 4)[0]
        require(8 <= length <= len(icns) - offset, 'Invalid ICNS chunk bounds')
        if icns[offset:offset + 4] == b'ic08':
            chunks.append(icns[offset + 8:offset + length])
        offset += length
    require(len(chunks) == 1 and chunks[0][:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack_from('>II', chunks[0], 16) == (256, 256), 'Expected one approved 256 px runtime source PNG')
    source_path = 'assets/app-icon/hicolor/256x256/apps/com.kio.' + app + '.png'
    expected = next(row['after'] for row in bogo.load_lock(app)['bogoOverlay']['files'] if row['path'] == source_path)
    raw = chunks[0]
    require(hashlib.sha256(raw).hexdigest() == expected['sha256'] and len(raw) == expected['bytes'], 'Runtime PNG differs from the exact compiled viewport source overlay')
    path = Path(output) / 'approved-runtime-source.png'
    require(not path.exists(), 'Runtime source evidence already exists')
    path.write_bytes(raw)
    return path, expected['sha256']


def gui_startup(executable, environment, log, app, runtime_png, runtime_png_sha256):
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageW.restype = ctypes.c_void_p
    user.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype = ctypes.c_void_p
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.PostMessageW.restype = wintypes.BOOL
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.GetForegroundWindow.argtypes = []
    user.GetForegroundWindow.restype = wintypes.HWND
    with Path(log).open('wb') as output:
        process = subprocess.Popen([str(executable)], env=environment, stdout=output, stderr=subprocess.STDOUT)
        windows = []
        try:
            for _ in range(150):
                if process.poll() is not None:
                    raise ValueError('GUI exited before a visible native window: ' + str(process.returncode))
                windows.clear()
                def window(hwnd, _value):
                    pid = wintypes.DWORD()
                    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value == process.pid and user.IsWindowVisible(hwnd):
                        text = ctypes.create_unicode_buffer(user.GetWindowTextLengthW(hwnd) + 1)
                        user.GetWindowTextW(hwnd, text, len(text))
                        icon = ctypes.c_size_t()
                        for kind in (0, 1):
                            if user.SendMessageTimeoutW(hwnd, 0x7F, kind, 0, 0x2, 1000, ctypes.byref(icon)) and icon.value:
                                break
                        windows.append({'title': text.value, 'windowHandle': int(hwnd), 'windowIconHandle': icon.value})
                    return True
                callback = callback_type(window)
                user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
                user.EnumWindows(callback, 0)
                if any('Bogo' in row['title'] for row in windows):
                    break
                time.sleep(.2)
            require(any('Bogo' in row['title'] for row in windows), 'No visible Bogo native window title was observed')
            own = next(row for row in windows if 'Bogo' in row['title'])
            user.SetForegroundWindow(own['windowHandle'])
            time.sleep(1)
            require(user.GetForegroundWindow() == own['windowHandle'], 'Own GUI did not become foreground; refusing to capture unrelated/occluded screen pixels')
            from bogo_runtime_icons import check_runtime_icons, application_lock_for
            runtime_icons = check_runtime_icons(own['windowHandle'], process.pid,
                bogo.ROOT / 'assets/bogo-program-icons' / (app + '.ico'),
                digest(bogo.ROOT / 'assets/bogo-program-icons' / (app + '.ico')),
                Path(log).with_suffix('.runtime-icons'), runtime_png=runtime_png,
                approved_runtime_png_sha256=runtime_png_sha256,
                application_cargo_lock=application_lock_for(app))
            current_owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(own['windowHandle'], ctypes.byref(current_owner))
            require(current_owner.value == process.pid and user.GetForegroundWindow() == own['windowHandle'], 'Own foreground window changed during icon verification; screenshot refused')
            rectangle = wintypes.RECT()
            user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            require(user.GetClientRect(own['windowHandle'], ctypes.byref(rectangle)), 'Cannot obtain own GUI client rectangle')
            point = wintypes.POINT()
            user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            require(user.ClientToScreen(own['windowHandle'], ctypes.byref(point)), 'Cannot locate own GUI client rectangle')
            width, height = rectangle.right - rectangle.left, rectangle.bottom - rectangle.top
            require(100 <= width <= 10000 and 100 <= height <= 10000, 'Own GUI screenshot dimensions refused')
            screenshot = Path(log).with_suffix('.png')
            capture = powershell("$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Drawing; $w=[int]$env:BOGO_QA_WIDTH; $h=[int]$env:BOGO_QA_HEIGHT; $b=New-Object Drawing.Bitmap($w,$h); $g=[Drawing.Graphics]::FromImage($b); try {$g.CopyFromScreen([int]$env:BOGO_QA_LEFT,[int]$env:BOGO_QA_TOP,0,0,(New-Object Drawing.Size($w,$h))); $b.Save($env:BOGO_QA_SCREENSHOT,[Drawing.Imaging.ImageFormat]::Png); $counts=@{'FFF3E8'=0;'FFFAF6'=0;'FFE7D4'=0;'F1D3BD'=0;'342B26'=0}; for($y=0;$y -lt [Math]::Min($h,180);$y+=2){for($x=0;$x -lt $w;$x+=2){$p=$b.GetPixel($x,$y);$s=('{0:X2}{1:X2}{2:X2}' -f $p.R,$p.G,$p.B);if($counts.ContainsKey($s)){$counts[$s]++}}}; @{width=$w;height=$h;top180SampleStride=2;paletteCounts=$counts;png=$env:BOGO_QA_SCREENSHOT} | ConvertTo-Json -Compress} finally {$g.Dispose();$b.Dispose()}", {'BOGO_QA_LEFT': point.x, 'BOGO_QA_TOP': point.y, 'BOGO_QA_WIDTH': width, 'BOGO_QA_HEIGHT': height, 'BOGO_QA_SCREENSHOT': screenshot})
            require(screenshot.is_file() and screenshot.stat().st_size > 1024, 'Own native GUI screenshot was not captured')
            capture['sha256'] = digest(screenshot)
            capture['themeAssessment'] = 'actual native-window pixels retained for visual review; palette counts alone do not establish all UI states'
            return {'pid': process.pid, 'visibleWindows': list(windows), 'started': True, 'screenshot': capture, 'runtimeIcons': runtime_icons, 'scope': 'new process in ephemeral CI VM; own window/taskbar/Alt+Tab icon-source pixels checked, PE icons checked separately; existing user pins not modified or claimed'}
        finally:
            if process.poll() is None:
                for row in windows:
                    owner = wintypes.DWORD()
                    user.GetWindowThreadProcessId(row['windowHandle'], ctypes.byref(owner))
                    if owner.value == process.pid:
                        user.PostMessageW(row['windowHandle'], 0x10, 0, 0)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)


def advertised_target(path, product_code):
    """Read the MSI descriptor and installed component path without self-repair."""
    from ctypes import wintypes
    msi = ctypes.WinDLL('msi')
    msi.MsiGetShortcutTargetW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPWSTR, wintypes.LPWSTR]
    msi.MsiGetShortcutTargetW.restype = wintypes.UINT
    product, feature, component = ctypes.create_unicode_buffer(39), ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(39)
    if msi.MsiGetShortcutTargetW(str(path), product, feature, component) != 0:
        return None
    require(product.value.upper() == product_code.upper(), 'Advertised shortcut belongs to a different MSI product')
    msi.MsiGetComponentPathW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    msi.MsiGetComponentPathW.restype = ctypes.c_int
    target, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
    state = msi.MsiGetComponentPathW(product, component, target, ctypes.byref(length))
    require(state == 3 and target.value, 'Advertised shortcut component is not installed locally')
    return {'productCode': product.value, 'feature': feature.value, 'componentCode': component.value, 'installedComponentPath': target.value, 'queryOnlyNoRepair': True}


def shortcuts(name, legacy_name, executable, expected_ico, output, authored, product_code):
    """Inspect real post-upgrade desktop/Start Menu links and their cached icon bytes."""
    links = powershell("$ErrorActionPreference='Stop'; $w=New-Object -ComObject WScript.Shell; $rows=@(); foreach($kind in @('DesktopDirectory','CommonDesktopDirectory','Programs','CommonPrograms')) {$folder=[Environment]::GetFolderPath($kind); if($folder -and (Test-Path -LiteralPath $folder)) {foreach($n in @($env:BOGO_QA_NAME,$env:BOGO_QA_OLD_NAME)) {$p=Join-Path $folder ($n+'.lnk'); if(Test-Path -LiteralPath $p) {$s=$w.CreateShortcut($p); $rows+=@{path=$p;name=$n;kind=$kind;target=$s.TargetPath;icon=$s.IconLocation}}}}}; ConvertTo-Json -InputObject @($rows) -Compress", {'BOGO_QA_NAME': name, 'BOGO_QA_OLD_NAME': legacy_name})
    require(not any(row['name'] == legacy_name for row in links), 'Legacy desktop/Start Menu display link remains after upgrade')
    current = [row for row in links if row['name'] == name]
    require(any('Programs' in row['kind'] for row in current), 'New MSI did not create its authored Bogo Start Menu shortcut')
    desktop = any(row['directory'] in ('DesktopFolder', 'CommonDesktopFolder') for row in authored)
    if desktop:
        require(any('Desktop' in row['kind'] for row in current), 'New MSI did not create its authored Bogo desktop shortcut')
    for index, row in enumerate(current):
        advertised = advertised_target(row['path'], product_code)
        if advertised is not None:
            row['advertised'] = advertised
        target = advertised['installedComponentPath'] if advertised is not None else row['target']
        require(Path(target).resolve() == executable.resolve(), 'Bogo shortcut target differs from installed executable')
        icon_path = Path(row['icon'].rsplit(',', 1)[0].strip('"'))
        require(icon_path.is_file(), 'Installed shortcut icon file is missing')
        raw = icon_path.read_bytes()
        if raw[:4] == b'\0\0\1\0':
            require(ico_frames(raw) == ico_frames(Path(expected_ico).read_bytes()), 'Cached Windows Installer shortcut icon differs')
            row['iconAllFrameBytesMatch'] = True
            row['iconSha256'] = digest(icon_path)
        else:
            row['iconReadback'] = extract_primary_icon(icon_path, expected_ico, output / ('shortcut-' + str(index) + '.ico'))
    return {'authoredMsiRows': authored, 'actualLinks': current, 'desktop': 'verified' if desktop else 'not-authored-by-this-installer', 'startMenu': 'verified'}


def ephemeral_output(output, explicit):
    require(sys.platform == 'win32' and os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_OS') == 'Windows' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted' and explicit, 'Actual install smoke requires explicit opt-in on an ephemeral GitHub-hosted Windows runner')
    require(os.environ.get('GITHUB_REPOSITORY') == 'qptywoei-sudo/bogo-native-apps' and os.environ.get('GITHUB_WORKFLOW') in ('Full native Bogo applications (reviewed branch dispatch)', 'Bogo native applications (manual verification)', 'Bogo Windows artifact acceptance (manual)'), 'Actual install smoke requires the reviewed repository/workflow context')
    require(os.environ.get('GITHUB_REF') == 'refs/heads/codex/bogo-native-rebrand-20261026', 'Actual install smoke requires the reviewed Bogo feature branch')
    base = Path(os.environ['RUNNER_TEMP'])
    require(base.is_absolute() and base.is_dir(), 'RUNNER_TEMP must be an existing absolute runner directory')
    output = Path(output)
    require(output.is_absolute(), 'Smoke output must be absolute')
    for path in [base, *base.parents, *[path for path in (output, *output.parents) if path.exists() or path.is_symlink()]]:
        metadata = path.lstat()
        require(not path.is_symlink() and not (getattr(metadata, 'st_file_attributes', 0) & 0x400), 'Runner/output ancestry must not contain links or reparse points')
    base, output = base.resolve(), output.resolve()
    require(output.is_relative_to(base) and output != base and not output.exists(), 'Smoke output must be a fresh directory inside RUNNER_TEMP')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', choices=tuple(bogo.NAMES), required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-ephemeral-install', action='store_true')
    args = parser.parse_args()
    output = ephemeral_output(args.output, args.allow_ephemeral_install)
    output.mkdir(parents=True)
    lock = bogo.load_lock(args.app)
    folder = args.directory.resolve()
    bogo.full.verify(folder, lock, 'windows-x64')
    pins = json.loads((bogo.ROOT / 'manifests/bogo-legacy-upgrade-inputs.json').read_text(encoding='utf-8'))
    old = next(row for row in pins['applications'] if row['id'] == args.app)
    old_file = output / 'verified-legacy.msi'
    current = folder / (lock['assetPrefix'] + '-' + lock['version'] + '-windows-x64.msi')
    portable = folder / (lock['assetPrefix'] + '-' + lock['version'] + '-windows-x64.zip')
    provenance = json.loads((folder / (lock['assetPrefix'] + '-' + lock['version'] + '-windows-x64-provenance.json')).read_text(encoding='utf-8'))
    expected_binary = provenance['binaries']['app']
    report = {'schema': 1, 'app': args.app, 'version': lock['version'], 'platform': 'windows-x64', 'ephemeralRunnerOnly': True, 'steps': [], 'status': 'running', 'scope': 'actual old/new MSI install+upgrade, installed/portable GUI execution, actual PE icons; no publisher certificate claimed'}
    installed_codes = []
    try:
        from bogo_msi_art import verify_msi_art
        report['installerArtwork'] = verify_msi_art(current, args.app, output / 'installer-artwork')
        runtime_png, runtime_png_sha256 = runtime_source_png(args.app, output)
        pin = old['windowsMsi']
        require(pin['url'].startswith('https://github.com/qptywoei777-rgb/kio-native-apps/releases/download/' + args.app + '-v'), 'Legacy input outside exact app releases')
        urllib.request.urlretrieve(pin['url'], old_file)
        require(old_file.stat().st_size == pin['bytes'] and digest(old_file) == pin['sha256'], 'Downloaded old MSI differs from its actual published pin')
        prior, new = msi_properties(old_file), msi_properties(current)
        report['msiIdentityBeforeInstall'] = {'legacy': prior, 'bogo': new, 'pinnedUpgradeCode': old['upgradeCode']}
        require(prior['ProductName'] == old['name'] and prior['Manufacturer'] == 'KIO', 'Legacy MSI product/publisher differs')
        require(new['ProductName'] == lock['name'] and new['Manufacturer'] == 'Bogo', 'New MSI product/publisher differs')
        require(canonical_guid(prior['UpgradeCode']) == canonical_guid(new['UpgradeCode']) == canonical_guid(old['upgradeCode']), 'Actual old/new MSI UpgradeCode continuity failed')
        require(canonical_guid(prior['ProductCode']) != canonical_guid(new['ProductCode']), 'A real new MSI ProductCode is required')
        require(product_state(prior['ProductCode']) == -1 and product_state(new['ProductCode']) == -1, 'Refusing smoke against a pre-existing Windows installation')
        destination = output / 'installed'
        appdata = child_environment(output / 'isolated-user')
        sentinels = []
        for key in ('APPDATA', 'LOCALAPPDATA'):
            path = Path(appdata[key]) / lock['bundleId'] / 'qa-existing-data.txt'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'Bogo synthetic continuity fixture; preserve exact bytes\n')
            sentinels.append((path, digest(path)))
        installed_codes.append(prior['ProductCode'])
        old_exit = msi_run(['/i', str(old_file), 'INSTALLFOLDER=' + str(destination), 'DESKTOPSHORTCUT=1', 'INSTALLDESKTOPSHORTCUT=1'], output / 'old-install.log')
        require(product_state(prior['ProductCode']) == 5, 'Old MSI did not reach installed state')
        installed_codes.append(new['ProductCode'])
        new_exit = msi_run(['/i', str(current)], output / 'new-upgrade.log')
        require(product_state(new['ProductCode']) == 5 and product_state(prior['ProductCode']) == -1, 'Actual old-to-Bogo MSI upgrade did not replace the old product')
        report['actualMsiUpgrade'] = {'legacy': prior, 'bogo': new, 'oldInstallExit': old_exit, 'upgradeExit': new_exit, 'sameUpgradeCode': True, 'oldProductRemoved': True, 'newProductInstalled': True, 'installDirectory': str(destination)}
        binaries = [path for path in destination.rglob('*.exe') if path.name in (lock['name'] + '.exe', lock['binaries']['app'] + '.exe')]
        binaries = [path for path in binaries if file_version(path)['ProductName'] == lock['name']]
        require(len(binaries) == 1, 'Cannot identify the actual newly installed GUI executable')
        installed = binaries[0]
        require(digest(installed) == expected_binary['sha256'] and installed.stat().st_size == expected_binary['bytes'], 'Installed MSI GUI differs from the authenticated new native build provenance')
        report['actualMsiUpgrade']['legacyCustomInstallDirectoryPreservedWithoutOverride'] = True
        report['shortcuts'] = shortcuts(lock['name'], old['name'], installed, bogo.ROOT / 'assets/bogo-program-icons' / (args.app + '.ico'), output, msi_shortcuts(current), new['ProductCode'])
        report['installedExe'] = {'path': str(installed), 'sha256': digest(installed), 'pe': pe_identity(installed), 'versionInfo': file_version(installed), 'icon': extract_primary_icon(installed, bogo.ROOT / 'assets/bogo-program-icons' / (args.app + '.ico'), output / 'installed-primary-icon.ico')}
        report['installedGui'] = gui_startup(installed, appdata, output / 'installed-gui.log', args.app, runtime_png, runtime_png_sha256)
        unpack = output / 'portable'
        with zipfile.ZipFile(portable) as archive:
            for name in archive.namelist():
                require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'Portable ZIP unsafe member')
            archive.extractall(unpack)
        candidates = [path for path in unpack.rglob('*.exe') if path.name in (lock['name'] + '.exe', lock['binaries']['app'] + '.exe')]
        candidates = [path for path in candidates if file_version(path)['ProductName'] == lock['name']]
        require(len(candidates) == 1 and digest(candidates[0]) == digest(installed), 'Portable and installed GUI bytes differ')
        binary = candidates[0]
        report['portableExe'] = {'path': str(binary), 'sha256': digest(binary), 'pe': pe_identity(binary), 'versionInfo': file_version(binary), 'icon': extract_primary_icon(binary, bogo.ROOT / 'assets/bogo-program-icons' / (args.app + '.ico'), output / 'portable-primary-icon.ico')}
        report['portableGui'] = gui_startup(binary, child_environment(output / 'portable-user'), output / 'portable-gui.log', args.app, runtime_png, runtime_png_sha256)
        require(all(path.exists() and digest(path) == sha for path, sha in sentinels), 'Synthetic existing profile data changed')
        report['syntheticProfileCanariesPreserved'] = True
        report['profileScope'] = 'isolated APPDATA/LOCALAPPDATA continuity fixtures in disposable VM; real-user profile migration is separately source-audited'
        report['status'] = 'passed'
    except Exception as error:
        report['status'], report['error'] = 'failed', str(error)
    finally:
        report['cleanup'] = []
        for code in reversed(installed_codes):
            state = product_state(code)
            cleanup = {'productCode': code, 'stateBefore': state}
            report['cleanup'].append(cleanup)
            if state != -1:
                try:
                    result = msi_run(['/x', code], output / ('uninstall-' + code.strip('{}') + '.log'))
                    cleanup.update({'exitCode': result, 'stateAfter': product_state(code)})
                    require(cleanup['stateAfter'] == -1, 'Owned MSI registration remains after cleanup')
                except Exception as error:
                    cleanup.update({'error': str(error), 'stateAfter': product_state(code)})
                    report['status'] = 'failed'
            else:
                cleanup['result'] = 'already-unregistered'
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'app': args.app, 'status': report['status'], 'report': str(output / 'report.json'), 'error': report.get('error')}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print('Bogo Windows smoke refused/stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
