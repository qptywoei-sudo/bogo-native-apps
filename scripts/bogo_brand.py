#!/usr/bin/env python3
"""Bogo display-only transformation, recorded as exact per-app binary Git overlays."""
import base64
import io
import json
import re
import shutil
from pathlib import Path

from bogo_assets import ASSETS, originals

NAMES = {'cad': 'CAD', 'design': 'Design', 'vector': 'Vector', 'film': 'Film', 'light': 'Light', 'pdf': 'PDF', 'effect': 'Effect', 'ui': 'UI', 'word': 'Word', 'sound': 'Sound', 'deck': 'Deck', 'grid': 'Grid', 'launcher': 'Launcher', 'photo': 'Photo'}
PALETTE = {'brand': 'FC7501', 'header': 'FFF3E8', 'background': 'FFFAF6', 'hover': 'FFE7D4', 'border': 'F1D3BD', 'text': '342B26'}
STORAGE_FILES = {'app_dirs.rs', 'paths.rs', 'portable.rs', 'profile.rs', 'profiles.rs', 'user_dirs.rs'}
SPECIAL = {'crates/core/src/catalog.rs', 'crates/core/src/kio_registry.rs', 'crates/core/src/version.rs', 'crates/native/src/detect.rs', 'crates/native/src/install.rs', 'apps/lightcraft/src/editors.rs', 'apps/pdfcraft/src/updates.rs'}
TECHNICAL = re.compile(r'(?i)ProjectDirs|\.join\(|PathBuf::|Path::|(?<![A-Za-z0-9])[A-Za-z]:[\\/]|Software\\|HKEY_|PORTABLE_MARKERS|PORTABLE_DATA_DIR|(?:DATA|PROFILE|CONFIG)_DIR|registry_key|former_names|legacy_name')


def display(text):
    text = re.sub(r'KIO (CAD|Cad|Design|Vector|Film|Light|PDF|Effect|UI|Word|Sound|Deck|Grid|Launcher|Photo)(?![A-Za-z])', lambda m: 'Bogo ' + ('CAD' if m[1] == 'Cad' else m[1]), text)
    return text.replace('Independent KIO fork', 'Independent Bogo fork').replace('KIO branding', 'Bogo branding').replace('KIO Apps', 'Bogo Apps').replace('KIO Work', 'Bogo Work').replace('KIO App Suite', 'Bogo App Suite')


def rust_display(text):
    result = []
    for line in text.splitlines(keepends=True):
        if 'Copyright' in line or 'copyright' in line or TECHNICAL.search(line):
            result.append(line)
        else:
            line = display(line)
            if '.set("CompanyName", "KIO")' in line:
                line = line.replace('.set("CompanyName", "KIO")', '.set("CompanyName", "Bogo")')
            result.append(line)
    return ''.join(result)


def xml_display(text):
    # MSI GUIDs, registration keys, component IDs and bundle identifiers remain exact.
    protected = []
    def keep(match):
        protected.append(match[0])
        return f'__BOGO_KEEP_{len(protected)-1}__'
    text = re.sub(r'\b(?:Key|Id|Guid|UpgradeCode|ProductCode|Source|SourceFile)="[^"]*"|\bValue="(?:Software\\|KIO\.|com\.kio\.)[^"]*"', keep, text)
    text = display(text).replace('Manufacturer="KIO"', 'Manufacturer="Bogo"')
    for index, value in enumerate(protected):
        text = text.replace(f'__BOGO_KEEP_{index}__', value)
    return text


