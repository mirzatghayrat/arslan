"""Native .pptx generation from a validated deck spec (python-pptx).

Safe by construction, exactly like render_chart: the model supplies a normalized DATA spec
(slides + content + a closed set of layout intents), never code. We build the PowerPoint from
that spec. No shell, no network, no untrusted-file parsing (v1 ships clean themed decks;
template-following is deferred to v2). Output is a real, natively-editable .pptx (shapes + text
frames + speaker notes) — not slide images.

Inspired by hugohe3/ppt-master (MIT) for the "native editable shapes, not images" approach.
The design system (mandatory 5-role color theme + strict typography scale + per-page-type
composition rules) is a port of the SPEC from MiniMax-AI/skills pptx-generator (MIT) — no code
was vendored. See THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations

from io import BytesIO

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

LAYOUTS = {"title", "section", "bullets", "two-column", "quote", "big-number"}

# 16:9 canvas.
_W = Inches(13.333)
_H = Inches(7.5)
_MARGIN = Inches(0.6)
_CONTENT_W = _W - _MARGIN * 2

# Typography scale (pt) — consistent across every layout.
_T_TITLE = 40    # title-slide headline / section-slide oversize title
_T_HEADING = 32  # content-slide headings
_T_QUOTE = 28    # quote body
_T_BODY = 18     # bullets / subtitles / labels
_T_SUB = 16      # sub-bullets
_T_CAPTION = 12  # page badge / attributions / column headers

# Design system: every theme is a mandatory set of 5 color roles (hex, RGBColor-ready).
#   primary   — dominant ink: body text + solid bands (high contrast against bg)
#   secondary — supporting text: subtitles, attributions, sub-bullets, column headers
#   accent    — highlights ONLY: underline bars, badges, big section numbers;
#               never body text on a light background
#   light     — text placed ON a primary-filled band
#   bg        — slide background
THEMES: dict[str, dict[str, str]] = {
    # The house look: warm paper, near-black ink, chartreuse highlighter.
    "ink": {"primary": "1E1E1E", "secondary": "54665A", "accent": "EEFF53",
            "light": "FFFFFF", "bg": "F6F4F2"},
    # Dark: near-black blue, light text, cyan accent.
    "midnight": {"primary": "E8EEF4", "secondary": "9AA8B5", "accent": "22D3EE",
                 "light": "101418", "bg": "101418"},
    # Clean corporate: white, deep blue ink, sky accent.
    "azure": {"primary": "14337A", "secondary": "4A6591", "accent": "38BDF8",
              "light": "FFFFFF", "bg": "FFFFFF"},
    # Warm editorial: cream, brown/rust ink, orange accent.
    "terra": {"primary": "7C3F21", "secondary": "9A6B4F", "accent": "E8852B",
              "light": "FFF8EE", "bg": "FAF3E7"},
}
DEFAULT_THEME = "ink"


def _resolve_theme(name: object) -> dict[str, RGBColor]:
    """Resolve a preset name to RGBColor roles; anything unknown (or non-string, e.g. the
    legacy {'accent': '#hex'} dict) falls back to the default preset — never crashes."""
    key = name.strip().lower() if isinstance(name, str) else ""
    hexes = THEMES.get(key, THEMES[DEFAULT_THEME])
    t = {role: RGBColor.from_string(h) for role, h in hexes.items()}
    # Text sitting on the (bright) accent: whichever of primary/light is darker.
    t["on_accent"] = min(
        (t["primary"], t["light"]),
        key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2],
    )
    return t


def _rect(slide, left, top, width, height, color):
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def _text(slide, left, top, width, height, *, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    return box, tf, p


def _run(paragraph, text, *, size, color, bold=False, italic=False):
    r = paragraph.add_run()
    r.text = str(text)
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    r.font.color.rgb = color
    return r


def _accent_underline(slide, t, *, top):
    """Short accent underline bar under a heading (~1.2in x 4pt)."""
    return _rect(slide, _MARGIN, top, Inches(1.2), Pt(4), t["accent"])


def _page_badge(slide, number, t):
    """Small accent-filled rectangle with the page number, bottom-right."""
    w, h = Inches(0.55), Inches(0.32)
    shp = _rect(slide, _W - Inches(0.85), _H - Inches(0.57), w, h, t["accent"])
    tf = shp.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for attr in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, attr, 0)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    _run(p, str(number), size=_T_CAPTION, color=t["on_accent"], bold=True)


def _bullet_list(slide, items, t, *, left, top, width, height):
    """Bullets in primary; items prefixed '- ' or indented render as sub-bullets in secondary."""
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        text = str(item)
        sub = text.startswith(("- ", "  "))
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(10)
        if sub:
            _run(p, f"     –  {text.lstrip('- ').strip()}", size=_T_SUB, color=t["secondary"])
        else:
            _run(p, f"•  {text}", size=_T_BODY, color=t["primary"])
    return box


def _heading(slide, title, t):
    """Content-slide heading: 32pt primary + short accent underline bar."""
    _, _, p = _text(slide, _MARGIN, Inches(0.55), _CONTENT_W, Inches(0.9))
    _run(p, title or "", size=_T_HEADING, color=t["primary"], bold=True)
    _accent_underline(slide, t, top=Inches(1.42))


def _title_slide(slide, s, t):
    # Full-bleed primary band across the lower-middle third; title in light on the band.
    band_top, band_h = Inches(3.1), Inches(2.7)
    _rect(slide, 0, band_top, _W, band_h, t["primary"])
    # Small accent eyebrow bar above the title.
    _rect(slide, _MARGIN, band_top + Inches(0.45), Inches(1.4), Inches(0.09), t["accent"])
    _, _, p = _text(slide, _MARGIN, band_top + Inches(0.75), _CONTENT_W, Inches(1.5))
    _run(p, s.get("title") or "", size=_T_TITLE, color=t["light"], bold=True)
    if s.get("subtitle"):
        _, _, sp = _text(slide, _MARGIN, band_top + band_h + Inches(0.25), _CONTENT_W, Inches(0.8))
        _run(sp, s["subtitle"], size=_T_BODY, color=t["secondary"])


def _section_slide(slide, s, t, number):
    # Big section number in accent, oversize title in primary, thin accent rule between.
    _, _, np = _text(slide, _MARGIN, Inches(1.0), _CONTENT_W, Inches(2.2))
    _run(np, f"{number:02d}", size=96, color=t["accent"], bold=True)
    _rect(slide, _MARGIN, Inches(3.35), Inches(2.4), Pt(3), t["accent"])
    _, _, p = _text(slide, _MARGIN, Inches(3.7), _CONTENT_W, Inches(1.6))
    _run(p, s.get("title") or "", size=_T_TITLE, color=t["primary"], bold=True)


def _bullets_slide(slide, s, t):
    _heading(slide, s.get("title"), t)
    _bullet_list(slide, s.get("bullets") or [], t,
                 left=_MARGIN, top=Inches(1.95), width=_CONTENT_W, height=Inches(4.7))


def _two_col_slide(slide, s, t):
    _heading(slide, s.get("title"), t)
    gap = Inches(0.7)
    col_w = (_CONTENT_W - gap) / 2
    right_x = _MARGIN + col_w + gap
    # Hairline vertical divider between the columns.
    _rect(slide, _MARGIN + col_w + gap / 2, Inches(1.95), Pt(1), Inches(4.6), t["secondary"])
    body_top = Inches(1.95)
    headers = (s.get("left_title"), s.get("right_title"))
    if any(headers):
        body_top = Inches(2.55)
        for x, header in ((_MARGIN, headers[0]), (right_x, headers[1])):
            if header:
                _, _, hp = _text(slide, x, Inches(1.95), col_w, Inches(0.4))
                _run(hp, str(header).upper(), size=_T_CAPTION + 2, color=t["secondary"], bold=True)
            _rect(slide, x, Inches(2.4), col_w, Pt(1), t["secondary"])  # hairline under header row
    _bullet_list(slide, s.get("left") or [], t,
                 left=_MARGIN, top=body_top, width=col_w, height=Inches(4.2))
    _bullet_list(slide, s.get("right") or [], t,
                 left=right_x, top=body_top, width=col_w, height=Inches(4.2))


def _quote_slide(slide, s, t):
    # Oversized accent quotation mark, quote in primary italic, attribution in secondary.
    _, _, qp = _text(slide, _MARGIN, Inches(0.8), Inches(2.5), Inches(1.8))
    _run(qp, "“", size=120, color=t["accent"], bold=True)
    _, _, p = _text(slide, _MARGIN + Inches(0.3), Inches(2.4), _CONTENT_W - Inches(0.6),
                    Inches(2.6), anchor=MSO_ANCHOR.MIDDLE)
    _run(p, s.get("text") or "", size=_T_QUOTE, color=t["primary"], bold=True, italic=True)
    if s.get("attribution"):
        _, _, ap = _text(slide, _MARGIN + Inches(0.3), Inches(5.3), _CONTENT_W - Inches(0.6),
                         Inches(0.7))
        _run(ap, f"— {s['attribution']}", size=_T_BODY, color=t["secondary"])


def _big_number_slide(slide, s, t):
    # The number huge in primary with an accent underline block, caption in secondary.
    _, _, p = _text(slide, _MARGIN, Inches(1.9), _CONTENT_W, Inches(2.2),
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    _run(p, s.get("value") or "", size=96, color=t["primary"], bold=True)
    _rect(slide, (_W - Inches(2.0)) / 2, Inches(4.35), Inches(2.0), Inches(0.12), t["accent"])
    if s.get("label"):
        _, _, lp = _text(slide, _MARGIN, Inches(4.75), _CONTENT_W, Inches(0.9),
                         align=PP_ALIGN.CENTER)
        _run(lp, s["label"], size=_T_BODY, color=t["secondary"])


_RENDERERS = {
    "title": _title_slide, "section": _section_slide, "bullets": _bullets_slide,
    "two-column": _two_col_slide, "quote": _quote_slide, "big-number": _big_number_slide,
}


def build_deck(spec: dict) -> bytes:
    """Build a .pptx from a validated deck spec and return its bytes. Assumes the spec has
    already passed DeckExecutor validation (layouts in LAYOUTS, bounded counts).
    spec['theme'] is an optional preset name from THEMES; unknown/absent -> default."""
    t = _resolve_theme(spec.get("theme"))

    prs = Presentation()
    prs.slide_width = _W
    prs.slide_height = _H
    blank = prs.slide_layouts[6]  # blank — we place every shape ourselves for full theme control

    section_no = 0
    for idx, s in enumerate(spec["slides"], start=1):
        slide = prs.slides.add_slide(blank)
        bg = slide.background
        bg.fill.solid()
        bg.fill.fore_color.rgb = t["bg"]
        layout = s["layout"]
        if layout == "section":
            section_no += 1
            _section_slide(slide, s, t, section_no)
        else:
            _RENDERERS[layout](slide, s, t)
        if layout != "title":
            _page_badge(slide, idx, t)
        notes = s.get("notes")
        if notes:
            slide.notes_slide.notes_text_frame.text = str(notes)

    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()
