import base64
from io import BytesIO

import pytest
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_FILL

from server.registry.executors import DeckExecutor
from server.services.deck_pptx import DEFAULT_THEME, THEMES

pytestmark = pytest.mark.asyncio

VALID = {
    "title": "AI 2026",
    "slides": [
        {"layout": "title", "title": "AI 2026", "subtitle": "A field briefing"},
        {"layout": "section", "title": "The Landscape"},
        {"layout": "bullets", "title": "Trends", "bullets": ["Agents", "Cheaper inference"], "notes": "speak"},
        {"layout": "two-column", "title": "Bull / Bear", "left": ["up"], "right": ["moats"],
         "left_title": "Bull", "right_title": "Bear"},
        {"layout": "quote", "text": "The future is here.", "attribution": "Gibson"},
        {"layout": "big-number", "value": "92%", "label": "devs using AI"},
    ],
}


def _open(out) -> Presentation:
    assert out["ok"] is True, out.get("error")
    return Presentation(BytesIO(base64.b64decode(out["artifact"]["bytes_b64"])))


def _solid_fills(slide) -> set[RGBColor]:
    """All solid fill colors on a slide's shapes."""
    fills = set()
    for shp in slide.shapes:
        try:
            if shp.fill.type == MSO_FILL.SOLID:
                fills.add(shp.fill.fore_color.rgb)
        except (AttributeError, TypeError):
            continue
    return fills


def _theme_rgb(name: str, role: str) -> RGBColor:
    return RGBColor.from_string(THEMES[name][role])


async def test_render_deck_produces_valid_editable_pptx():
    out = await DeckExecutor().execute(VALID)
    assert out["ok"] is True
    art = out["artifact"]
    assert art["kind"] == "pptx" and art["filename"].endswith(".pptx") and art["slides"] == 6
    # the artifact is a real, re-openable PowerPoint with native shapes (not an image)
    prs = Presentation(BytesIO(base64.b64decode(art["bytes_b64"])))
    assert len(prs.slides._sldIdLst) == 6
    # speaker notes survived, and every slide carries native shapes
    assert prs.slides[2].notes_slide.notes_text_frame.text == "speak"
    assert all(len(s.shapes) >= 1 for s in prs.slides)


async def test_default_theme_ink_applied():
    prs = _open(await DeckExecutor().execute(VALID))
    assert DEFAULT_THEME == "ink"
    # every slide gets the theme background fill
    for slide in prs.slides:
        assert slide.background.fill.fore_color.rgb == _theme_rgb("ink", "bg")
    # title slide carries the primary-color band + accent eyebrow bar
    title_fills = _solid_fills(prs.slides[0])
    assert _theme_rgb("ink", "primary") in title_fills
    assert _theme_rgb("ink", "accent") in title_fills
    # bullets slide carries the accent underline bar (and accent page badge)
    assert _theme_rgb("ink", "accent") in _solid_fills(prs.slides[2])


async def test_explicit_theme_applied():
    spec = dict(VALID, theme="midnight")
    prs = _open(await DeckExecutor().execute(spec))
    assert prs.slides[0].background.fill.fore_color.rgb == _theme_rgb("midnight", "bg")
    title_fills = _solid_fills(prs.slides[0])
    assert _theme_rgb("midnight", "primary") in title_fills
    assert _theme_rgb("midnight", "accent") in _solid_fills(prs.slides[2])


async def test_unknown_theme_falls_back_to_default():
    prs = _open(await DeckExecutor().execute(dict(VALID, theme="vaporwave")))
    assert prs.slides[0].background.fill.fore_color.rgb == _theme_rgb(DEFAULT_THEME, "bg")


async def test_legacy_dict_theme_falls_back_to_default():
    # older callers passed theme={'accent': '#hex'}; must not crash, must fall back
    prs = _open(await DeckExecutor().execute(dict(VALID, theme={"accent": "#2b6ee8"})))
    assert prs.slides[0].background.fill.fore_color.rgb == _theme_rgb(DEFAULT_THEME, "bg")


async def test_all_presets_generate_without_error():
    for name in THEMES:
        prs = _open(await DeckExecutor().execute(dict(VALID, theme=name)))
        assert len(prs.slides._sldIdLst) == 6
        assert prs.slides[0].background.fill.fore_color.rgb == _theme_rgb(name, "bg")


async def test_page_badge_on_all_slides_except_title():
    prs = _open(await DeckExecutor().execute(VALID))
    accent = _theme_rgb("ink", "accent")
    for i, slide in enumerate(prs.slides):
        badge_texts = {
            shp.text_frame.text for shp in slide.shapes
            if shp.has_text_frame and shp.text_frame.text.strip().isdigit()
        }
        if i == 0:
            assert str(i + 1) not in badge_texts  # no page number on the title slide
        else:
            assert str(i + 1) in badge_texts
            assert accent in _solid_fills(slide)


async def test_empty_slides_rejected():
    out = await DeckExecutor().execute({"slides": []})
    assert out["ok"] is False and "non-empty" in out["error"]


async def test_invalid_layout_rejected():
    out = await DeckExecutor().execute({"slides": [{"layout": "carousel", "title": "x"}]})
    assert out["ok"] is False and "invalid layout" in out["error"]


async def test_bullets_overflow_rejected():
    out = await DeckExecutor().execute(
        {"slides": [{"layout": "bullets", "title": "x", "bullets": [str(i) for i in range(99)]}]}
    )
    assert out["ok"] is False and "bullets" in out["error"]


async def test_too_many_slides_rejected():
    out = await DeckExecutor().execute({"slides": [{"layout": "section", "title": "s"}] * 99})
    assert out["ok"] is False and "too many" in out["error"]


async def test_deck_tool_is_registered_and_resolvable():
    from server.registry.executors import EXECUTORS, resolve_executor
    assert "render_deck" in EXECUTORS
    assert await resolve_executor("render_deck") is not None
