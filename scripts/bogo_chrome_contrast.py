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
            // Catalog labels retain their semantic colors; choose readable ink
            // from the actual composed background, including hover/selection.
            let luminance = |color: Color32| {
                let linear = |value: u8| {
                    let c = f32::from(value) / 255.0;
                    if c <= 0.04045 { c / 12.92 } else { ((c + 0.055) / 1.055).powf(2.4) }
                };
                0.2126 * linear(color.r()) + 0.7152 * linear(color.g()) + 0.0722 * linear(color.b())
            };
            let background_luminance = luminance(label_background);
            let primary_luminance = luminance(t.text_dim);
            let primary_contrast = (background_luminance.max(primary_luminance) + 0.05)
                / (background_luminance.min(primary_luminance) + 0.05);
            let label_ink = if primary_contrast >= 4.5 {
                t.text_dim
            } else if 1.05 / (background_luminance + 0.05) >= 4.5 {
                Color32::WHITE
            } else {
                Color32::BLACK
            };
            p.rect_filled(cr, 0.0, label_background);'''


def replacements(app, relative):
    if app == 'light' and relative == 'crates/ui-egui/src/docking.rs':
        return [('style.active_background = t.canvas;', 'style.active_background = t.hover;', 1)]
    if app == 'light' and relative == 'crates/ui-egui/src/panels/detail.rs':
        return [(LIGHT_LABEL_BEFORE, LIGHT_LABEL_AFTER, 1),
                ('film_label(name), t.font(10.0), t.text_dim);', 'film_label(name), t.font(10.0), label_ink);', 1),
                ('&ph.format, t.semibold(8.5), t.text_dim);', '&ph.format, t.semibold(8.5), label_ink);', 1)]
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


def transform(app, relative, text):
    return replace_exact(text, replacements(app, relative))
