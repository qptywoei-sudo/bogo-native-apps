"""Exact reviewed chrome fixes found in real installed Bogo screenshots.

Document/media colors and interaction logic remain outside these replacements.
Unknown upstream declarations fail rather than accepting a broad color rewrite.
"""


def replace_exact(text, replacements):
    for before, after, count in replacements:
        if text.count(before) != count:
            raise ValueError('Unreviewed Bogo chrome contrast source contract: ' + before[:100])
        text = text.replace(before, after)
    return text


LIGHT_LABEL_BEFORE = '            p.rect_filled(cr, 0.0, crate::theme::label_background(base, label, selected));'
LIGHT_LABEL_AFTER = '''            let label_background = crate::theme::label_background(base, label, selected);
            let label_ink = crate::theme::readable_ink(label_background, t.text_dim);
            p.rect_filled(cr, 0.0, label_background);'''



def previous_replacements(app, relative):
    if app == 'light' and relative == 'crates/ui-egui/src/docking.rs':
        return [('style.active_background = t.canvas;', 'style.active_background = t.hover;', 1)]
    if app == 'light' and relative == 'crates/ui-egui/src/panels/detail.rs':
        return [(LIGHT_LABEL_BEFORE, LIGHT_LABEL_AFTER, 1),
                ('film_label(name), t.font(10.0), t.text_dim);', 'film_label(name), t.font(10.0), label_ink);', 1),
                ('&ph.format, t.semibold(8.5), t.text_dim);', '&ph.format, t.semibold(8.5), label_ink);', 1)]
    if app == 'light' and relative == 'crates/ui-egui/src/panels/bottombar.rs':
        return [
            ('ui.painter().rect_filled(pill, 15.0, t.canvas);', 'ui.painter().rect_filled(pill, 15.0, t.button);', 1),
            ('ui.painter().rect_filled(copy_r, 15.0, if cresp.hovered() { t.hover } else { t.canvas });',
             'ui.painter().rect_filled(copy_r, 15.0, if cresp.hovered() { t.hover } else { t.button });', 1),
            ('ui.painter().rect_filled(gear_r, 15.0, if gresp.hovered() { t.hover } else { t.canvas });',
             'ui.painter().rect_filled(gear_r, 15.0, if gresp.hovered() { t.hover } else { t.button });', 1),
            ('''        let on = flag == f && f != Flag::None;
        let c = if on {
            if f == Flag::Reject { t.reject } else { t.pick }''', '''        let on = flag == f && f != Flag::None;
        if on {
            pill_ui.painter().rect_filled(r, 4.0, t.pressed);
        }
        let c = if on {
            if f == Flag::Reject { t.reject } else { t.text }''', 1),
        ]
    if app == 'light' and relative == 'crates/ui-egui/src/widgets.rs':
        return [('if filled { t.star } else { t.icon });', 't.icon);', 1)]
    if app == 'ui' and relative == 'crates/ui-egui/src/theme.rs':
        pale = 'Color32::from_rgb(0xFF, 0xE7, 0xD4)'
        return [(before, after, 1) for before, after in (
            ('accent_hover: Color32::from_rgb(0x00, 0x7B, 0xE5),', 'accent_hover: ' + pale + ','),
            ('accent_hover: Color32::from_rgb(0x3D, 0xAD, 0xFF),', 'accent_hover: ' + pale + ','),
            ('selected_row: Color32::from_rgb(0xE5, 0xF4, 0xFF),', 'selected_row: ' + pale + ','),
            ('selected_row_child: Color32::from_rgb(0xF2, 0xF9, 0xFF),', 'selected_row_child: ' + pale + ','),
            ('selected_row: Color32::from_rgb(0x2A, 0x45, 0x5C),', 'selected_row: ' + pale + ','),
            ('selected_row_child: Color32::from_rgb(0x2D, 0x37, 0x41),', 'selected_row_child: ' + pale + ','),
        )]
    if app == 'deck' and relative == 'crates/ui-egui/src/backstage.rs':
        return [('''    if resp.hovered() {
        p.rect_filled(row, CornerRadius::same(2), t.hover);
    }''', '''    if selected || resp.hovered() {
        p.rect_filled(row, CornerRadius::same(2), t.hover);
    }''', 1), ('let ink = if selected { t.accent } else { t.text };', 'let ink = t.text;', 1)]
    if app == 'word' and relative == 'crates/ui-egui/src/backstage.rs':
        return [
            ('use crate::theme::{APP_COLOR, Tokens, medium, regular, semibold};', 'use crate::theme::{Tokens, medium, regular, semibold};', 1),
            ('.frame(egui::Frame::NONE.fill(APP_COLOR).inner_margin', '.frame(egui::Frame::NONE.fill(t.title_bar).inner_margin', 1),
            ('"chevronLeft", egui::Color32::WHITE, egui::Color32::WHITE);', '"chevronLeft", t.text, t.text);', 1),
            ('''                    "chevronLeft",
                    egui::Color32::WHITE,
                    egui::Color32::WHITE,''', '''                    "chevronLeft",
                    t.text,
                    t.text,''', 1),
            ('ui.painter().rect_filled(r, 0.0, egui::Color32::from_white_alpha(46));', 'ui.painter().rect_filled(r, 0.0, t.checked);', 1),
            ('ui.painter().rect_filled(r, 0.0, egui::Color32::from_white_alpha(26));', 'ui.painter().rect_filled(r, 0.0, t.hover);', 2),
            ('if on { egui::Color32::WHITE } else { egui::Color32::from_white_alpha(110) },', 'if on { t.text } else { t.text.gamma_multiply(0.45) },', 1),
            ('tl!(label), regular(13.0), egui::Color32::WHITE);', 'tl!(label), regular(13.0), t.text);', 1),
        ]
    if app == 'sound' and relative == 'crates/ui-egui/src/panels.rs':
        return [('egui::TextEdit::singleline(&mut filter).hint_text("🔍 Find clips").desired_width(f32::INFINITY)',
                 'egui::TextEdit::singleline(&mut filter).background_color(t.panel_bg2).text_color(t.text).hint_text(egui::RichText::new("🔍 Find clips").color(t.text)).desired_width(f32::INFINITY)', 1)]
    if app == 'sound' and relative == 'crates/ui-egui/src/widgets.rs':
        return [('let style = button_style(t.accent, t.text, 3);',
                 'let mut style = button_style(t.button_hi, t.text, 3);\n    style.selected.icon = t.text;', 1),
                ('/// A toolbar button with an icon; `on` draws the blue selected state.',
                 '/// A toolbar button with an icon; `on` draws the pale orange selected state.', 1)]
    if app == 'effect' and relative == 'crates/ui-egui/src/widgets.rs':
        return [
            ('ui.painter().rect_filled(rect, 4.0, t.accent);', 'ui.painter().rect_filled(rect, 4.0, t.hover);', 1),
            ('let col = if active {\n        Color32::WHITE', 'let col = if active {\n        t.text', 1),
            ('if resp.hovered() { t.accent_hover } else { t.accent }', 'if resp.hovered() { t.pressed } else { t.hover }', 1),
            ('Tokens::medium(12.0), if primary { Color32::WHITE } else { t.text });', 'Tokens::medium(12.0), t.text);', 1),
            ('ui.painter().rect_filled(b, 2.0, if on { t.accent } else { t.field_bg });', 'ui.painter().rect_filled(b, 2.0, if on { t.hover } else { t.field_bg });', 1),
            ('Stroke::new(1.6, Color32::WHITE)', 'Stroke::new(1.6, t.text)', 1),
        ]
    if app == 'effect' and relative == 'crates/ui-egui/src/theme.rs':
        return [('v.selection.bg_fill = t.accent;', 'v.selection.bg_fill = t.hover;', 1),
                ('v.selection.stroke = Stroke::new(1.0, Color32::WHITE);', 'v.selection.stroke = Stroke::new(1.0, t.text);', 1)]
    if app == 'effect' and relative == 'crates/ui-egui/src/header.rs':
        return [('let col = if active {\n            t.hot_text', 'let col = if active {\n            t.text', 1),
                ('        p.galley_with_override_text_color(pos2(r.min.x + 8.0, cy - g.size().y / 2.0), g, col);',
                 '        if active || resp.hovered() {\n            p.rect_filled(r, 2.0, t.hover);\n        }\n        p.galley_with_override_text_color(pos2(r.min.x + 8.0, cy - g.size().y / 2.0), g, col);', 1),
                ('Stroke::new(2.0, t.hot_text));', 'Stroke::new(2.0, t.accent));', 1)]
    if app == 'effect' and relative == 'crates/ui-egui/src/panels/viewer.rs':
        return [('crate::i18n::tr("Composition"), Tokens::semibold(16.0), t.text);',
                 'crate::i18n::tr("Composition"), Tokens::semibold(16.0), if t.kind.is_light() { t.text } else { egui::Color32::from_gray(244) });', 1)]
    if app == 'photo' and relative == 'crates/ui-egui/src/canvas.rs':
        return [('''fn start_screen(app: &mut PhotocraftApp, ui: &mut egui::Ui) {
    let t = crate::theme::Tokens::get(ui.ctx());
    let area = ui.available_rect_before_wrap();''', '''fn start_screen(app: &mut PhotocraftApp, ui: &mut egui::Ui) {
    let t = crate::theme::Tokens::get(ui.ctx());
    let area = ui.available_rect_before_wrap();
    // Home is application chrome; actual document pasteboards retain their
    // existing preferences and media colors in the separate canvas path.
    ui.painter().rect_filled(area, 0.0, t.card);''', 1)]
    if app == 'photo' and relative == 'crates/ui-egui/src/icons.rs':
        return [('egui::Stroke::new(1.0, t.accent_border)', 'egui::Stroke::new(1.0, t.field_border)', 2)]
    return []


