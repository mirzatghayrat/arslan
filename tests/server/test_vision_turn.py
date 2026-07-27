"""Stage 2: an attached image reaches the LLM turn, and history stays honest.

Decision ③A (user-approved): an image participates ONLY in the turn it was
sent. `arslan_messages.content` is a Text column, so nothing else is even
storable — the turn is persisted with a `[图片:name]` placeholder instead of
pretending the picture is still there on turn two.

These tests assert the CONTENT HANDED TO THE MODEL, not that the call
succeeded: the whole failure mode this round exists to prevent is an image
that silently becomes text.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.orchestrator import arslan as arslan_mod

IMAGE = {"name": "shot.png", "mime_type": "image/png", "data": "QUJDRA=="}


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'v.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def test_blocks_carry_text_and_image():
    blocks = arslan_mod.build_user_blocks("看看这张图", None, [IMAGE])
    assert blocks[0] == {"type": "text", "text": "看看这张图"}
    img = [b for b in blocks if b["type"] == "image"]
    assert img == [{"type": "image", "mime_type": "image/png", "data": "QUJDRA=="}]


def test_no_images_returns_a_plain_string():
    """Discrimination: the 34 text-only call sites and every text-only turn must
    keep the exact payload they had. Returning a one-element block list here
    would reshape every request in the app for no reason."""
    assert arslan_mod.build_user_blocks("hello", None, []) == "hello"
    assert arslan_mod.build_user_blocks("hello", None, None) == "hello"


def test_attached_text_still_prefixes_the_message():
    out = arslan_mod.build_user_blocks("问题", "材料正文", [])
    assert isinstance(out, str)
    assert "材料正文" in out and "问题" in out


def test_attached_text_and_image_coexist():
    blocks = arslan_mod.build_user_blocks("问题", "材料正文", [IMAGE])
    text = "".join(b.get("text", "") for b in blocks if b["type"] == "text")
    assert "材料正文" in text and "问题" in text
    assert any(b["type"] == "image" for b in blocks)


def test_history_placeholder_names_the_file():
    """③A: what gets PERSISTED is the placeholder, so turn two does not claim to
    still hold a picture it cannot hold."""
    assert arslan_mod.persisted_user_text("看看", [IMAGE]) == "看看\n[图片:shot.png]"
    assert arslan_mod.persisted_user_text("看看", []) == "看看"


@pytest.mark.asyncio
async def test_the_persisted_turn_never_contains_base64(maker):
    """The failure this guards: stuffing the image into the Text column would
    'work' and quietly bloat the DB and every backup."""
    from server.orchestrator import memory

    await memory.add_message("c1", "user", arslan_mod.persisted_user_text("看看", [IMAGE]))
    async with maker() as s:
        row = (await s.execute(sa_text(
            "SELECT content FROM arslan_messages ORDER BY id DESC LIMIT 1"))).scalar_one()
    assert "QUJDRA==" not in row
    assert "shot.png" in row


def test_every_material_carrying_answer_call_also_carries_images():
    """The threading is mechanical and therefore easy to get PARTIALLY right —
    which is the worst outcome: an image silently vanishes on whichever branch
    the router happened to take (clarify, staffing, route…), and the model
    answers about a picture it never saw.

    So assert the INVARIANT rather than the individual sites: wherever the
    turn's attached material flows, the turn's images flow with it.
    """
    import pathlib
    import re

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "server" / "orchestrator" / "arslan.py").read_text()

    # Every call expression that passes attached_context=attached_context.
    offenders = []
    for m in re.finditer(r"(\w+)\(", src):
        start = m.end()
        depth, i = 1, start
        while depth and i < len(src):
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
            i += 1
        call = src[m.start():i]
        if "attached_context=attached_context" in call and "images=" not in call:
            offenders.append(m.group(1))
    # The spawn gap is CLOSED: dispatcher.with_images puts images on the user
    # turn while attached TEXT keeps its route into the system prompt. The set
    # stays here, empty, because it is the mechanism that made the gap visible
    # while it existed — and a future omission has to land somewhere.
    SPAWN_PATH_GAP: set[str] = set()
    fresh = sorted(set(offenders) - SPAWN_PATH_GAP)
    assert not fresh, (
        f"these calls forward the turn's attached material but drop its images: {fresh}"
    )
    stale = sorted(SPAWN_PATH_GAP - set(offenders))
    assert not stale, (
        f"these now carry images — delete them from SPAWN_PATH_GAP: {stale}"
    )
