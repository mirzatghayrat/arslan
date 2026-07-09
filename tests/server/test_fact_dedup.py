"""Exact-normalized fact dedup: backfill keeps earliest; write-time skips dups."""
import anyio
import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import server.db.session as db_session
from server.db.models import Base, UserFact


@pytest.fixture
def maker(tmp_path, monkeypatch):
    # NullPool: the fail-open tests raise mid-operation; with a pooled connection the
    # aborted transaction can linger and later writes hit "database is locked" under CI
    # load (flaky). A fresh connection per use releases the file lock deterministically.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d.db'}", poolclass=NullPool)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    anyio.run(_seed)
    return m


def test_norm_collapses_whitespace_and_ascii_case():
    from server.services.fact_dedup import norm
    assert norm("  Hello   World ") == norm("hello world")
    assert norm("用户 想建 分身") == "用户 想建 分身"


def test_dedup_keeps_earliest_of_each_group(maker):
    from server.services import fact_dedup
    async def _run():
        async with maker() as s:
            for c in ["建 GitHub 分身", "建 GitHub 分身", "  建 GitHub 分身 ", "别的偏好"]:
                s.add(UserFact(content=c, source="auto"))
            await s.commit()
        return await fact_dedup.dedup_facts()
    deleted = anyio.run(_run)
    assert deleted == 2
    async def _left():
        async with maker() as s:
            rows = (await s.execute(sa_text("SELECT id, content FROM user_facts ORDER BY id"))).all()
            return rows
    left = anyio.run(_left)
    assert [r[0] for r in left] == [1, 4]


def test_write_time_skip_existing(maker):
    from server.orchestrator import memory
    anyio.run(lambda: memory.add_manual_fact("建 GitHub 分身"))
    anyio.run(lambda: memory.add_manual_fact("  建 GitHub 分身  "))  # normalized dup → skipped
    async def _count():
        async with maker() as s:
            return (await s.execute(sa_text("SELECT COUNT(*) FROM user_facts"))).scalar_one()
    assert anyio.run(_count) == 1


def _count_facts(maker):
    async def _c():
        async with maker() as s:
            return (await s.execute(sa_text("SELECT COUNT(*) FROM user_facts"))).scalar_one()
    return anyio.run(_c)


def test_fail_open_when_norm_raises(maker, monkeypatch):
    """Safety rule: if the dedup check itself throws, the write must still succeed.
    Patch norm to blow up; a would-be duplicate must still get inserted (dedup
    silently skipped, never the write)."""
    from server.orchestrator import memory

    def boom(_content):
        raise RuntimeError("norm exploded")

    monkeypatch.setattr("server.services.fact_dedup.norm", boom)
    # add_manual_fact: two identical facts — dedup broken → BOTH written (fail-open)
    r1 = anyio.run(lambda: memory.add_manual_fact("建 GitHub 分身"))
    r2 = anyio.run(lambda: memory.add_manual_fact("建 GitHub 分身"))
    assert r1 is not None and r2 is not None  # always returns a row, never None
    # save_facts: two identical auto facts — dedup broken → BOTH written
    anyio.run(lambda: memory.save_facts([
        {"content": "别的偏好"}, {"content": "别的偏好"},
    ]))
    assert _count_facts(maker) == 4  # 2 manual + 2 auto, nothing dropped


def test_fail_open_when_existing_norms_raises(maker, monkeypatch):
    """Safety rule: if the store-lookup for existing norms throws, writes proceed.
    existing_norms_safe swallows it → empty set → dedup skipped, write survives."""
    from server.orchestrator import memory

    async def boom():
        raise RuntimeError("db lookup exploded")

    monkeypatch.setattr("server.services.fact_dedup.existing_norms", boom)
    # Two identical manual facts: cross-store dedup lookup is broken, so the second
    # (normally deduped against the stored first) must still be written — fail-open.
    r1 = anyio.run(lambda: memory.add_manual_fact("建 GitHub 分身"))
    r2 = anyio.run(lambda: memory.add_manual_fact("建 GitHub 分身"))
    assert r1 is not None and r2 is not None
    assert _count_facts(maker) == 2  # both written; the store-lookup failure never blocked a write
    # (save_facts' intra-batch dedup via the local `seen` set is unaffected here —
    # only the store lookup fails — so we assert only the cross-store fail-open above.)
    anyio.run(lambda: memory.save_facts([{"content": "别的偏好"}]))
    assert _count_facts(maker) == 3
