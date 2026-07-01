import base64
from io import BytesIO

import pytest
from pptx import Presentation

from server.registry.executors import DeckExecutor

pytestmark = pytest.mark.asyncio

VALID = {
    "title": "AI 2026",
    "theme": {"accent": "#2b6ee8"},
    "slides": [
        {"layout": "title", "title": "AI 2026", "subtitle": "A field briefing"},
        {"layout": "section", "title": "The Landscape"},
        {"layout": "bullets", "title": "Trends", "bullets": ["Agents", "Cheaper inference"], "notes": "speak"},
        {"layout": "two-column", "title": "Bull / Bear", "left": ["up"], "right": ["moats"]},
        {"layout": "quote", "text": "The future is here.", "attribution": "Gibson"},
        {"layout": "big-number", "value": "92%", "label": "devs using AI"},
    ],
}


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
