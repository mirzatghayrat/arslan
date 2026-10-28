import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillPack

_GOOD_BODY = (
    "# My Skill\n\n"
    "## Trigger\nUse this when the user asks to do the thing.\n\n"
    "## Steps\n1. Do the first thing.\n2. Do the second thing thoroughly and well.\n"
)


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'sf.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def test_validate_rejects_oversize_body():
    from server.services import skill_forge

    big = "## Trigger\n" + ("x" * (skill_forge.MAX_SKILL_BYTES + 10))
    errors = skill_forge.validate("k", "Name", "desc", big)
    assert any("KB" in e for e in errors)


def test_validate_rejects_missing_trigger():
    from server.services import skill_forge

    errors = skill_forge.validate("k", "Name", "desc", "no trigger section here " * 10)
    assert any("Trigger" in e for e in errors)


def test_validate_rejects_bad_key():
    from server.services import skill_forge

    errors = skill_forge.validate("Bad Key", "Name", "desc", _GOOD_BODY)
    assert any("key" in e for e in errors)


def test_validate_passes_good_input():
    from server.services import skill_forge

    assert skill_forge.validate("my-skill", "My Skill", "does a thing", _GOOD_BODY) == []


@pytest.mark.asyncio
async def test_register_makes_a_real_assignable_skill_marked_as_the_users(maker):
    """CAP2a: the card's yes (or converting a former expert) writes the skill itself; no candidate."""
    from server.registry import service as registry_service
    from server.services import skill_forge

    assert await skill_forge.register(key="my-skill", name="My Skill", description="does a thing",
                                      body=_GOOD_BODY) is True
    async with maker() as s:
        pack = await s.get(SkillPack, "my-skill")
        assert (pack.tier, pack.status, pack.enabled, pack.body) == ("safe", "registered", True, _GOOD_BODY)
        assert pack.category == skill_forge.AUTHORED and pack.source_id is None
    await registry_service.assert_assignable("skill", "my-skill")


@pytest.mark.asyncio
async def test_register_never_overwrites_a_skill_of_that_key(maker):
    from server.services import skill_forge

    async with maker() as s:
        s.add(SkillPack(key="taken", name="Theirs", category="imported", description="d", tier="safe",
                        status="registered", body=_GOOD_BODY))
        await s.commit()
    assert await skill_forge.register(key="taken", name="Mine", description="x", body=_GOOD_BODY) is False
    async with maker() as s:
        pack = await s.get(SkillPack, "taken")
        assert (pack.name, pack.category) == ("Theirs", "imported")


def test_the_candidate_functions_are_gone():
    """sessions.md §11: the Skill Forge page went, and its candidate lifecycle with it."""
    from server.services import skill_forge

    for name in ("create_candidate", "promote_candidate", "reject_candidate", "list_candidates"):
        assert not hasattr(skill_forge, name), name
