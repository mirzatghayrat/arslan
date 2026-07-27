"""The last disclosed gap: a spawn can now see the images of the turn it was
dispatched for.

The reason this needed its own route rather than reusing `attached_context`:
that material is folded into the SYSTEM prompt (dispatcher.py), and an image
block cannot live there — Anthropic and Gemini both require images in the user
turn. So text keeps going to system and images ride the user content.
"""
from __future__ import annotations

from server.orchestrator import dispatcher

IMAGE = {"name": "shot.png", "mime_type": "image/png", "data": "QUJD"}


def test_images_ride_the_user_turn_as_blocks():
    out = dispatcher.with_images("do the thing", [IMAGE])
    assert isinstance(out, list)
    assert out[0] == {"type": "text", "text": "do the thing"}
    assert {"type": "image", "mime_type": "image/png", "data": "QUJD"} in out


def test_no_images_leaves_the_brief_a_plain_string():
    """Discrimination: every text-only dispatch must keep the exact payload it
    had. Wrapping it in a one-element block list would reshape every spawn call
    in the app for a feature it is not using."""
    assert dispatcher.with_images("do the thing", []) == "do the thing"
    assert dispatcher.with_images("do the thing", None) == "do the thing"


def test_images_never_go_into_the_system_prompt():
    """The mistake this route exists to avoid. `attached_context` (TEXT) is
    appended to system; images must not follow it there, or two of the three
    providers reject or ignore them."""
    import inspect

    src = inspect.getsource(dispatcher)
    # the system-append line must still be about attached_context only
    assert 'system += f"\\n\\n[用户附带的临时材料]\\n{attached_context}"' in src
    # and nothing may append images to system
    assert "system += " not in src.replace(
        'system += f"\\n\\n[用户附带的临时材料]\\n{attached_context}"', "", 1
    ) or "images" not in src.split("system += ")[-1][:200]


# ── the wiring, not just the helper ──────────────────────────────────────────
# A mutation proved the tests above pass even when dispatch never CALLS
# with_images: they cover the pure function and the call-site inventory, and
# neither notices that the result is dropped. This exercises the real dispatch
# and captures what the model was actually handed.

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

import server.db.session as db_session  # noqa: E402
from server.db.models import Base, Spawn  # noqa: E402


class _CapturingAdapter:
    """Records the user content the dispatcher hands the model."""

    seen: list = []

    async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
        _CapturingAdapter.seen.append({"system": system, "user": user})
        yield "ok"


@pytest_asyncio.fixture
async def spawn_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'sv.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    async with maker() as s:
        s.add(Spawn(id=1, name="R", domain_category="research",
                    persona_role="r", system_prompt="p"))
        await s.commit()
    _CapturingAdapter.seen = []
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _CapturingAdapter())
    return maker


@pytest.mark.asyncio
async def test_dispatch_actually_hands_the_image_to_the_model(spawn_db):
    await dispatcher.dispatch("c1", spawn_id=1, task_brief="read this",
                              images=[IMAGE], persist=False)
    assert _CapturingAdapter.seen, "the model was never called"
    user = _CapturingAdapter.seen[-1]["user"]
    assert isinstance(user, list), f"image dropped — model got {type(user).__name__}"
    assert any(b.get("type") == "image" for b in user)


@pytest.mark.asyncio
async def test_the_image_is_not_smuggled_into_the_system_prompt(spawn_db):
    """Anthropic and Gemini require images in the user turn; a system-prompt
    'fix' would look plausible and fail against two of three providers."""
    await dispatcher.dispatch("c1", spawn_id=1, task_brief="read this",
                              images=[IMAGE], persist=False)
    system = _CapturingAdapter.seen[-1]["system"]
    assert IMAGE["data"] not in str(system)


@pytest.mark.asyncio
async def test_a_text_only_dispatch_still_sends_a_plain_string(spawn_db):
    await dispatcher.dispatch("c1", spawn_id=1, task_brief="just text", persist=False)
    assert isinstance(_CapturingAdapter.seen[-1]["user"], str)


@pytest.mark.asyncio
async def test_a_refinement_dispatch_keeps_the_images(spawn_db):
    """The partial application this test exists to prevent: with_images applied
    only in the else-branch would drop images on exactly the path where the user
    says "no — look at the picture again"."""
    await dispatcher.dispatch("c1", spawn_id=1, task_brief="read this",
                              prior_output="first attempt", instruction="try again",
                              images=[IMAGE], persist=False)
    user = _CapturingAdapter.seen[-1]["user"]
    assert isinstance(user, list), "refinement dropped the image"
    assert any(b.get("type") == "image" for b in user)
