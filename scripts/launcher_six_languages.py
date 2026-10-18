#!/usr/bin/env python3
"""Reproduce KIO-authored Launcher catalogs without network or machine translation."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'patches/launcher'
ALIASES = [28, 29, 30, 31, 49, 52, 53, 48, 23, 208, 54, 57, 32, 60, 56, 3, 81, 5, 6, 9, 174, 10, 11, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 4, None, 68, 69, 71, 75, 76, 77, 80]
AUTO_CHECK = ['Tự động kiểm tra bản cập nhật', '업데이트 자동 확인', '自動檢查更新']
FONT_NOTE = 'No font for this language was found on this system. Install a font for this language and restart KIO Launcher.'
NOTES = ['Không tìm thấy phông chữ cho ngôn ngữ này trên hệ thống. Hãy cài phông chữ phù hợp rồi khởi động lại KIO Launcher.', '시스템에서 이 언어의 글꼴을 찾을 수 없습니다. 해당 언어의 글꼴을 설치한 후 KIO Launcher를 다시 시작하세요.', '系統找不到此語言適用的字型。請安裝適用字型，然後重新啟動 KIO Launcher。']


def write_catalogs(source):
    keys = json.loads((DATA / 'six-language-keys.json').read_text())
    if len(keys) != 307 or keys[259] != ['@id', 'app.install']:
        raise ValueError('Translation key order changed')
    translations = {}
    for line in (DATA / 'six-language-translations.tsv').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 4 or int(fields[0]) in translations:
            raise ValueError('Duplicate or malformed authored translation')
        translations[int(fields[0])] = fields[1:]
    for index, target in enumerate(ALIASES, 259):
        translations[index] = translations[target] if target is not None else AUTO_CHECK
    if set(translations) != set(range(len(keys))):
        raise ValueError('Missing authored translations')
    folder = source / 'crates/ui-egui/src/i18n'
    for column, lang in enumerate(('vi', 'ko', 'zh-TW')):
        lines = ['# KIO original translations. MIT. context<TAB>source<TAB>translation.', '# Official product names, URLs and file extensions are preserved.']
        for index, (context, english) in enumerate(keys):
            lines.append('\t'.join((context, english, translations[index][column])))
        lines.append('\t'.join(('', FONT_NOTE, NOTES[column])))
        (folder / (lang + '.tsv')).write_text('\n'.join(lines) + '\n')
    additions = {
        'ja': {0: 'ランチャー', 25: 'クラシック'},
        'zh-CN': {0: '启动器', 16: '灵感来源', 168: '无法打开 {name}：{e}', 197: '类似 {name}', 207: '网站（即将推出）', 284: '灵感来源'},
    }
    other_notes = {
        'ru': 'В системе не найден шрифт для этого языка. Установите подходящий шрифт и перезапустите KIO Launcher.',
        'fr': 'Aucune police pour cette langue n’a été trouvée sur ce système. Installez une police adaptée, puis redémarrez KIO Launcher.',
        'de': 'Auf diesem System wurde keine Schrift für diese Sprache gefunden. Installieren Sie eine passende Schrift und starten Sie KIO Launcher neu.',
        'pl': 'W systemie nie znaleziono czcionki dla tego języka. Zainstaluj odpowiednią czcionkę i uruchom ponownie KIO Launcher.',
        'hu': 'A rendszer nem talált betűtípust ehhez a nyelvhez. Telepítsen megfelelő betűtípust, majd indítsa újra a KIO Launcher alkalmazást.',
        'es': 'No se encontró ninguna fuente para este idioma en el sistema. Instale una fuente adecuada y reinicie KIO Launcher.',
        'pt-BR': 'Nenhuma fonte para este idioma foi encontrada no sistema. Instale uma fonte adequada e reinicie o KIO Launcher.',
        'cs': 'V systému nebylo nalezeno písmo pro tento jazyk. Nainstalujte vhodné písmo a restartujte KIO Launcher.',
    }
    for lang, rows in {**{code: {} for code in other_notes}, **additions}.items():
        p = folder / (lang + '.tsv')
        content = p.read_text()
        present = {tuple(l.split('\t')[:2]) for l in content.splitlines() if l and not l.startswith('#')}
        for index, value in rows.items():
            if tuple(keys[index]) in present:
                lines = content.splitlines()
                prefix = '\t'.join(keys[index]) + '\t'
                content = '\n'.join(prefix + value if line.startswith(prefix) else line for line in lines) + '\n'
            else:
                content += '\t'.join((*keys[index], value)) + '\n'
        note = other_notes.get(lang) or ('この言語に対応するフォントがシステムに見つかりません。対応するフォントをインストールして、KIO Launcherを再起動してください。' if lang == 'ja' else '系统找不到此语言适用的字体。请安装适用字体，然后重新启动 KIO Launcher。')
        if ('', FONT_NOTE) not in present:
            content += '\t'.join(('', FONT_NOTE, note)) + '\n'
        p.write_text(content)
    # English has no runtime lookup file; this file supports exact key/variable audits.
    english = []
    for index, (context, value) in enumerate(keys):
        label = value
        if context == '@id':
            target = ALIASES[index - 259]
            label = keys[target][1] if target is not None else 'Check for updates automatically'
        english.append('\t'.join((context, value, label)))
    english.append('\t'.join(('', FONT_NOTE, FONT_NOTE)))
    (folder / 'en.tsv').write_text('# English source messages. MIT.\n' + '\n'.join(english) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    write_catalogs(args.source)