LIGHT_ROLE_REPLACEMENTS = {'crates/ui-egui/src/theme.rs': [('#[derive(Clone, Copy, Debug)]\npub struct Tokens {',
                                  '/// UI ink for an actual opaque surface. Photo, histogram and mask colors stay unchanged.\n'
                                  'pub fn readable_ink(background: Color32, preferred: Color32) -> Color32 {\n'
                                  '    let luminance = |color: Color32| {\n'
                                  '        let linear = |value: u8| {\n'
                                  '            let c = f32::from(value) / 255.0;\n'
                                  '            if c <= 0.04045 { c / 12.92 } else { ((c + 0.055) / 1.055).powf(2.4) }\n'
                                  '        };\n'
                                  '        0.2126 * linear(color.r()) + 0.7152 * linear(color.g()) + 0.0722 * linear(color.b())\n'
                                  '    };\n'
                                  '    let background = luminance(background);\n'
                                  '    let preferred_luminance = luminance(preferred);\n'
                                  '    let contrast = (background.max(preferred_luminance) + 0.05) / (background.min(preferred_luminance) + '
                                  '0.05);\n'
                                  '    if contrast >= 4.5 { preferred }\n'
                                  '    else if 1.05 / (background + 0.05) >= 4.5 { Color32::WHITE }\n'
                                  '    else { Color32::BLACK }\n'
                                  '}\n'
                                  '\n'
                                  '/// A readable annotation on arbitrary media, preserving its existing text anchor and font.\n'
                                  'pub fn media_label(p: &egui::Painter, position: egui::Pos2, align: egui::Align2, text: impl Into<String>, '
                                  'font: egui::FontId) -> egui::Rect {\n'
                                  '    let galley = p.layout_no_wrap(text.into(), font, Color32::WHITE);\n'
                                  '    let rect = align.anchor_size(position, galley.size());\n'
                                  '    p.rect_filled(rect.expand2(egui::vec2(3.0, 2.0)), 3.0, Color32::from_black_alpha(220));\n'
                                  '    p.galley(rect.min, galley, Color32::WHITE);\n'
                                  '    rect\n'
                                  '}\n'
                                  '\n'
                                  '#[derive(Clone, Copy, Debug)]\n'
                                  'pub struct Tokens {',
                                  1),
                                 ('v.selection.bg_fill = t.accent.gamma_multiply(0.6);', 'v.selection.bg_fill = t.pressed;', 1),
                                 ('let (popup, window) = if dark { (140, 160) } else { (50, 60) };', 'let (popup, window) = (24, 30);', 1)],
 'crates/ui-egui/src/widgets.rs': [('pub fn preview_only_notice(ui: &mut Ui, key: &str, reason: &str) {\n'
                                    '    let t = Tokens::get(ui.ctx());\n'
                                    '    let r = egui::Frame::NONE\n'
                                    '        .fill(t.canvas)',
                                    'pub fn preview_only_notice(ui: &mut Ui, key: &str, reason: &str) {\n'
                                    '    let t = Tokens::get(ui.ctx());\n'
                                    '    let r = egui::Frame::NONE\n'
                                    '        .fill(t.button)',
                                    1),
                                   ('    } else if active {\n        t.pick', '    } else if active {\n        t.icon', 1)],
 'crates/ui-egui/src/panels/topbar.rs': [('if focused { t.canvas } else { t.field },', 't.field,', 1),
                                         ('            let filtering = app.session.filter != Default::default() || app.ui.filter_bar;\n'
                                          '            paint(',
                                          '            let filtering = app.session.filter != Default::default() || app.ui.filter_bar;\n'
                                          '            if filtering {\n'
                                          '                ui.painter().rect_filled(fr, 4.0, t.pressed);\n'
                                          '            }\n'
                                          '            paint(',
                                          1),
                                         ('                if filtering {\n                    t.accent',
                                          '                if filtering {\n                    t.text',
                                          1),
                                         ('active.to_string(), t.semibold(9.5), t.canvas);',
                                          'active.to_string(), t.semibold(9.5), crate::theme::readable_ink(t.accent, t.text));',
                                          1),
                                         ('"!", t.semibold(9.5), t.canvas);',
                                          '"!", t.semibold(9.5), crate::theme::readable_ink(t.reject, t.text));',
                                          1)],
 'crates/ui-egui/src/panels/filterbar.rs': [('        let c = if filled {\n            t.star',
                                             '        let c = if filled {\n            t.icon',
                                             1),
                                            ('Flag::Pick if on => t.pick,', 'Flag::Pick if on => t.text,', 1)],
 'crates/ui-egui/src/panels/presets.rs': [('Icon::StarFilled, t.star);', 'Icon::StarFilled, t.icon);', 1)],
 'crates/ui-egui/src/panels/profiles.rs': [('Stroke::new(2.0, t.pick)', 'Stroke::new(2.0, t.accent)', 1),
                                           ('if fav || over_star { t.star } else { Color32::WHITE }', 'Color32::WHITE', 1)],
 'crates/ui-egui/src/panels/right.rs': [('egui::Frame::NONE.fill(t.canvas).corner_radius(6.0).inner_margin',
                                         'egui::Frame::NONE.fill(t.button).corner_radius(6.0).inner_margin',
                                         1),
                                        ('if online { t.text_dim } else { t.accent }', 'if online { t.text_dim } else { t.text }', 1),
                                        ('Icon::Check, t.accent);', 'Icon::Check, t.icon);', 1)],
 'crates/ui-egui/src/panels/left.rs': [('ui.painter().rect_filled(inner, 4.0, t.canvas);',
                                        'ui.painter().rect_filled(inner, 4.0, t.pressed);',
                                        1),
                                       ('egui::Frame::NONE.fill(t.accent).corner_radius(10.0)',
                                        'egui::Frame::NONE.fill(t.pressed).corner_radius(10.0)',
                                        2),
                                       ('.color(egui::Color32::WHITE).font(t.semibold(12.0))', '.color(t.text).font(t.semibold(12.0))', 2)],
 'crates/ui-egui/src/panels/keyword_list.rs': [('ui.painter().rect_filled(inner, 4.0, t.canvas);',
                                                'ui.painter().rect_filled(inner, 4.0, t.pressed);',
                                                1),
                                               ('egui::Frame::NONE.fill(t.accent).corner_radius(10.0)',
                                                'egui::Frame::NONE.fill(t.pressed).corner_radius(10.0)',
                                                1),
                                               ('.color(Color32::WHITE).font(t.semibold(12.0))', '.color(t.text).font(t.semibold(12.0))', 1),
                                               ('ui.painter().rect_filled(boxr, 2.0, t.accent);',
                                                'ui.painter().rect_filled(boxr, 2.0, t.pressed);',
                                                1),
                                               ('egui::Shape::line(pts, Stroke::new(1.6, Color32::WHITE))',
                                                'egui::Shape::line(pts, Stroke::new(1.6, t.text))',
                                                1)],
 'crates/ui-egui/src/panels/chips.rs': [('ui.painter().rect_filled(bar, 0.0, t.canvas);', 'ui.painter().rect_filled(bar, 0.0, t.chrome);', 1)],
 'crates/ui-egui/src/panels/mod.rs': [('unwrap_or((egui::Color32::from_black_alpha(200), t.text))', 'unwrap_or((t.button, t.text))', 1),
                                      ('pub fn empty_message(ui: &egui::Ui, rect: Rect, title: &str, body: &str) {\n'
                                       '    let t = Tokens::get(ui.ctx());\n'
                                       '    let p = ui.painter();\n'
                                       '    p.text(rect.center() - vec2(0.0, 12.0), Align2::CENTER_CENTER, crate::i18n::tr(title), '
                                       't.semibold(18.0), t.text_label);\n'
                                       '    p.text(rect.center() + vec2(0.0, 14.0), Align2::CENTER_CENTER, crate::i18n::tr(body), t.font(13.0), '
                                       't.text_dim);\n'
                                       '}',
                                       'pub fn empty_message(ui: &egui::Ui, rect: Rect, title: &str, body: &str) {\n'
                                       '    let t = Tokens::get(ui.ctx());\n'
                                       '    empty_message_on(ui, rect, title, body, t.chrome);\n'
                                       '}\n'
                                       '\n'
                                       '/// The caller supplies the real canvas or chrome surface; its colors are not changed.\n'
                                       'pub fn empty_message_on(ui: &egui::Ui, rect: Rect, title: &str, body: &str, background: egui::Color32) '
                                       '{\n'
                                       '    let t = Tokens::get(ui.ctx());\n'
                                       '    let p = ui.painter();\n'
                                       '    p.text(rect.center() - vec2(0.0, 12.0), Align2::CENTER_CENTER, crate::i18n::tr(title), '
                                       't.semibold(18.0), crate::theme::readable_ink(background, t.text_label));\n'
                                       '    p.text(rect.center() + vec2(0.0, 14.0), Align2::CENTER_CENTER, crate::i18n::tr(body), t.font(13.0), '
                                       'crate::theme::readable_ink(background, t.text_dim));\n'
                                       '}',
                                       1)],
 'crates/ui-egui/src/panels/grid.rs': [('    let g = p.layout_no_wrap(crate::i18n::date_group_label(&run.key, false), t.semibold(15.0), if '
                                        'resp.hovered() { t.text } else { t.text_label });',
                                        '    let ink = crate::theme::readable_ink(if pinned { t.chrome } else { t.grid_bg }, t.text);\n'
                                        '    let g = p.layout_no_wrap(crate::i18n::date_group_label(&run.key, false), t.semibold(15.0), ink);',
                                        1),
                                       ('p.galley(pos2(x, r.center().y - g.size().y / 2.0), g, t.text);',
                                        'p.galley(pos2(x, r.center().y - g.size().y / 2.0), g, ink);',
                                        1),
                                       ('        crate::i18n::tr_format!("· {n} photo{}", if n == 1 { "" } else { "s" }, n = n),\n'
                                        '        t.font(12.5),\n'
                                        '        t.text_dim,',
                                        '        crate::i18n::tr_format!("· {n} photo{}", if n == 1 { "" } else { "s" }, n = n),\n'
                                        '        t.font(12.5),\n'
                                        '        ink,',
                                        1),
                                       ('"!", t.semibold(18.0), t.text_dim);', '"!", t.semibold(18.0), Color32::WHITE);', 1),
                                       ('layout_no_wrap(fmt, t.semibold(9.0), t.text_label)',
                                        'layout_no_wrap(fmt, t.semibold(9.0), Color32::WHITE)',
                                        1),
                                       ('p.galley(br.min + vec2(4.0, 1.5), g, t.text_label);',
                                        'p.galley(br.min + vec2(4.0, 1.5), g, Color32::WHITE);',
                                        1),
                                       ('Icon::StarFilled, t.star);', 'Icon::StarFilled, Color32::WHITE);', 1),
                                       ('Icon::FlagPick, t.pick),', 'Icon::FlagPick, Color32::WHITE),', 1),
                                       ('Icon::Sliders, t.text_label);', 'Icon::Sliders, Color32::WHITE);', 1),
                                       ('egui::Frame::NONE.fill(t.accent).corner_radius(10.0)',
                                        'egui::Frame::NONE.fill(t.pressed).corner_radius(10.0)',
                                        1),
                                       ('.color(Color32::WHITE)\n                    .font(t.semibold(12.0))',
                                        '.color(t.text)\n                    .font(t.semibold(12.0))',
                                        1),
                                       ('super::empty_message(ui, ui.max_rect(), "No photos match the active filters", &body);',
                                        'super::empty_message_on(ui, ui.max_rect(), "No photos match the active filters", &body, t.grid_bg);',
                                        1),
                                       ('super::empty_message(ui, ui.max_rect(), "No photos in this folder", "Turn on Include subfolders, or '
                                        'pick another folder under Local");',
                                        'super::empty_message_on(ui, ui.max_rect(), "No photos in this folder", "Turn on Include subfolders, or '
                                        'pick another folder under Local", t.grid_bg);',
                                        1),
                                       ('super::empty_message(ui, ui.max_rect(), "No photos", "Import photos with File → Import Photos… '
                                        '(Cmd+Shift+I), or drop them here");',
                                        'super::empty_message_on(ui, ui.max_rect(), "No photos", "Import photos with File → Import Photos… '
                                        '(Cmd+Shift+I), or drop them here", t.grid_bg);',
                                        1),
                                       ('                "A filter is hiding this view\'s photos: change it, or clear it (View → Clear '
                                        'Filters)",\n'
                                        '            );',
                                        '                "A filter is hiding this view\'s photos: change it, or clear it (View → Clear '
                                        'Filters)",\n'
                                        '                t.grid_bg,\n'
                                        '            );',
                                        1),
                                       ('            super::empty_message(\n                ui,\n                ui.max_rect(),',
                                        '            super::empty_message_on(\n                ui,\n                ui.max_rect(),',
                                        1)],
 'crates/ui-egui/src/panels/compare.rs': [('    let pt = ui.painter();\n    let mut x = cap.left() + 4.0;',
                                           '    let pt = ui.painter();\n'
                                           '    let caption_ink = crate::theme::readable_ink(t.canvas, t.text);\n'
                                           '    let mut x = cap.left() + 4.0;',
                                           1),
                                          ('crate::i18n::tr(label).to_string(), t.semibold(12.0), if active { t.text } else { t.text_label }',
                                           'crate::i18n::tr(label).to_string(), t.semibold(12.0), caption_ink',
                                           1),
                                          ('g.clone(), t.text);', 'g.clone(), caption_ink);', 1),
                                          ('layout_no_wrap(name, t.font(11.5), t.text_dim)',
                                           'layout_no_wrap(name, t.font(11.5), caption_ink)',
                                           1),
                                          ('g, t.text_dim);', 'g, caption_ink);', 1),
                                          ('if filled { t.star } else { t.icon.gamma_multiply(0.6) }', 'caption_ink', 1),
                                          ('Icon::FlagPick, t.pick),', 'Icon::FlagPick, caption_ink),', 1),
                                          ('super::empty_message(ui, canvas, "Nothing to compare", "Select two photos, then choose View → '
                                           'Compare (Shift+C)");',
                                           'super::empty_message_on(ui, canvas, "Nothing to compare", "Select two photos, then choose View → '
                                           'Compare (Shift+C)", crate::theme::Tokens::get(ui.ctx()).canvas);',
                                           1),
                                          ('super::empty_message(ui, canvas, "Nothing to survey", "Select photos, then choose View → Survey '
                                           '(N)");',
                                           'super::empty_message_on(ui, canvas, "Nothing to survey", "Select photos, then choose View → Survey '
                                           '(N)", crate::theme::Tokens::get(ui.ctx()).canvas);',
                                           1),
                                          ('super::empty_message(ui, canvas, "No reference photo", "Right-click a photo ▸ Set as Reference '
                                           'Photo, then View → Reference View (Shift+R)");',
                                           'super::empty_message_on(ui, canvas, "No reference photo", "Right-click a photo ▸ Set as Reference '
                                           'Photo, then View → Reference View (Shift+R)", crate::theme::Tokens::get(ui.ctx()).canvas);',
                                           1)],
 'crates/ui-egui/src/panels/detail.rs': [('super::empty_message(ui, canvas, "No photo selected", "Choose a photo in the grid or filmstrip");',
                                          'super::empty_message_on(ui, canvas, "No photo selected", "Choose a photo in the grid or filmstrip", '
                                          'if fullscreen { Color32::BLACK } else { t.canvas });',
                                          1),
                                         ('    let shown;\n    if split {',
                                          '    let canvas_background = if fullscreen { Color32::BLACK } else if app.ui.soft_proof { '
                                          'Color32::from_gray(238) } else { t.canvas };\n'
                                          '    let canvas_ink = crate::theme::readable_ink(canvas_background, t.text);\n'
                                          '    let shown;\n'
                                          '    if split {',
                                          1),
                                         ('p.text(label_at(br, areas[0]), Align2::LEFT_CENTER, crate::i18n::tr("Before"), t.font(12.0), '
                                          't.text_dim);',
                                          'crate::theme::media_label(&p, label_at(br, areas[0]), Align2::LEFT_CENTER, crate::i18n::tr("Before"), '
                                          't.font(12.0));',
                                          1),
                                         ('p.text(label_at(img_rect, main_area), Align2::LEFT_CENTER, crate::i18n::tr("After"), t.font(12.0), '
                                          't.text_dim);',
                                          'crate::theme::media_label(&p, label_at(img_rect, main_area), Align2::LEFT_CENTER, '
                                          'crate::i18n::tr("After"), t.font(12.0));',
                                          1),
                                         ('p.text(pos2(img_rect.left() + 8.0, img_rect.top() + 14.0), Align2::LEFT_CENTER, '
                                          'crate::i18n::tr("Before"), t.font(12.0), t.text);',
                                          'crate::theme::media_label(&p, pos2(img_rect.left() + 8.0, img_rect.top() + 14.0), '
                                          'Align2::LEFT_CENTER, crate::i18n::tr("Before"), t.font(12.0));',
                                          1),
                                         ('                        crate::i18n::tr("This photo can\'t be opened"),\n'
                                          '                        t.semibold(14.0),\n'
                                          '                        t.text,',
                                          '                        crate::i18n::tr("This photo can\'t be opened"),\n'
                                          '                        t.semibold(14.0),\n'
                                          '                        canvas_ink,',
                                          1),
                                         ('e, t.font(12.0), t.text_dim);', 'e, t.font(12.0), canvas_ink);', 1),
                                         ('crate::i18n::tr("Rendering…"), t.font(13.0), t.text_dim);',
                                          'crate::i18n::tr("Rendering…"), t.font(13.0), canvas_ink);',
                                          1),
                                         ('why, t.font(12.5), t.text_dim);',
                                          'why, t.font(12.5), crate::theme::readable_ink(t.canvas, t.text_dim));',
                                          1),
                                         ('Icon::StarFilled, t.star);', 'Icon::StarFilled, Color32::WHITE);', 1),
                                         ('Icon::FlagPick, t.pick),', 'Icon::FlagPick, Color32::WHITE),', 1),
                                         ('Icon::Sliders, t.text_label);', 'Icon::Sliders, Color32::WHITE);', 1)],
 'crates/ui-egui/src/merge.rs': [('                ui.painter().text(\n                    rect.center_bottom()',
                                  '                crate::theme::media_label(\n'
                                  '                    ui.painter(),\n'
                                  '                    rect.center_bottom()',
                                  1),
                                 ('                    crate::i18n::tr_format!("{stage}… {:.0}%", f * 100.0, stage = stage),\n'
                                  '                    t.font(12.0),\n'
                                  '                    t.text,',
                                  '                    crate::i18n::tr_format!("{stage}… {:.0}%", f * 100.0, stage = stage),\n'
                                  '                    t.font(12.0),',
                                  1),
                                 ('ui.painter().text(rect.center(), egui::Align2::CENTER_CENTER, e, t.font(13.0), t.text);',
                                  'crate::theme::media_label(ui.painter(), rect.center(), egui::Align2::CENTER_CENTER, e, t.font(13.0));',
                                  1)],
 'crates/ui-egui/src/panels/people.rs': [('crate::i18n::tr("Named People"), t.semibold(15.0), t.text);',
                                          'crate::i18n::tr("Named People"), t.semibold(15.0), crate::theme::readable_ink(t.grid_bg, t.text));',
                                          1),
                                         ('people.len().to_string(), t.font(13.0), t.text_dim);',
                                          'people.len().to_string(), t.font(13.0), crate::theme::readable_ink(t.grid_bg, t.text_dim));',
                                          1),
                                         ('                "No named people yet. Name the faces below to start.",\n'
                                          '                t.font(13.0),\n'
                                          '                t.text_dim,',
                                          '                "No named people yet. Name the faces below to start.",\n'
                                          '                t.font(13.0),\n'
                                          '                crate::theme::readable_ink(t.grid_bg, t.text_dim),',
                                          1),
                                         ('name, t.semibold(13.0), t.text);',
                                          'name, t.semibold(13.0), crate::theme::readable_ink(t.grid_bg, t.text));',
                                          1),
                                         ('photos, t.font(12.0), t.text_dim);',
                                          'photos, t.font(12.0), crate::theme::readable_ink(t.grid_bg, t.text_dim));',
                                          1),
                                         ('super::empty_message(ui, ui.available_rect_before_wrap(), title, body);',
                                          'super::empty_message_on(ui, ui.available_rect_before_wrap(), title, body, t.grid_bg);',
                                          1)],
 'crates/ui-egui/src/panels/person.rs': [('RichText::new(&shown_name).font(t.semibold(15.0)).color(t.text)',
                                          'RichText::new(&shown_name).font(t.semibold(15.0)).color(crate::theme::readable_ink(t.grid_bg, '
                                          't.text))',
                                          1),
                                         ('RichText::new(count).color(t.text_dim)',
                                          'RichText::new(count).color(crate::theme::readable_ink(t.grid_bg, t.text_dim))',
                                          1),
                                         ('"More", t.semibold(15.0), t.text);',
                                          '"More", t.semibold(15.0), crate::theme::readable_ink(t.grid_bg, t.text));',
                                          1),
                                         ('sub, t.font(12.0), t.text_dim);',
                                          'sub, t.font(12.0), crate::theme::readable_ink(t.grid_bg, t.text_dim));',
                                          1),
                                         ('        super::empty_message(\n'
                                          '            ui,\n'
                                          '            ui.available_rect_before_wrap(),\n'
                                          '            "No faces by that name",\n'
                                          '            "They may have been renamed or removed. Go back to People",\n'
                                          '        );',
                                          '        super::empty_message_on(\n'
                                          '            ui,\n'
                                          '            ui.available_rect_before_wrap(),\n'
                                          '            "No faces by that name",\n'
                                          '            "They may have been renamed or removed. Go back to People",\n'
                                          '            t.grid_bg,\n'
                                          '        );',
                                          1)],
 'crates/ui-egui/src/panels/unnamed.rs': [('}).color(t.text));', '}).color(crate::theme::readable_ink(t.grid_bg, t.text)));', 1),
                                          ('RichText::new(p.as_str()).color(t.text_label)',
                                           'RichText::new(p.as_str()).color(crate::theme::readable_ink(t.grid_bg, t.text_label))',
                                           1),
                                          ('"Unnamed faces", t.semibold(15.0), t.text);',
                                           '"Unnamed faces", t.semibold(15.0), crate::theme::readable_ink(t.grid_bg, t.text));',
                                           1),
                                          ('count, t.font(13.0), t.text_dim);',
                                           'count, t.font(13.0), crate::theme::readable_ink(t.grid_bg, t.text_dim));',
                                           1),
                                          ('sub, t.font(12.0), t.text_dim);',
                                           'sub, t.font(12.0), crate::theme::readable_ink(t.grid_bg, t.text_dim));',
                                           1),
                                          ('Color32::from_rgba_unmultiplied(70, 130, 255, 55)',
                                           'Color32::from_rgba_unmultiplied(0xFF, 0xE7, 0xD4, 55)',
                                           1),
                                          ('Color32::from_rgb(110, 160, 255)', 't.accent', 1),
                                          ('p.circle_filled(c, 9.0, Color32::from_rgb(70, 130, 255));',
                                           'p.circle_filled(c, 9.0, t.pressed);',
                                           1),
                                          ('Stroke::new(1.8, Color32::WHITE)', 'Stroke::new(1.8, t.text)', 2)],
 'crates/ui-egui/src/import.rs': [('if on { t.accent } else { Color32::from_black_alpha(150) }',
                                   'if on { t.pressed } else { Color32::from_black_alpha(150) }',
                                   1),
                                  ('Stroke::new(2.0, Color32::WHITE)', 'Stroke::new(2.0, t.text)', 2)],
 'crates/ui-egui/src/panels/settings.rs': [('if favorite { t.accent } else { t.text_dim }', 'if favorite { t.icon } else { t.text_dim }', 1)],
 'crates/ui-egui/src/panels/edit.rs': [('            format!("{} / {}", (q.x * 255.0).round(), (q.y * 255.0).round()),\n'
                                        '            t.font(11.0),\n'
                                        '            t.text_dim,',
                                        '            format!("{} / {}", (q.x * 255.0).round(), (q.y * 255.0).round()),\n'
                                        '            t.font(11.0),\n'
                                        '            crate::theme::readable_ink(t.canvas, t.text_dim),',
                                        1)],
 'crates/ui-egui/src/panels/library_problem.rs': [('.color(t.canvas),', '.color(crate::theme::readable_ink(t.caution, t.text)),', 1),
                                                  ('RichText::new(crate::i18n::tr("Open '
                                                   'Library…")).color(t.canvas)).fill(egui::Color32::from_black_alpha(40))',
                                                   'RichText::new(crate::i18n::tr("Open Library…")).color(t.text)).fill(t.button)',
                                                   1)]}


