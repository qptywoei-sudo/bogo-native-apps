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
TECHNICAL = re.compile(r'(?i)ProjectDirs|\.join\(|PathBuf::|Path::|(?:storage_dir|storage_path|preferences_dir|settings_dir|data_local_dir|cache_dir|config_dir)\s*\(|(?<![A-Za-z0-9])[A-Za-z]:[\\/]|Software\\|HKEY_|PORTABLE_MARKERS|PORTABLE_DATA_DIR|(?:DATA|PROFILE|CONFIG)_DIR|registry_key|former_names|legacy_name')


def display(text):
    text = re.sub(r'KIO (CAD|Cad|Design|Vector|Film|Light|PDF|Effect|UI|Word|Sound|Deck|Grid|Launcher|Photo)', lambda m: 'Bogo ' + ('CAD' if m[1] == 'Cad' else m[1]), text)
    return text.replace('Independent KIO fork', 'Independent Bogo fork').replace('KIO branding', 'Bogo branding').replace('KIO Apps', 'Bogo Apps').replace('KIO apps', 'Bogo apps').replace('KIO Work', 'Bogo Work').replace('KIO App Suite', 'Bogo App Suite')


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
    background = {'bg', 'app_bg', 'window', 'window_bg', 'panel', 'panel_bg', 'panel_bg2', 'panel_darker', 'dock', 'card', 'button', 'field', 'field_bg', 'input_bg', 'input', 'menu_bg', 'sunken', 'inset', 'toolbar_group', 'tab_inactive', 'tab_active', 'tab_bar_bg', 'strip_bg', 'strip_section', 'cmd_bg', 'chrome_dark', 'row', 'row_alt', 'switch_well', 'cell'}
    hover = {'hover', 'pressed', 'checked', 'selection', 'row_selected', 'tool_active', 'cell_selected', 'header_sel_bg', 'header_all_bg', 'tab_selected', 'accent_soft', 'button_hi', 'well', 'name_field_sel', 'header_selected', 'strip_selected', 'control_hover', 'cmd_keyword_hover'}
    border = {'border', 'border_strong', 'border_light', 'ribbon_border', 'divider', 'separator', 'line', 'line_strong', 'field_border', 'input_border', 'button_border', 'card_border', 'section_divider', 'header_line', 'well_rim', 'control_border', 'group_border'}
    text_fields = {'text', 'text_strong', 'text_dim', 'text_secondary', 'text_tertiary', 'text_faint', 'text_muted', 'text_disabled', 'ink', 'ink_strong', 'muted', 'faint', 'icon', 'header_text', 'tab_text', 'tab_text_active', 'accent_text', 'accent_ink', 'accent_dark', 'accent_strong', 'primary_text', 'invert_fg', 'on_accent', 'group_label', 'header_sel_text', 'text_label', 'section_label'}
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
    text = re.sub(r'(^\s*)(\w+):\s*((?:Color32::\w+(?:\([^\n]*?\))?|hex\([^\n]*?\)|rgb\([^\n]*?\)|ink_alpha\([^\n]*?\))),', field, text, flags=re.M)
    for name in brand:
        colour = 'Color32::from_rgb(0x34, 0x2B, 0x26)' if name == 'APP_INK' else 'Color32::from_rgb(0xFC, 0x75, 0x01)'
        text = re.sub(r'(pub const ' + name + r': Color32 = )[^;\n]+;', r'\g<1>' + colour + ';', text)
    text = re.sub(r'(^\s*slot_face:)\s*\[[^\n]+\],', r'\g<1> [Color32::from_rgb(0xFF, 0xFA, 0xF6); 2],', text, flags=re.M)
    # egui uses selection.stroke as the foreground of selected tab labels too.
    # Keep official orange for artwork/fills; small chrome links and labels need dark ink.
    dark_accent = 'Color32::from_rgb(0x93, 0x44, 0x00)'
    text = re.sub(r'(\.hyperlink_color\s*=\s*)(?:[a-z_]+\.accent|APP_COLOR|ACCENT)(\s*;)', r'\g<1>' + dark_accent + r'\g<2>', text)
    text = re.sub(r'(\.selection\.stroke\s*=\s*(?:egui::)?Stroke::new\([^,\n]+,\s*)(?:[a-z_]+\.accent|APP_COLOR|ACCENT)(\s*\);)', r'\g<1>' + dark_accent + r'\g<2>', text)
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
    if app == 'launcher':
        sibling_icons = source / 'assets/app-icons'
        names = {('figcraft' if item == 'ui' else item + 'craft'): item for item in NAMES if item != 'launcher'}
        if {p.stem for p in sibling_icons.glob('*.png')} != set(names):
            raise ValueError('Launcher sibling icon inventory differs from the 13 full native editors')
        originals_by_id = {r[0]['id']: r[1] for r in originals()}
        for stem, item in names.items():
            # These embedded Launcher tiles are already 1024 px: retain every original byte.
            shutil.copyfile(originals_by_id[item], sibling_icons / (stem + '.png'))


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
        if not allowed or path.suffix.lower() not in ('.rs', '.json', '.po', '.ftl', '.xml', '.in', '.wxs', '.wxl', '.ps1', '.sh', '.html', '.desktop', '.toml', '.tsv'):
            continue
        try:
            old = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        if relative.startswith('packaging/') and path.suffix in ('.wxs', '.wxl', '.xml'):
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
        if relative.startswith('crates/ui-egui/') and path.suffix == '.rs':
            foreground = 'ink' if app == 'launcher' else 'text'
            new = re.sub(r'\.color\((t|tokens)\.accent\)', lambda m: '.color(' + m[1] + '.' + foreground + ')', new)
        if app == 'grid':
            if relative == 'crates/ui-egui/src/ribbon.rs':
                new = new.replace('frame(egui::Frame::NONE.fill(t.window))', 'frame(egui::Frame::NONE.fill(t.header_bg))')
            elif relative == 'crates/ui-egui/src/tabs.rs':
                new = new.replace('&name, font, if active { t.accent } else { t.text }', '&name, font, t.text')
            elif relative == 'crates/ui-egui/src/lib.rs':
                new = new.replace('egui::ViewportCommand::Title(title.clone())', 'egui::ViewportCommand::Title(format!("{title} — Bogo Grid"))')
        elif app == 'light' and relative == 'apps/lightcraft/src/main.rs':
            new = new.replace('.with_title("LightCraft")', '.with_title("Bogo Light")').replace('eframe::run_native(\n            "LightCraft",', 'eframe::run_native(\n            "Bogo Light",')
        elif app == 'light' and relative == 'crates/ui-egui/src/panels/grid.rs':
            new = new.replace('rect_filled(hr, 0.0, t.canvas)', 'rect_filled(hr, 0.0, t.chrome)').replace('rect_filled(r, 0.0, t.canvas)', 'rect_filled(r, 0.0, t.chrome)').replace('let header = egui::Frame::NONE.fill(t.canvas)', 'let header = egui::Frame::NONE.fill(t.chrome)')
        elif app == 'design' and relative == 'crates/ui-egui/src/lib.rs':
            new = new.replace('format!("{} — 2", d.doc.title)', 'format!("{} — 2 — Bogo Design", d.doc.title)')
        elif app == 'photo' and relative == 'crates/ui-egui/src/canvas.rs':
            new = new.replace('format!("{} — window {}", st.doc.name, w.id)', 'format!("{} — window {} — Bogo Photo", st.doc.name, w.id)')
        elif app == 'deck' and relative == 'crates/ui-egui/src/status.rs':
            new = new.replace('&msg, theme::font(12.0), t.accent', '&msg, theme::font(12.0), t.text')
        elif app == 'word' and relative in ('crates/ui-egui/src/chrome.rs', 'crates/ui-egui/src/ribbon.rs'):
            new = new.replace('if resp.hovered() { t.accent_text } else { t.accent }', 'if resp.hovered() { t.hover } else { t.accent }')
        elif app == 'word' and relative == 'crates/ui-egui/src/theme.rs':
            # Preserve the upstream real-token contrast regression for the new hover fill.
            new = new.replace('("hover", t.accent_text)', '("hover", t.hover)')
        elif app == 'effect' and relative == 'crates/ui-egui/src/panels/properties.rs':
            new = new.replace('Tokens::ui(12.0), if resp.hovered() { t.accent_hover } else { t.accent }', 'Tokens::ui(12.0), t.text')
        elif app == 'effect' and relative == 'crates/ui-egui/src/panels/timeline.rs':
            new = new.replace('crate::i18n::tr("Change Renderer…"), Tokens::ui(11.5), t.accent', 'crate::i18n::tr("Change Renderer…"), Tokens::ui(11.5), t.text')
        elif app == 'sound' and relative == 'crates/ui-egui/src/toolbar.rs':
            new = new.replace('"triangle_down", t.text_dim', '"triangle_down", t.counter_label').replace('format!("{st} · {dev}"), regular(10.0), t.text_dim', 'format!("{st} · {dev}"), regular(10.0), t.counter_label')
        elif app == 'launcher' and relative == 'crates/ui-egui/src/views.rs':
            new = new.replace('.alt_text(tl!("ArtCraft"))', '.alt_text("Bogo")')
        if new != old:
            path.write_text(new, encoding='utf-8')
    icon_assets(source, app)
