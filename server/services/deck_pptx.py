"""Native .pptx generation from a validated deck spec (python-pptx).

Safe by construction, exactly like render_chart: the model supplies a normalized DATA spec
(slides + content + a closed set of layout intents), never code. We build the PowerPoint from
that spec. No shell, no network, no untrusted-file parsing (v1 ships clean themed decks;
template-following is deferred to v2). Output is a real, natively-editable .pptx (shapes + text
frames + speaker notes) — not slide images.

Inspired by hugohe3/ppt-master (MIT) for the "native editable shapes, not images" approach; no
code was vendored — this is a thin renderer on python-pptx. See THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations

from io import BytesIO

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

LAYOUTS = {"title", "section", "bullets", "two-column", "quote", "big-number"}

# 16:9 canvas.
_W = Inches(13.333)
_H = Inches(7.5)
_MARGIN = Inches(0.9)
_CONTENT_W = _W - _MARGIN * 2

_INK = "1A1A1A"       # near-black body text
_MUTED = "5A5A62"     # secondary text
_PAPER = "FFFFFF"     # slide background (light, print/present-friendly)
_DEFAULT_ACCENT = "E8852B"  # Arslan orange


def _rgb(value: str | None, fallback: str) -> RGBColor:
    s = (value or "").lstrip("#").upper()
    if len(s) == 6:
        try:
            return RGBColor.from_string(s)
        except ValueError:
            pass
    return RGBColor.from_string(fallback)


def _text(slide, left, top, width, height, *, size, color, bold=False,
          align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    return box, tf, p


def _run(paragraph, text, *, size, color, bold=False):
    r = paragraph.add_run()
    r.text = str(text)
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    return r


def _accent_bar(slide, accent, *, top):
    bar = slide.shapes.add_textbox(_MARGIN, top, Inches(1.1), Pt(6))
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent
    bar.line.fill.background()
    return bar


def _bullet_list(slide, items, *, left, top, width, height, color, size=18):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(10)
        _run(p, f"•  {item}", size=size, color=color)
    return box


def _title_slide(slide, s, accent, ink, muted):
    _accent_bar(slide, accent, top=Inches(2.7))
    _, _, p = _text(slide, _MARGIN, Inches(2.9), _CONTENT_W, Inches(1.8),
                    size=44, color=ink, bold=True, anchor=MSO_ANCHOR.TOP)
    _run(p, s.get("title") or "", size=44, color=ink, bold=True)
    if s.get("subtitle"):
        _, _, sp = _text(slide, _MARGIN, Inches(4.5), _CONTENT_W, Inches(1.0), size=20, color=muted)
        _run(sp, s["subtitle"], size=20, color=muted)


def _section_slide(slide, s, accent):
    bg = slide.shapes.add_textbox(0, 0, _W, _H)
    bg.fill.solid()
    bg.fill.fore_color.rgb = accent
    bg.line.fill.background()
    _, _, p = _text(slide, _MARGIN, Inches(3.0), _CONTENT_W, Inches(1.5),
                    size=40, color=RGBColor.from_string("FFFFFF"), bold=True, anchor=MSO_ANCHOR.MIDDLE)
    _run(p, s.get("title") or "", size=40, color=RGBColor.from_string("FFFFFF"), bold=True)


def _heading(slide, title, accent, ink):
    _accent_bar(slide, accent, top=Inches(0.75))
    _, _, p = _text(slide, _MARGIN, Inches(0.95), _CONTENT_W, Inches(1.0), size=28, color=ink, bold=True)
    _run(p, title or "", size=28, color=ink, bold=True)


def _bullets_slide(slide, s, accent, ink):
    _heading(slide, s.get("title"), accent, ink)
    _bullet_list(slide, s.get("bullets") or [], left=_MARGIN, top=Inches(2.1),
                 width=_CONTENT_W, height=Inches(4.8), color=RGBColor.from_string(_INK))


def _two_col_slide(slide, s, accent, ink):
    _heading(slide, s.get("title"), accent, ink)
    col_w = (_CONTENT_W - Inches(0.6)) / 2
    _bullet_list(slide, s.get("left") or [], left=_MARGIN, top=Inches(2.1),
                 width=col_w, height=Inches(4.8), color=RGBColor.from_string(_INK))
    _bullet_list(slide, s.get("right") or [], left=_MARGIN + col_w + Inches(0.6), top=Inches(2.1),
                 width=col_w, height=Inches(4.8), color=RGBColor.from_string(_INK))


def _quote_slide(slide, s, accent, ink, muted):
    _, _, p = _text(slide, _MARGIN, Inches(2.2), _CONTENT_W, Inches(2.8),
                    size=32, color=ink, anchor=MSO_ANCHOR.MIDDLE)
    _run(p, f"“{s.get('text') or ''}”", size=32, color=ink, bold=True)
    if s.get("attribution"):
        _, _, ap = _text(slide, _MARGIN, Inches(5.2), _CONTENT_W, Inches(0.8), size=18, color=muted)
        _run(ap, f"— {s['attribution']}", size=18, color=muted)


def _big_number_slide(slide, s, accent, ink, muted):
    _, _, p = _text(slide, _MARGIN, Inches(2.2), _CONTENT_W, Inches(2.2),
                    size=96, color=accent, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    _run(p, s.get("value") or "", size=96, color=accent, bold=True)
    if s.get("label"):
        _, _, lp = _text(slide, _MARGIN, Inches(4.6), _CONTENT_W, Inches(1.0), size=22, color=muted,
                         align=PP_ALIGN.CENTER)
        _run(lp, s["label"], size=22, color=muted)


_RENDERERS = {
    "title": _title_slide, "section": _section_slide, "bullets": _bullets_slide,
    "two-column": _two_col_slide, "quote": _quote_slide, "big-number": _big_number_slide,
}


def build_deck(spec: dict) -> bytes:
    """Build a .pptx from a validated deck spec and return its bytes. Assumes the spec has
    already passed DeckExecutor validation (layouts in LAYOUTS, bounded counts)."""
    accent = _rgb((spec.get("theme") or {}).get("accent"), _DEFAULT_ACCENT)
    ink = RGBColor.from_string(_INK)
    muted = RGBColor.from_string(_MUTED)

    prs = Presentation()
    prs.slide_width = _W
    prs.slide_height = _H
    blank = prs.slide_layouts[6]  # blank — we place every shape ourselves for full theme control

    for s in spec["slides"]:
        slide = prs.slides.add_slide(blank)
        bg = slide.background
        bg.fill.solid()
        bg.fill.fore_color.rgb = RGBColor.from_string(_PAPER)
        renderer = _RENDERERS[s["layout"]]
        # section paints its own full-bleed background; others keep the paper bg.
        if s["layout"] == "section":
            renderer(slide, s, accent)
        elif s["layout"] in ("title", "quote", "big-number"):
            renderer(slide, s, accent, ink, muted)
        else:
            renderer(slide, s, accent, ink)
        notes = s.get("notes")
        if notes:
            slide.notes_slide.notes_text_frame.text = str(notes)

    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()