PDF_ROLE_REPLACEMENTS = {'crates/ui-egui/src/home.rs': [('pub fn show(app: &mut PdfCraftApp, ui: &mut egui::Ui) {\n    let t = Tokens::get(ui.ctx());',
                                 'pub fn show(app: &mut PdfCraftApp, ui: &mut egui::Ui) {\n'
                                 '    let t = Tokens::get(ui.ctx());\n'
                                 '    // Home owns this clipped UI surface in both Read and docked/floating Canvas routes.\n'
                                 '    ui.painter().rect_filled(ui.max_rect(), 0.0, t.panel);',
                                 1),
                                ('press.fill(t.pasteboard, t.hover, t.pressed)', 'press.fill(t.card, t.hover, t.pressed)', 1)],
 'crates/ui-egui/tests/ui.rs': [('use pdfcraft_ui_egui::PdfCraftApp;\n',
                                 'use pdfcraft_ui_egui::PdfCraftApp;\n'
                                 '\n'
                                 '// Bogo home surface regression: drive the real app, including its default docking path.\n'
                                 "fn bogo_last_opaque_fill(h: &Harness<'static, PdfCraftApp>, point: egui::Pos2) -> "
                                 'Option<egui::Color32> {\n'
                                 '    fn visit(shape: &egui::Shape, point: egui::Pos2, color: &mut Option<egui::Color32>) {\n'
                                 '        match shape {\n'
                                 '            egui::Shape::Vec(shapes) => {\n'
                                 '                for shape in shapes {\n'
                                 '                    visit(shape, point, color);\n'
                                 '                }\n'
                                 '            }\n'
                                 '            egui::Shape::Rect(rect) if rect.rect.contains(point) && rect.fill.a() == 255 => '
                                 '*color = Some(rect.fill),\n'
                                 '            _ => {}\n'
                                 '        }\n'
                                 '    }\n'
                                 '    let mut color = None;\n'
                                 '    for clipped in &h.output().shapes {\n'
                                 '        if clipped.clip_rect.contains(point) {\n'
                                 '            visit(&clipped.shape, point, &mut color);\n'
                                 '        }\n'
                                 '    }\n'
                                 '    color\n'
                                 '}\n'
                                 '\n'
                                 "fn bogo_canvas_blank_margin(h: &Harness<'static, PdfCraftApp>) -> egui::Pos2 {\n"
                                 '    // A document exposes its actual viewport; never sample a sidebar from the outer '
                                 'CentralPanel.\n'
                                 '    if let Some(index) = h.state().active {\n'
                                 '        let view = &h.state().views[index];\n'
                                 '        let viewport = view.viewport_rect();\n'
                                 '        assert!(viewport.is_positive(), "document viewport is painted");\n'
                                 '        let point = egui::pos2(viewport.left() + 8.0, viewport.bottom() - 16.0);\n'
                                 '        assert!(viewport.contains(point));\n'
                                 '        assert!(view.visible_page_rects().iter().all(|(_, rect)| !rect.contains(point)), '
                                 '"probe must be document margin, not page content");\n'
                                 '        return point;\n'
                                 '    }\n'
                                 '    // Home and Combine use their real heading to bind the topmost enclosing Canvas backdrop.\n'
                                 '    let pasteboard = egui::Color32::from_rgb(0xF1, 0xF1, 0xF3);\n'
                                 '    let text = painted_text(h);\n'
                                 '    let heading = text.iter().find(|(text, _, _)| text.contains("Welcome to Bogo PDF"))\n'
                                 '        .or_else(|| text.iter().filter(|(text, _, _)| text == "Combine files").max_by(|a, b| '
                                 'a.2.height().total_cmp(&b.2.height())))\n'
                                 '        .expect("Home or Combine heading is actually painted").2.center();\n'
                                 '    let canvases: Vec<_> = h\n'
                                 '        .output()\n'
                                 '        .shapes\n'
                                 '        .iter()\n'
                                 '        .filter_map(|clipped| {\n'
                                 '            if let egui::Shape::Rect(rect) = &clipped.shape {\n'
                                 '                let visible = rect.rect.intersect(clipped.clip_rect);\n'
                                 '                if rect.fill == pasteboard && visible.width() > 250.0 && visible.height() > '
                                 '200.0 {\n'
                                 '                    return Some(visible);\n'
                                 '                }\n'
                                 '            }\n'
                                 '            None\n'
                                 '        })\n'
                                 '        .collect();\n'
                                 '    let canvas = canvases.iter().rev().find(|rect| '
                                 'rect.contains(heading)).copied().expect("heading belongs to a real Canvas");\n'
                                 '    // The Home/Combine content inset leaves this left-bottom margin free of controls.\n'
                                 '    egui::pos2(canvas.left() + 8.0, canvas.bottom() - 16.0)\n'
                                 '}\n'
                                 '\n'
                                 '#[test]\n'
                                 'fn bogo_home_surface_role_covers_real_default_read_and_floating_routes() {\n'
                                 '    use pdfcraft_ui_egui::{Mode, docking::Panel};\n'
                                 '    let expected = egui::Color32::from_rgb(0xFF, 0xFA, 0xF6);\n'
                                 '    let default = harness(|_| {});\n'
                                 '    assert_eq!(default.state().mode, Mode::AllTools, "the actual default must exercise '
                                 'docking");\n'
                                 '    default.get_by_label_contains("Welcome to Bogo PDF");\n'
                                 '    assert_eq!(bogo_last_opaque_fill(&default, bogo_canvas_blank_margin(&default)), '
                                 'Some(expected));\n'
                                 '    let tools = painted_text(&default).into_iter().find(|(text, _, _)| text == '
                                 '"Tools").expect("actual selected Tools docktab is painted");\n'
                                 '    assert_eq!(bogo_last_opaque_fill(&default, tools.2.center()), '
                                 'Some(egui::Color32::from_rgb(0xFF, 0xE7, 0xD4)), "the actual selected docktab uses the Bogo '
                                 'chrome selection surface");\n'
                                 '    let read = harness(|app| {\n'
                                 '        app.mode = Mode::Read;\n'
                                 '    });\n'
                                 '    assert_eq!(read.state().mode, Mode::Read);\n'
                                 '    read.get_by_label_contains("Welcome to Bogo PDF");\n'
                                 '    assert_eq!(bogo_last_opaque_fill(&read, bogo_canvas_blank_margin(&read)), '
                                 'Some(expected));\n'
                                 '    let floating = harness(|app| {\n'
                                 '        let protected = serde_json::to_value(&app.docking).unwrap();\n'
                                 '        assert!(app.docking.apply(craft_ui::docking::Action::Float { panel: Panel::Canvas, '
                                 'rect: [360.0, 140.0, 900.0, 620.0] }).is_err(), "the document Canvas remains protected");\n'
                                 '        assert_eq!(serde_json::to_value(&app.docking).unwrap(), protected, "a refused docking '
                                 'action cannot mutate layout");\n'
                                 '        app.docking.apply(craft_ui::docking::Action::Float { panel: Panel::Tools, rect: '
                                 '[1040.0, 140.0, 300.0, 360.0] }).unwrap();\n'
                                 '    });\n'
                                 '    assert!(floating.state().docking.layout.floating.iter().any(|group| '
                                 'group.panels.contains(&Panel::Tools)));\n'
                                 '    floating.get_by_label_contains("Welcome to Bogo PDF");\n'
                                 '    assert_eq!(bogo_last_opaque_fill(&floating, bogo_canvas_blank_margin(&floating)), '
                                 'Some(expected));\n'
                                 '}\n'
                                 '\n'
                                 '#[test]\n'
                                 'fn bogo_home_surface_role_preserves_document_and_combine_pasteboards() {\n'
                                 '    let expected = egui::Color32::from_rgb(0xF1, 0xF1, 0xF3);\n'
                                 '    let document = harness(|app| {\n'
                                 '        app.open_bytes("fixture.pdf", None, FIXTURE.to_vec()).unwrap();\n'
                                 '    });\n'
                                 '    assert!(document.state().active.is_some());\n'
                                 '    assert_eq!(bogo_last_opaque_fill(&document, bogo_canvas_blank_margin(&document)), '
                                 'Some(expected));\n'
                                 '    let combine = harness(|app| {\n'
                                 '        app.open_combine_tab();\n'
                                 '    });\n'
                                 '    assert!(combine.state().combine_showing());\n'
                                 '    assert_eq!(bogo_last_opaque_fill(&combine, bogo_canvas_blank_margin(&combine)), '
                                 'Some(expected));\n'
                                 '}\n'
                                 '\n',
                                 1)],
 'crates/ui-egui/src/docking.rs': [('    style.active_background = t.selected;', '    style.active_background = t.pressed;', 1)]}


