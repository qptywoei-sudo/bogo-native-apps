"""Exact installer backdrop overlays; owner icon drawing is left unchanged."""
from pathlib import Path

COLORS = {'ui': ('#f5f5f5', '#0d99ff'), 'photo': ('#efe9dc', '#2f7bf5'),
          'vector': ('#efe9dc', '#e8573f')}
APPS = set(COLORS) | {'launcher', 'light'}


def once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Unreviewed installer artwork contract: ' + before[:110])
    return text.replace(before, after, 1)


def transform_packaging_source(source, app):
    if app == 'pdf':
        path = Path(source) / 'packaging/windows/test-msi.ps1'
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing regular PDF MSI publisher test source')
        before = b"Assert-Equal $manufacturer[0] 'KIO' 'MSI manufacturer'"
        after = b"Assert-Equal $manufacturer[0] 'Bogo' 'MSI manufacturer'"
        data = path.read_bytes()
        if data.splitlines().count(before) != 1 or data.count(before) != 1:
            raise ValueError('Unreviewed PDF MSI publisher assertion contract')
        # The original evaluator, scope cases, registry keys and legacy shortcut
        # fixtures remain byte-exact; only its displayed publisher expectation changes.
        path.write_bytes(data.replace(before, after, 1))
        return ['packaging/windows/test-msi.ps1']
    if app not in APPS:
        return []
    path = Path(source) / 'packaging/windows/package.ps1'
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing regular installer packaging source')
    text = path.read_text(encoding='utf-8')
    if app == 'light':
        text = once(text,
            'New-PanelBitmap $UiDialogBmp 493 312 164 ([byte[]](0x4E, 0x7B, 0xFB)) ([byte[]](0xFF, 0xFF, 0xFF))',
            'New-PanelBitmap $UiDialogBmp 493 312 164 ([byte[]](0xFF, 0xF3, 0xE8)) ([byte[]](0xFF, 0xFA, 0xF6))')
        text = once(text,
            'New-PanelBitmap $UiBannerBmp 493 58 0 ([byte[]](0xFF, 0xFF, 0xFF)) ([byte[]](0xFF, 0xFF, 0xFF))',
            'New-PanelBitmap $UiBannerBmp 493 58 0 ([byte[]](0xFF, 0xF3, 0xE8)) ([byte[]](0xFF, 0xF3, 0xE8))')
    else:
        start = text.index('function New-InstallerArt(')
        end = text.index('\n}', start) + 2
        block = text[start:end]
        if app == 'launcher':
            replacements = [
                ("$ink = [System.Drawing.ColorTranslator]::FromHtml('#121316')", "$ink = [System.Drawing.ColorTranslator]::FromHtml('#FFF3E8')"),
                ("$accent = [System.Drawing.ColorTranslator]::FromHtml('#2d81ff')", "$accent = [System.Drawing.ColorTranslator]::FromHtml('#FC7501')"),
                ('$muted = [System.Drawing.Color]::FromArgb(153, 242, 241, 238)', "$muted = [System.Drawing.ColorTranslator]::FromHtml('#342B26')"),
                ('$line = [System.Drawing.Color]::FromArgb(38, 242, 241, 238)', "$line = [System.Drawing.ColorTranslator]::FromHtml('#F1D3BD')"),
            ]
        else:
            paper, accent = COLORS[app]
            replacements = [
                (f"$paper = [System.Drawing.ColorTranslator]::FromHtml('{paper}')", "$paper = [System.Drawing.ColorTranslator]::FromHtml('#FFF3E8')"),
                (f"$accent = [System.Drawing.ColorTranslator]::FromHtml('{accent}')", "$accent = [System.Drawing.ColorTranslator]::FromHtml('#FC7501')"),
            ]
        replacements.append(('$g.Clear([System.Drawing.Color]::White)', "$g.Clear([System.Drawing.ColorTranslator]::FromHtml('#FFFAF6'))"))
        for before, after in replacements:
            block = once(block, before, after)
        text = text[:start] + block + text[end:]
    path.write_text(text, encoding='utf-8')
    return ['packaging/windows/package.ps1']