def theme(text):
    """Change chrome tokens only; document content, semantic colours and metrics stay intact."""
    header = {'title_bar', 'titlebar', 'ribbon', 'tab_strip', 'tab_bar', 'tab_bg', 'header_bg', 'app_bar', 'chrome', 'toolbar_bg', 'menu_bar', 'status_bar', 'tl_header_bg'}
    background = {'bg', 'app_bg', 'window', 'window_bg', 'panel', 'panel_bg', 'panel_bg2', 'panel_darker', 'dock', 'card', 'button', 'field', 'field_bg', 'input_bg', 'input', 'menu_bg', 'sunken', 'inset', 'toolbar_group', 'tab_inactive', 'tab_active', 'tab_bar_bg', 'strip_bg', 'strip_section'}
    hover = {'hover', 'pressed', 'checked', 'selection', 'row_selected', 'tool_active', 'cell_selected', 'header_sel_bg', 'header_all_bg', 'tab_selected', 'accent_soft', 'button_hi', 'well', 'name_field_sel', 'header_selected', 'strip_selected', 'control_hover'}
    border = {'border', 'border_strong', 'border_light', 'ribbon_border', 'divider', 'separator', 'line', 'line_strong', 'field_border', 'input_border', 'button_border', 'card_border', 'section_divider', 'header_line', 'well_rim', 'control_border', 'group_border'}
    text_fields = {'text', 'text_strong', 'text_dim', 'text_secondary', 'text_tertiary', 'text_faint', 'text_muted', 'text_disabled', 'ink', 'ink_strong', 'muted', 'faint', 'icon', 'header_text', 'tab_text', 'tab_text_active', 'accent_text', 'accent_ink', 'accent_dark', 'accent_strong', 'primary_text', 'invert_fg', 'header_sel_text', 'text_label', 'section_label'}
    brand = {'accent', 'primary_bg', 'invert_bg', 'APP_COLOR', 'APP_INK', 'ACCENT', 'icon_accent'}
    def field(match):
        prefix, name, value = match.groups()
        key = 'header' if name in header else 'background' if name in background else 'hover' if name in hover else 'border' if name in border else 'text' if name in text_fields else 'brand' if name in brand else None
        if not key:
            return match[0]
        colour = PALETTE[key]
        expression = 'Color32::from_rgb(' + ', '.join('0x' + colour[i:i+2] for i in (0, 2, 4)) + ')'
        return prefix + name + ': ' + expression + ','
    # One-line token initializers only; never touch command/canvas implementation.
    text = re.sub(r'(^\s*)(\w+):\s*((?:Color32::\w+(?:\([^\n]*?\))?|hex\([^\n]*?\)|ink_alpha\([^\n]*?\))),', field, text, flags=re.M)
    for name in brand:
        colour = 'Color32::from_rgb(0x34, 0x2B, 0x26)' if name == 'APP_INK' else 'Color32::from_rgb(0xFC, 0x75, 0x01)'
        text = re.sub(r'(pub const ' + name + r': Color32 = )[^;\n]+;', r'\g<1>' + colour + ';', text)
    return text


def icon_assets(source, app):
    from PIL import Image
    row, original, image = next(r for r in originals() if r[0]['id'] == app)
    folder = source / 'assets/app-icon'
    if not folder.is_dir():
        raise ValueError('Native app icon folder missing: ' + app)
    for path in sorted(folder.rglob('*')):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == '.png':
            previous = Image.open(path)
            size = previous.size
            if size[0] != size[1] or size[0] > 2048:
                raise ValueError('Unexpected native icon geometry: ' + str(path))
            if size == (1024, 1024):
                shutil.copyfile(original, path)
            else:
                image.resize(size, Image.Resampling.LANCZOS).save(path, format='PNG')
        elif suffix in ('.ico', '.icns'):
            shutil.copyfile(ASSETS / (app + suffix), path)
        elif suffix == '.svg':
            # The exact owner PNG is embedded, never traced, recoloured or cropped.
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1024" height="1024" viewBox="0 0 1024 1024"><image width="1024" height="1024" xlink:href="data:image/png;base64,' + base64.b64encode(original.read_bytes()).decode('ascii') + '"/></svg>\n')
    (folder / 'BOGO-ICON-SOURCE.txt').write_text('Bogo ' + NAMES[app] + '\nOwner-provided original artwork from the approved Google Drive icon set.\nOriginal PNG: ' + row['filename'] + '\nSHA-256: ' + row['sha256'] + '\nOnly resolution conversion was used for native ICO/ICNS resources.\nOriginal upstream notices remain in the distribution.\n')


def transform_source(source, app):
    source = Path(source)
    for path in sorted(source.rglob('*')):
        if not path.is_file() or '.git' in path.parts:
            continue
        relative = path.relative_to(source).as_posix()
        if relative in SPECIAL or path.name in STORAGE_FILES or path.name in ('Cargo.toml', 'Cargo.lock'):
            continue
        # Engine/document model, dependencies, test inputs, licences and contributor records stay exact.
        allowed = relative.startswith(('apps/', 'crates/ui-egui/', 'crates/native/', 'crates/core/', 'packaging/', 'locales/', 'i18n/', 'translations/'))
        if not allowed or path.suffix.lower() not in ('.rs', '.json', '.po', '.ftl', '.xml', '.in', '.wxs', '.ps1', '.sh', '.html', '.desktop', '.toml', '.tsv'):
            continue
        try:
            old = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        if relative.startswith('packaging/') and path.suffix in ('.wxs', '.xml'):
            new = xml_display(old)
        elif relative.startswith('packaging/'):
            # Preserve installer storage/registry strings; display labels and sealed bundle names change.
            new = rust_display(old)
        elif path.suffix == '.rs':
            new = rust_display(old)
        else:
            new = display(old)
        if relative == 'crates/ui-egui/src/theme.rs':
            new = theme(new)
        if new != old:
            path.write_text(new, encoding='utf-8')
    icon_assets(source, app)