EXTRA_VISUAL_REPLACEMENTS = {('photo', 'crates/ui-egui/src/gpu_status.rs'): [('            ui.label(egui::RichText::new(tl!("GPU acceleration could not '
                                                  'continue. Your documents are unchanged.")).color(t.warning));',
                                                  '            ui.label(egui::RichText::new(tl!("GPU acceleration could not '
                                                  'continue. Your documents are unchanged.")).color(t.text));',
                                                  1)],
 ('deck', 'crates/ui-egui/src/theme.rs'): [('#[cfg(test)]\nmod tests {',
                                            'pub(crate) fn builtin_display_name(name: &str) -> &str {\n'
                                            '    if name == "DeckCraft" { "Bogo Deck" } else { name }\n'
                                            '}\n'
                                            '\n'
                                            '#[cfg(test)]\n'
                                            'mod tests {',
                                            1)],
 ('deck', 'crates/ui-egui/src/backstage.rs'): [('q.is_empty() || th.name.to_lowercase().contains(&q)',
                                                'q.is_empty() || th.name.to_lowercase().contains(&q) || '
                                                'crate::theme::builtin_display_name(&th.name).to_lowercase().contains(&q)',
                                                1),
                                               ('tile(ui, &th.name, Some(&th), false)',
                                                'tile(ui, crate::theme::builtin_display_name(&th.name), Some(&th), false)',
                                                1)],
 ('deck', 'crates/ui-egui/src/ribbon.rs'): [('|i| names.get(i).cloned().unwrap_or_default(),',
                                             '|i| names.get(i).map(|name| '
                                             'crate::theme::builtin_display_name(name).to_owned()).unwrap_or_default(),',
                                             1),
                                            ('Align2::LEFT_CENTER, &cs.name, theme::font(12.0)',
                                             'Align2::LEFT_CENTER, crate::theme::builtin_display_name(&cs.name), theme::font(12.0)',
                                             1),
                                            ('ui.button(&th.name).clicked()',
                                             'ui.button(crate::theme::builtin_display_name(&th.name)).clicked()',
                                             1)],
 ('deck', 'crates/ui-egui/src/panes.rs'): [('resp.on_hover_text(&th.name).clicked()',
                                            'resp.on_hover_text(crate::theme::builtin_display_name(&th.name)).clicked()',
                                            1)],
 ('film', 'crates/ui-egui/src/theme.rs'): [('    pub focus: Color32,', '    pub focus: Color32,\n    pub chrome_focus: Color32,', 1),
                                           ('            focus: Color32::from_rgb(0x57, 0x94, 0xec),',
                                            '            focus: Color32::from_rgb(0x57, 0x94, 0xec),\n'
                                            '            chrome_focus: Color32::from_rgb(0xFC, 0x75, 0x01),',
                                            1)],
 ('film', 'crates/ui-egui/src/panels/tools.rs'): [('vec2(26.0, 26.0)), 4.0, t.accent);', 'vec2(26.0, 26.0)), 4.0, t.pressed);', 1),
                                                  ('current.icon(), if active { egui::Color32::WHITE } else { t.icon });',
                                                   'current.icon(), t.icon);',
                                                   1),
                                                  ('egui::Stroke::new(1.5, t.focus)', 'egui::Stroke::new(1.5, t.chrome_focus)', 1)],
 ('film', 'crates/ui-egui/src/dock.rs'): [('ui.painter().rect_stroke(group.rect, 0.0, Stroke::new(1.0, tokens.focus), StrokeKind::Inside);',
                                           'ui.painter().rect_stroke(group.rect, 0.0, Stroke::new(1.0, tokens.chrome_focus), '
                                           'StrokeKind::Inside);',
                                           1)],
 ('film', 'crates/ui-egui/src/panels/timeline.rs'): [
     ('ui.painter().rect_filled(b, 13.0, if resp.hovered() { t.accent_hover } else { t.accent });',
      'ui.painter().rect_filled(b, 13.0, if resp.hovered() { t.pressed } else { t.tab_bg });', 1),
     ('ui.painter().text(b.center(), Align2::CENTER_CENTER, tl!("Open Demo Project"), Tokens::semibold(12.0), Color32::WHITE);',
      'ui.painter().text(b.center(), Align2::CENTER_CENTER, tl!("Open Demo Project"), Tokens::semibold(12.0), t.icon);', 1)],
 ('film', 'crates/ui-egui/tests/ui_keyboard_focus.rs'): [
     ('&& r.stroke.color == h.state().tokens.focus && r.stroke.width > 0.0)),\n'
      '        "the focused custom-painted tool needs a visible focus outline"',
      '&& r.stroke.color == h.state().tokens.chrome_focus && r.stroke.width > 0.0)),\n'
      '        "the focused custom-painted tool needs a visible focus outline"', 1)],
 ('word', 'crates/ui-egui/src/backstage.rs'): [('egui::CentralPanel::default().frame(egui::Frame::NONE.fill(t.ribbon).inner_margin(egui::Margin::symmetric(40, '
                                                '30)))',
                                                'egui::CentralPanel::default().frame(egui::Frame::NONE.fill(t.panel).inner_margin(egui::Margin::symmetric(40, '
                                                '30)))',
                                                1)]}


