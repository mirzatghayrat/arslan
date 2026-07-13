import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillPack

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def seeded(tmp_path, monkeypatch):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with m() as db:
        db.add(SkillPack(key="writing-plans", name="Writing Plans", category="dev",
                         description="d", tier="safe", status="registered",
                         body="## First\nalpha\n## Second\n" + "beta " * 4000))
        db.add(SkillPack(key="short", name="Short", category="dev", description="d",
                         tier="safe", status="registered", body="tiny"))
        await db.commit()

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def test_full_short_returns_whole(seeded):
    from server.registry.executors import ReadSkillExecutor
    out = await ReadSkillExecutor().execute({"key": "short"})
    assert out["ok"] and "tiny" in out["body"]


async def test_full_long_caps_and_hints(seeded):
    from server.registry.executors import ReadSkillExecutor
    out = await ReadSkillExecutor().execute({"key": "writing-plans"})
    assert out["ok"] and len(out["body"]) <= 8600
    assert "按章节读取" in out["body"] and "## Second" in out["body"]


async def test_section_returns_only_that(seeded):
    from server.registry.executors import ReadSkillExecutor
    out = await ReadSkillExecutor().execute({"key": "writing-plans", "section": "## First"})
    assert out["ok"] and "alpha" in out["body"] and "beta" not in out["body"]


async def test_unknown_key_fails(seeded):
    from server.registry.executors import ReadSkillExecutor
    out = await ReadSkillExecutor().execute({"key": "../etc/passwd"})
    assert out["ok"] is False


async def test_section_read_is_capped(seeded):
    """FIX 3: a single very large ## section must be capped like the other branches
    (writing-plans '## Second' body is ~20k chars of 'beta ')."""
    from server.registry.executors import ReadSkillExecutor
    out = await ReadSkillExecutor().execute({"key": "writing-plans", "section": "## Second"})
    assert out["ok"]
    assert len(out["body"]) <= ReadSkillExecutor._READ_SKILL_CAP + 60
    assert "已截断" in out["body"]


async def test_non_utf8_reference_does_not_crash(seeded, tmp_path, monkeypatch):
    """FIX 4: a non-UTF-8 bundled reference must return an honest ok result with replaced
    bytes, never raise UnicodeDecodeError."""
    from server.registry.executors import ReadSkillExecutor
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    refs = tmp_path / "skill_scripts" / "writing-plans" / "references"
    refs.mkdir(parents=True)
    (refs / "bad.md").write_bytes(b"ok text \xff\xfe more")
    out = await ReadSkillExecutor().execute(
        {"key": "writing-plans", "section": "references/bad.md"})
    assert out["ok"] is True
    assert "ok text" in out["body"]        # readable prefix survives (errors='replace')
