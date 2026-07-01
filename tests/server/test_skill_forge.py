import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillCandidate, SkillPack

_GOOD_BODY = (
    "# My Skill\n\n"
    "## Trigger\nUse this when the user asks to do the thing.\n\n"
    "## Steps\n1. Do the first thing.\n2. Do the second thing thoroughly and well.\n"
)


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'sf.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_seed)
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
async def test_create_candidate_status_observing(maker):
    from server.services import skill_forge

    cand = await skill_forge.create_candidate(
        key="my-skill", name="My Skill", category="meta",
        description="does a thing", body=_GOOD_BODY,
    )
    assert cand.status == "observing"
    assert cand.source == "skill_creator"
    listed = await skill_forge.list_candidates()
    assert [c.id for c in listed] == [cand.id]
    assert [c.id for c in await skill_forge.list_candidates(status="observing")] == [cand.id]
    assert await skill_forge.list_candidates(status="promoted") == []


@pytest.mark.asyncio
async def test_create_candidate_raises_on_invalid(maker):
    from server.services import skill_forge

    with pytest.raises(ValueError):
        await skill_forge.create_candidate(
            key="", name="", category="meta", description="", body="too short",
        )


@pytest.mark.asyncio
async def test_promote_makes_a_real_assignable_skillpack(maker):
    from server.registry import service as registry_service
    from server.services import skill_forge

    cand = await skill_forge.create_candidate(
        key="my-skill", name="My Skill", category="meta",
        description="does a thing", body=_GOOD_BODY,
    )
    result = await skill_forge.promote_candidate(cand.id)
    assert result == {"ok": True, "key": "my-skill"}

    # A real, live SkillPack row now exists, tier=safe / status=registered / body set.
    async with maker() as s:
        pack = await s.get(SkillPack, "my-skill")
        assert pack is not None
        assert pack.tier == "safe"
        assert pack.status == "registered"
        assert pack.body == _GOOD_BODY
        assert pack.category == "meta"
        got = await s.get(SkillCandidate, cand.id)
        assert got.status == "promoted"
        assert got.promoted_at is not None

    # Proof it is equippable: the registry choke point accepts it.
    await registry_service.assert_assignable("skill", "my-skill")


@pytest.mark.asyncio
async def test_create_refuses_dup_live_key(maker):
    from server.services import skill_forge

    cand = await skill_forge.create_candidate(
        key="my-skill", name="My Skill", category="meta",
        description="does a thing", body=_GOOD_BODY,
    )
    await skill_forge.promote_candidate(cand.id)
    with pytest.raises(ValueError, match="already exists"):
        await skill_forge.create_candidate(
            key="my-skill", name="Dup", category="meta",
            description="dup", body=_GOOD_BODY,
        )


@pytest.mark.asyncio
async def test_create_refuses_dup_inflight_candidate(maker):
    from server.services import skill_forge

    await skill_forge.create_candidate(
        key="my-skill", name="My Skill", category="meta",
        description="does a thing", body=_GOOD_BODY,
    )
    with pytest.raises(ValueError, match="in progress"):
        await skill_forge.create_candidate(
            key="my-skill", name="Again", category="meta",
            description="again", body=_GOOD_BODY,
        )


@pytest.mark.asyncio
async def test_reject_sets_status_rejected(maker):
    from server.services import skill_forge

    cand = await skill_forge.create_candidate(
        key="my-skill", name="My Skill", category="meta",
        description="does a thing", body=_GOOD_BODY,
    )
    assert await skill_forge.reject_candidate(cand.id) == {"ok": True}
    async with maker() as s:
        got = await s.get(SkillCandidate, cand.id)
        assert got.status == "rejected"
    # A rejected key frees up: a fresh candidate can be created again.
    again = await skill_forge.create_candidate(
        key="my-skill", name="My Skill", category="meta",
        description="does a thing", body=_GOOD_BODY,
    )
    assert again.status == "observing"


@pytest.mark.asyncio
async def test_promote_unknown_returns_not_ok(maker):
    from server.services import skill_forge

    assert (await skill_forge.promote_candidate(9999))["ok"] is False


@pytest.mark.asyncio
async def test_promote_terminal_returns_not_ok(maker):
    from server.services import skill_forge

    cand = await skill_forge.create_candidate(
        key="my-skill", name="My Skill", category="meta",
        description="does a thing", body=_GOOD_BODY,
    )
    await skill_forge.reject_candidate(cand.id)
    result = await skill_forge.promote_candidate(cand.id)
    assert result["ok"] is False
    assert "rejected" in result["reason"]