def replacements(app, relative):
    rows = previous_replacements(app, relative)
    if app == 'light':
        rows = rows + LIGHT_ROLE_REPLACEMENTS.get(relative, [])
    elif app == 'pdf':
        rows = rows + PDF_ROLE_REPLACEMENTS.get(relative, [])
    return rows + EXTRA_VISUAL_REPLACEMENTS.get((app, relative), [])


def transform(app, relative, text):
    if app == 'film' and relative == FILM_DEMO_TEST_PATH:
        import hashlib
        if hashlib.sha256(text.encode('utf-8')).hexdigest() != FILM_DEMO_TEST_BEFORE_SHA256:
            raise ValueError('Every original Film monitor UI test must retain its exact reviewed bytes')
        return text + FILM_DEMO_PAINT_TEST
    if app == 'film' and relative in (FILM_DEMO_CTA_PATH, FILM_KEYBOARD_TEST_PATH):
        import hashlib
        before_sha, after_sha = ((FILM_DEMO_CTA_BEFORE_SHA256, FILM_DEMO_CTA_AFTER_SHA256)
                                 if relative == FILM_DEMO_CTA_PATH else FILM_KEYBOARD_TEST_SHA256)
        if hashlib.sha256(text.encode('utf-8')).hexdigest() != before_sha:
            raise ValueError('Exact reviewed empty-timeline Film CTA source required')
        after = replace_exact(text, replacements(app, relative))
        if hashlib.sha256(after.encode('utf-8')).hexdigest() != after_sha:
            raise ValueError('Unexpected Film demo CTA role output')
        return after
    return replace_exact(text, replacements(app, relative))


