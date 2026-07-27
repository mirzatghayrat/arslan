"""T11: a run whose input carried an image must never enter the replay corpus.

WHY IT MATTERS: decision ③A means an image lives for exactly one turn. The
baseline answered while LOOKING at the picture; a replay arm can only see the
"[图片:name]" placeholder. Scoring those two against each other is not a
comparison — and nothing errors, so the promotion gate's fairness disappears
silently. The exclusion lives in build_corpus, which evolution propose and
skill_forge both go through, so one guard serves both.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, Run, Spawn
from server.services import replay_gate


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'c.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as s:
        s.add(Spawn(id=1, name="R", domain_category="research", persona_role="r", system_prompt="p"))
        await s.commit()
    # Every run in this file is replayable as far as the OTHER gate is concerned,
    # so an exclusion can only come from the image rule under test.
    async def _always_replayable(_db, _run_id):
        return True
    monkeypatch.setattr(replay_gate.replay_run, "is_replayable", _always_replayable)
    async with maker() as s:
        yield s
    await engine.dispose()


def _run(**kw):
    base = dict(conversation_id="c1", spawn_id=1, kind="live", epoch=1,
                status="scored", user_message="do the thing")
    base.update(kw)
    return Run(**base)


@pytest.mark.asyncio
async def test_an_image_run_is_excluded_and_a_text_run_is_kept(db):
    """Both halves in ONE test on purpose: asserting only the exclusion is
    satisfied by an implementation that returns an empty corpus for everything.
    """
    db.add(_run(user_message="describe this", has_images=True))
    db.add(_run(user_message="summarise the doc", has_images=False))
    await db.commit()

    corpus = await replay_gate.build_corpus(db, 1)
    tasks = [p["task"] for p in corpus]
    assert "summarise the doc" in tasks
    assert "describe this" not in tasks


@pytest.mark.asyncio
async def test_the_exclusion_is_counted_not_silent(db):
    """A corpus that quietly shrinks is its own hazard — the count is the only
    way anyone can tell why an exam got smaller."""
    db.add(_run(user_message="describe this", has_images=True))
    db.add(_run(user_message="plain task", has_images=False))
    await db.commit()

    corpus = await replay_gate.build_corpus(db, 1)
    assert corpus.excluded == 1


@pytest.mark.asyncio
async def test_rows_predating_the_column_are_kept(db):
    """NULL means "written before the column existed", and image input did not
    exist in any earlier build — treating those as excluded would empty the
    corpus of every historical run."""
    db.add(_run(user_message="legacy task", has_images=None))
    await db.commit()

    corpus = await replay_gate.build_corpus(db, 1)
    assert [p["task"] for p in corpus] == ["legacy task"]
    assert corpus.excluded == 0


@pytest.mark.asyncio
async def test_placeholder_text_alone_does_not_exclude(db):
    """Discrimination against the implementation the spec forbids: sniffing the
    transcript for "[图片:" would exclude a user who merely TYPED that."""
    db.add(_run(user_message="what does [图片:foo.png] mean in this codebase?",
                has_images=False))
    await db.commit()

    corpus = await replay_gate.build_corpus(db, 1)
    assert len(corpus) == 1, "a text run was excluded by text-sniffing"
