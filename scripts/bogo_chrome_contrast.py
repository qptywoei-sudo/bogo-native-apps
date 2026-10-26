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
    return replace_exact(text, replacements(app, relative))