FILM_DEMO_CTA_PATH = 'crates/ui-egui/src/panels/timeline.rs'
FILM_DEMO_CTA_BEFORE_SHA256 = '0194819d30fb493375d2eebcad0105fc07e5ec0495af74552ea7a703206eec67'
FILM_DEMO_CTA_AFTER_SHA256 = 'e3268ead06293db944e3ec1f64c5ff66b17ce5ad0a709d2ac8622eedc5d17eaa'
FILM_KEYBOARD_TEST_PATH = 'crates/ui-egui/tests/ui_keyboard_focus.rs'
FILM_KEYBOARD_TEST_SHA256 = ('02e6850f91ab274a355fced517c0540e4486f1d3ac253d7e702ebf16163b7bbf',
                            'a972eb501f8fc43e1dc86d1a48184897a158abeb2883ee8c185d3d6eae54f340')


# Applied after the exact existing promotion-test transform, before normal rustfmt.
LAUNCHER_POST_ROLE_ROWS = {'crates/ui-egui/src/theme.rs': {'beforeSha256': '217e17d6f6aed75ac814ff6143f8ef2a3938c5151be3239d72c7b19758da70c3',
                                 'afterSha256': 'ac3ec9fba6640e65bebf6e8d50f7135de45071a2d811f36006c39eaf9c63f149',
                                 'pairs': [['    pub bg: Color32,',
                                            '    pub bg: Color32,\n'
                                            '    /// Header chrome, independent of gallery and document colours.\n'
                                            '    pub header: Color32,\n'
                                            '    /// Selected and hovered application controls.\n'
                                            '    pub selection: Color32,',
                                            1],
                                           ['        bg: Color32::from_rgb(0xFF, 0xFA, 0xF6),\n        sunken:',
                                            '        bg: Color32::from_rgb(0xFF, 0xFA, 0xF6),\n'
                                            '        header: Color32::from_rgb(0xFF, 0xF3, 0xE8),\n'
                                            '        selection: Color32::from_rgb(0xFF, 0xE7, 0xD4),\n'
                                            '        sunken:',
                                            2],
                                           ['    v.selection.bg_fill = t.accent;', '    v.selection.bg_fill = t.selection;', 1],
                                           ['    v.selection.stroke = Stroke::new(1.0, Color32::WHITE);',
                                            '    v.selection.stroke = Stroke::new(1.0, t.ink);',
                                            1],
                                           ['(&mut v.widgets.hovered, t.sunken, t.line_strong, t.ink_strong)',
                                            '(&mut v.widgets.hovered, t.selection, t.line_strong, t.ink_strong)',
                                            1],
                                           ['(&mut v.widgets.active, t.sunken, t.line_strong, t.ink_strong)',
                                            '(&mut v.widgets.active, t.selection, t.line_strong, t.ink_strong)',
                                            1],
                                           ['(&mut v.widgets.open, t.sunken, t.line_strong, t.ink_strong)',
                                            '(&mut v.widgets.open, t.selection, t.line_strong, t.ink_strong)',
                                            1]]},
 'crates/ui-egui/src/app.rs': {'beforeSha256': '241713bb24d8af8e9b7c37b61c511a91176352fbc2a435f3a8de2ad329c8613d',
                               'afterSha256': '334215c0742f8548498a0a6606a84cb8e739e1663fe48f746d8dbe60f58df930',
                               'pairs': [['        egui::Panel::top("header")\n'
                                          '            .frame(egui::Frame::new().fill(tokens.bg))',
                                          '        egui::Panel::top("header")\n'
                                          '            .frame(egui::Frame::new().fill(tokens.header))',
                                          1]]},
 'crates/ui-egui/src/widgets.rs': {'beforeSha256': '2d9f26525dff8f619fc79a20f1120c3dc86b93e623eabc4365ef57e0329204fd',
                                   'afterSha256': 'a1102857a4174856ceed65078d14d4160c3e54176b50d56ba2464f655bc966aa',
                                   'pairs': [['ui.painter().rect_filled(span, CornerRadius::ZERO, t.invert_bg);',
                                              'ui.painter().rect_filled(span, CornerRadius::ZERO, t.selection);',
                                              1],
                                             ['        p.rect_filled(rect, CornerRadius::ZERO, t.invert_bg);',
                                              '        p.rect_filled(rect, CornerRadius::ZERO, t.selection);',
                                              2],
                                             ['Kind::Primary => (t.invert_bg.gamma_multiply(if hovered { 0.8 } else { 1.0 }), '
                                              'Stroke::NONE, t.invert_fg),',
                                              'Kind::Primary => (if hovered { t.selection } else { t.invert_bg }, Stroke::NONE, '
                                              't.invert_fg),',
                                              1],
                                             ['Kind::Secondary if hovered => (t.invert_bg, Stroke::NONE, t.invert_fg),',
                                              'Kind::Secondary if hovered => (t.selection, Stroke::NONE, t.ink_strong),',
                                              1],
                                             ['if on { t.invert_fg.gamma_multiply(0.6) } else { highlight.filter(|_| n > '
                                              '0).unwrap_or(t.faint) }',
                                              'if on { t.ink_strong } else { highlight.filter(|_| n > 0).unwrap_or(t.faint) }',
                                              1],
                                             ['(true, _) => (t.invert_bg, t.invert_fg),',
                                              '(true, _) => (t.selection, t.ink_strong),',
                                              1],
                                             ['(false, true) => (t.sunken, t.ink_strong),',
                                              '(false, true) => (t.selection, t.ink_strong),',
                                              1]]},
 'crates/ui-egui/src/views.rs': {'beforeSha256': '08239da360f8e1138eaa7355b9c4f1cdebaa8bdb81d8df5fa710e8f8cafea0d8',
                                 'afterSha256': '574fa442f1ba240c50a6fca0695e1df138a436423dba481992ccfc263baefee1',
                                 'pairs': [['widgets::tag(ui, tl!("Launcher"), t.invert_bg, t.invert_fg);',
                                            'widgets::tag(ui, tl!("Launcher"), t.selection, t.ink_strong);',
                                            1],
                                           ['widgets::tag(ui, tl!("Update"), t.accent, Color32::WHITE);',
                                            'widgets::tag(ui, tl!("Update"), t.selection, t.ink_strong);',
                                            1],
                                           ['        let app_color = rgb(app.color);', '        let app_color = t.accent;', 1],
                                           ['let fill = t.bg.lerp_to_gamma(app_color, 0.05 * lift);',
                                            'let fill = t.bg.lerp_to_gamma(t.selection, lift);',
                                            1],
                                           ['widgets::tag(&mut strip_ui, &number, app_color, Color32::BLACK);',
                                            'widgets::tag(&mut strip_ui, &number, t.selection, t.ink_strong);',
                                            1]]},
 'crates/ui-egui/src/details.rs': {'beforeSha256': '3b70dccc9befbff63ed6fc77c12214bc39af9801850e905080768725c053a252',
                                   'afterSha256': '9185af4157b6be068a73f5ededa0683adb880f20a5c42ca9f5dbfd2be74488b2',
                                   'pairs': [['        let app_color = rgb(app.color);', '        let app_color = t.accent;', 1],
                                             ['egui::Frame::new().fill(tint(app_color, if t.dark { 0.09 } else { 0.07 '
                                              '})).inner_margin',
                                              'egui::Frame::new().fill(t.header).inner_margin',
                                              1],
                                             ['let (fill, ink) = if resp.hovered() { (t.invert_bg, t.invert_fg) } else { '
                                              '(t.bg.gamma_multiply(0.92), t.ink) };',
                                              'let (fill, ink) = if resp.hovered() { (t.selection, t.ink_strong) } else { '
                                              '(t.bg.gamma_multiply(0.92), t.ink) };',
                                              1]]}}

LAUNCHER_ROLE_TEST_PREIMAGE_SHA256 = "61fde7d5658096455fd77014bf7bed28920f49ac86fc389872fbcaa059d2f737"
LAUNCHER_ROLE_PAINT_TEST = '// Append after the existing promotion-test transform. The original tests remain byte-identical.\n#[test]\nfn bogo_launcher_actual_header_selection_hover_and_index_shapes() {\n    use egui::{Color32, Pos2, Rect};\n    use egui::epaint::Shape;\n    const HEADER: Color32 = Color32::from_rgb(0xff, 0xf3, 0xe8);\n    const SELECTED: Color32 = Color32::from_rgb(0xff, 0xe7, 0xd4);\n    const INK: Color32 = Color32::from_rgb(0x34, 0x2b, 0x26);\n\n    // Retain painter order and the parent\'s real clip, including nested Shape::Vec.\n    fn leaves<\'a>(shape: &\'a Shape, clip: Rect, out: &mut Vec<(Rect, &\'a Shape)>) {\n        if let Shape::Vec(children) = shape {\n            for child in children { leaves(child, clip, out); }\n        } else {\n            out.push((clip, shape));\n        }\n    }\n    fn painted<\'a>(h: &\'a Harness<\'_, Option<LauncherUi>>) -> Vec<(Rect, &\'a Shape)> {\n        let mut out = Vec::new();\n        for clipped in &h.output().shapes { leaves(&clipped.shape, clipped.clip_rect, &mut out); }\n        out\n    }\n    fn top_rect_fill(h: &Harness<\'_, Option<LauncherUi>>, p: Pos2) -> Option<Color32> {\n        painted(h).into_iter().filter_map(|(clip, shape)| match shape {\n            Shape::Rect(r) if clip.contains(p) && r.rect.contains(p) && r.fill.a() == 255 => Some(r.fill),\n            _ => None,\n        }).last()\n    }\n    fn assert_ink(h: &Harness<\'_, Option<LauncherUi>>, target: Rect, text: &str) {\n        let matching: Vec<_> = painted(h).into_iter().filter_map(|(clip, shape)| match shape {\n            Shape::Text(t) if t.galley.job.text == text\n                && clip.intersects(target) && t.visual_bounding_rect().intersects(target) => Some(t),\n            _ => None,\n        }).collect();\n        assert_eq!(matching.len(), 1, "one actual visible text shape {text:?} in {target:?}");\n        let t = matching[0];\n        assert_eq!(t.opacity_factor, 1.0, "{text}: no dimming of the selected label");\n        // widgets::paint_left/paint_centred use galley_with_override_text_color.\n        assert_eq!(t.override_text_color, Some(INK), "{text}: actual glyph ink must remain readable brown");\n    }\n    fn assert_selection(h: &Harness<\'_, Option<LauncherUi>>, label: &str, text: &str) {\n        let rect = h.get_by_label(label).rect();\n        assert_eq!(top_rect_fill(h, rect.center()), Some(SELECTED), "actual selected/hover fill for {label}");\n        assert_ink(h, rect, text);\n    }\n\n    for theme in [egui::Theme::Light, egui::Theme::Dark] {\n        let (mut h, _) = harness(ViewMode::Grid, theme, true);\n        h.event(egui::Event::PointerGone);\n        h.run_steps(6);\n        assert_eq!(h.state().as_ref().unwrap().settings.view, ViewMode::Grid);\n        assert_eq!(h.state().as_ref().unwrap().settings.filter, artcraft_launcher_ui_egui::settings::Filter::All);\n        let grid = h.get_by_label("Grid").rect();\n        let header_rects: Vec<_> = painted(&h).into_iter().filter_map(|(clip, shape)| match shape {\n            Shape::Rect(r) if r.fill == HEADER => {\n                let visible = r.rect.intersect(clip);\n                (visible.width() >= 1100.0 && visible.height() >= 40.0 && visible.height() <= 90.0\n                    && visible.contains(grid.center())).then_some(visible)\n            }\n            _ => None,\n        }).collect();\n        assert!(!header_rects.is_empty(), "{theme:?}: actual full-width pale header must contain the Grid navigation center");\n        assert_selection(&h, "Grid", "GRID");\n        assert_selection(&h, "All 13", "ALL");\n        // Index 01 can be below the fold under a different legitimate sort order.\n        let index_id = h.get_by_label("01").accesskit_node().id();\n        h.get_by_label("01").scroll_to_me();\n        h.run_steps(4);\n        assert_eq!(h.get_by_label("01").accesskit_node().id(), index_id, "probe the same real index badge after scrolling");\n        assert_selection(&h, "01", "01");\n\n        let table = h.get_by_label("Table").rect();\n        assert_ne!(top_rect_fill(&h, table.center()), Some(SELECTED), "unselected Table starts unhighlighted");\n        let table_id = h.get_by_label("Table").accesskit_node().id();\n        h.event(egui::Event::PointerMoved(table.center()));\n        h.run_steps(4);\n        assert_eq!(h.get_by_label("Table").accesskit_node().id(), table_id, "hover the same real node");\n        assert_eq!(h.state().as_ref().unwrap().settings.view, ViewMode::Grid, "hover must not click or switch views");\n        assert_selection(&h, "Table", "TABLE");\n        assert_selection(&h, "Grid", "GRID");\n    }\n}\n'


def launcher_role_text(relative, text):
    """One authenticated Launcher UI preimage; never a global palette rewrite."""
    import hashlib
    row = LAUNCHER_POST_ROLE_ROWS.get(relative)
    if row is None or hashlib.sha256(text.encode('utf-8')).hexdigest() != row['beforeSha256']:
        raise ValueError('Exact reviewed post-promotion Launcher UI source required: ' + relative)
    after = replace_exact(text, row['pairs'])
    if hashlib.sha256(after.encode('utf-8')).hexdigest() != row['afterSha256']:
        raise ValueError('Unexpected Launcher UI role output: ' + relative)
    return after


def apply_launcher_role_source(source, app):
    """Closed UI-only post-hook; preserve every original test before appending one."""
    if app != 'launcher':
        return []
    import hashlib
    from pathlib import Path
    source = Path(source)
    if not source.is_dir() or source.is_symlink():
        raise ValueError('Launcher role source must be a regular prepared directory')
    planned = {}
    test_relative = 'crates/ui-egui/tests/ui.rs'
    for relative in (*LAUNCHER_POST_ROLE_ROWS, test_relative):
        path = source / relative
        if not path.is_file() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent == source or source in parent.parents):
            raise ValueError('Linked or missing Launcher UI role source: ' + relative)
        before = path.read_text(encoding='utf-8')
        if relative == test_relative:
            if hashlib.sha256(before.encode('utf-8')).hexdigest() != LAUNCHER_ROLE_TEST_PREIMAGE_SHA256:
                raise ValueError('Every original Launcher UI test must retain its exact reviewed bytes')
            planned[path] = before + '\n' + LAUNCHER_ROLE_PAINT_TEST
        else:
            planned[path] = launcher_role_text(relative, before)
    # Validate all six original files before any write. Data, registry, media,
    # assets, dependency, license and unrelated application paths are never visited.
    for path, after in planned.items():
        path.write_text(after, encoding='utf-8', newline='')
    return sorted(path.relative_to(source).as_posix() for path in planned)


# Add one actual production-painter regression; every original UI test stays exact.
FILM_DEMO_TEST_PATH = 'crates/ui-egui/tests/monitor_geometry.rs'
FILM_DEMO_TEST_BEFORE_SHA256 = '59f451d9de3dd3707888850335f78ae97670e7fcfe0be52e86f5fed6b1ef4399'
FILM_DEMO_PAINT_TEST = '\nmod bogo_demo_cta {\n//! Additive actual-production empty-timeline CTA regression; no original tests changed.\nuse egui::{Color32, Event, Id, Modifiers, PointerButton, Pos2, Rect, pos2, vec2};\nuse egui::epaint::Shape;\nuse egui_kittest::Harness;\nuse filmcraft_engine::Session;\nuse filmcraft_ui_egui::{\n    FilmcraftApp,\n    dock::{self, DockNode, PanelKind, SeqTabs},\n    panels::timeline,\n    theme::{self, ThemeKind},\n};\nuse serde_json::json;\n\nconst NORMAL: Color32 = Color32::from_rgb(0xff, 0xf3, 0xe8);\nconst HOVER: Color32 = Color32::from_rgb(0xff, 0xe7, 0xd4);\nconst INK: Color32 = Color32::from_rgb(0x34, 0x2b, 0x26);\n\nfn harness(kind: ThemeKind, highlight: &\'static str, accessible: bool) -> Harness<\'static, FilmcraftApp> {\n    let mut session = Session::default();\n    session.prefs.appearance.highlight_color = highlight.into();\n    session.prefs.appearance.accessible_contrast = accessible;\n    assert!(session.state.active_sequence.is_none());\n    assert!(session.prefs_path.is_none() && session.persistence.is_none(), "test session has no user profile persistence");\n    let mut fonts_ready = false;\n    let mut h = Harness::builder().with_size(vec2(720.0, 360.0)).with_pixels_per_point(1.0).build_ui_state(\n        move |ui, app: &mut FilmcraftApp| {\n            filmcraft_ui_egui::i18n::set_current(filmcraft_ui_egui::i18n::Language::En);\n            // The real production preference application, not a synthetic token table.\n            app.set_theme(ui.ctx(), kind);\n            if !fonts_ready {\n                // Match production\'s first-frame font install before painting semibold text.\n                theme::install(ui.ctx(), &app.tokens);\n                fonts_ready = true;\n                ui.ctx().request_repaint();\n                return;\n            }\n            app.auto.begin_frame();\n            let panel = PanelKind::Timeline;\n            let mut node = DockNode::Tabs { panels: vec![panel], active: 0 };\n            let mut groups = Vec::new();\n            dock::layout(ui, &mut node, ui.max_rect(), &app.tokens, "bogo-demo-cta", &mut groups, &mut app.auto);\n            for group in groups {\n                dock::draw_group_chrome(ui, &group, panel, &SeqTabs::default(), &app.tokens, &mut app.auto);\n                // With no active sequence this dispatches the actual private empty_state.\n                timeline::show(app, ui, group.content);\n            }\n        },\n        FilmcraftApp::new(session),\n    );\n    h.event(Event::PointerGone);\n    h.run_steps(4);\n    h\n}\n\nfn cta(h: &Harness<\'_, FilmcraftApp>) -> Rect {\n    let entries: Vec<_> = h.state().auto.elements.iter().filter(|e| e.id == "timeline.openDemo").collect();\n    assert_eq!(entries.len(), 1, "one current actual automation element for the production CTA");\n    assert_eq!(entries[0].label, "Open Demo Project");\n    let [x, y, w, height] = entries[0].rect;\n    assert_eq!((w, height), (170.0, 26.0), "production click target geometry is preserved");\n    let rect = Rect::from_min_size(pos2(x, y), vec2(w, height));\n    let response = h.ctx.read_response(Id::new("tl-open-demo")).expect("original actual egui interaction ID");\n    assert_eq!(response.id, Id::new("tl-open-demo"));\n    assert_eq!(response.rect, rect, "automation and actual egui click target must agree");\n    rect\n}\n\nfn leaves<\'a>(shape: &\'a Shape, clip: Rect, out: &mut Vec<(Rect, &\'a Shape)>) {\n    if let Shape::Vec(children) = shape {\n        for child in children { leaves(child, clip, out); }\n    } else {\n        out.push((clip, shape));\n    }\n}\nfn painted<\'a>(h: &\'a Harness<\'_, FilmcraftApp>) -> Vec<(Rect, &\'a Shape)> {\n    let mut out = Vec::new();\n    for clipped in &h.output().shapes { leaves(&clipped.shape, clipped.clip_rect, &mut out); }\n    out\n}\nfn top_opaque_rect(h: &Harness<\'_, FilmcraftApp>, pos: Pos2) -> Option<(Rect, Color32)> {\n    painted(h).into_iter().filter_map(|(clip, shape)| match shape {\n        Shape::Rect(r) if clip.contains(pos) && r.rect.contains(pos) && r.fill.a() == 255 => Some((r.rect, r.fill)),\n        _ => None,\n    }).last()\n}\nfn assert_actual_paint(h: &Harness<\'_, FilmcraftApp>, expected: Color32) {\n    let rect = cta(h);\n    assert_eq!(top_opaque_rect(h, rect.center()), Some((rect, expected)), "actual last opaque CTA rectangle must use the intended role, in real clip/paint order");\n    let texts: Vec<_> = painted(h).into_iter().filter_map(|(clip, shape)| match shape {\n        Shape::Text(text) if text.galley.text() == "Open Demo Project" => {\n            let visible = text.visual_bounding_rect().intersect(clip).intersect(rect);\n            (visible.width() > 0.0 && visible.height() > 0.0).then_some(text)\n        }\n        _ => None,\n    }).collect();\n    assert_eq!(texts.len(), 1, "the real visible button glyph must exist inside the actual CTA clip");\n    let text = texts[0];\n    assert_eq!(text.opacity_factor, 1.0);\n    if let Some(color) = text.override_text_color {\n        assert_eq!(color, INK, "actual glyph override must be readable brown");\n    } else {\n        assert!(!text.galley.job.sections.is_empty());\n        for section in &text.galley.job.sections {\n            let color = if section.format.color == Color32::PLACEHOLDER { text.fallback_color } else { section.format.color };\n            assert_eq!(color, INK, "actual galley section glyph ink must be readable brown");\n        }\n    }\n}\n\n#[test]\nfn bogo_empty_timeline_demo_cta_actual_normal_hover_ink_and_command() {\n    let mut cases = 0;\n    for kind in [ThemeKind::Dark, ThemeKind::Medium, ThemeKind::Light] {\n        for accessible in [false, true] {\n            // Finite representatives: default, saturated custom, both extremes and brand.\n            for highlight in ["", "#e0457b", "#000000", "#ffffff", "#fc7501"] {\n                let mut h = harness(kind, highlight, accessible);\n                let before_journal = h.state().session.journal.clone();\n                let before_revision = h.state().session.revision;\n                let semantic = (h.state().tokens.accent, h.state().tokens.playhead, h.state().tokens.timecode, h.state().tokens.track_target);\n                assert_actual_paint(&h, NORMAL);\n                let rect = cta(&h);\n                h.event(Event::PointerMoved(rect.center()));\n                h.run_steps(4);\n                assert!(h.ctx.read_response(Id::new("tl-open-demo")).unwrap().hovered(), "real pointer event must hover the original CTA");\n                assert_eq!(cta(&h), rect, "hover preserves actual interaction target");\n                assert_actual_paint(&h, HOVER);\n                assert!(h.state().session.state.active_sequence.is_none(), "hover must not open a demo");\n                assert_eq!(h.state().session.journal, before_journal, "hover must not execute any engine command");\n                assert_eq!(h.state().session.revision, before_revision, "hover must not edit project data");\n                assert_eq!((h.state().tokens.accent, h.state().tokens.playhead, h.state().tokens.timecode, h.state().tokens.track_target), semantic, "saved highlight/media semantic colors are preserved");\n                assert_eq!(h.state().session.prefs.appearance.highlight_color, highlight);\n                assert_eq!(h.state().session.prefs.appearance.accessible_contrast, accessible);\n                h.event(Event::PointerGone);\n                h.run_steps(4);\n                assert_actual_paint(&h, NORMAL);\n                // Exercise the actual command once; the30 paint cases share the same handler.\n                if cases == 0 {\n                    h.event(Event::PointerMoved(rect.center()));\n                    h.run_steps(2);\n                    for pressed in [true, false] {\n                        h.event(Event::PointerButton { pos: rect.center(), button: PointerButton::Primary, pressed, modifiers: Modifiers::NONE });\n                        h.step();\n                    }\n                    assert!(h.state().session.state.active_sequence.is_some(), "real CTA click opens the built-in demo");\n                    assert_eq!(h.state().session.journal.last(), Some(&("file.openDemoProject".to_string(), json!({}))), "original exact command ID and params are preserved");\n                    assert_eq!(h.state().session.journal.len(), before_journal.len() + 1, "one actual click executes one original command");\n                }\n                cases += 1;\n            }\n        }\n    }\n    assert_eq!(cases, 30, "all3themes ×2contrast settings ×5bounded accent preferences rendered actual normal/hover shapes");\n}\n\n}\n'
