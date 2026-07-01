"""Curator (create_skill Slice 3): post-promotion hygiene for self-authored skills.

Reviews PROMOTED SkillCandidates against their equipped spawns' real runs and
flags unused / underperforming ones; a human then retires flagged ones (sets the
SkillPack non-assignable, marks the candidate retired, unassigns from all spawns).
"""
from datetime import datetime, timedelta

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import (
    Base,
    Run,
    SkillCandidate,
    SkillPack,
    SpawnCapability,
)


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'curator.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def _seed_promoted(maker, *, key="my-skill", promoted_at=None):
    """Insert a promoted candidate + its live SkillPack. Returns nothing."""
    async with maker() as s:
        s.add(SkillPack(key=key, name="My Skill", category="meta",
                        description="d", tier="safe", status="registered", body="b"))
        s.add(SkillCandidate(
            key=key, name="My Skill", category="meta", description="d", body="b",
            source="skill_creator", status="promoted",
            promoted_at=promoted_at or datetime.utcnow(),
        ))
        await s.commit()


async def _equip(maker, spawn_id: int, key: str):
    async with maker() as s:
        s.add(SpawnCapability(spawn_id=spawn_id, kind="skill", ref_key=key,
                              grant="permanent", granted_by="user"))
        await s.commit()


async def _add_runs(maker, spawn_id: int, scores: list, *, at=None):
    async with maker() as s:
        for sc in scores:
            s.add(Run(conversation_id="c", spawn_id=spawn_id, user_message="",
                      status="scored", overall_score=sc,
                      created_at=at or datetime.utcnow()))
        await s.commit()


@pytest.mark.asyncio
async def test_unused_flag(maker):
    from server.services import curator

    old = datetime.utcnow() - timedelta(days=30)
    await _seed_promoted(maker, promoted_at=old)
    await _equip(maker, 1, "my-skill")
    # No runs at all since promotion → unused.
    review = await curator.review_promoted_skills()
    assert len(review) == 1
    row = review[0]
    assert row["key"] == "my-skill"
    assert row["usage"] == 0
    assert row["avg_score"] is None
    assert row["flag"] == "unused"
    assert "no runs" in row["reason"]
    assert row["equipped_spawns"] == 1


@pytest.mark.asyncio
async def test_unused_within_grace_not_flagged(maker):
    from server.services import curator

    # Promoted just now, 0 runs → within grace period → NOT flagged yet.
    await _seed_promoted(maker, promoted_at=datetime.utcnow())
    await _equip(maker, 1, "my-skill")
    review = await curator.review_promoted_skills()
    assert review[0]["flag"] is None


@pytest.mark.asyncio
async def test_underperforming_flag(maker):
    from server.services import curator

    old = datetime.utcnow() - timedelta(days=30)
    await _seed_promoted(maker, promoted_at=old)
    await _equip(maker, 1, "my-skill")
    # 6 scored runs, avg < 5 → underperforming.
    await _add_runs(maker, 1, [2.0, 3.0, 4.0, 4.5, 3.5, 4.0])
    review = await curator.review_promoted_skills()
    row = review[0]
    assert row["usage"] == 6
    assert row["avg_score"] == round(sum([2.0, 3.0, 4.0, 4.5, 3.5, 4.0]) / 6, 2)
    assert row["flag"] == "underperforming"
    assert "avg score" in row["reason"]


@pytest.mark.asyncio
async def test_underperforming_needs_min_runs(maker):
    from server.services import curator

    old = datetime.utcnow() - timedelta(days=30)
    await _seed_promoted(maker, promoted_at=old)
    await _equip(maker, 1, "my-skill")
    # Only 3 scored runs (avg < 5 but below MIN_RUNS_FOR_QUALITY) → no quality flag.
    await _add_runs(maker, 1, [1.0, 2.0, 3.0])
    review = await curator.review_promoted_skills()
    assert review[0]["flag"] is None


@pytest.mark.asyncio
async def test_healthy_not_flagged(maker):
    from server.services import curator

    old = datetime.utcnow() - timedelta(days=30)
    await _seed_promoted(maker, promoted_at=old)
    await _equip(maker, 1, "my-skill")
    await _add_runs(maker, 1, [8.0, 7.5, 9.0, 8.5, 7.0, 8.0])
    review = await curator.review_promoted_skills()
    row = review[0]
    assert row["usage"] == 6
    assert row["avg_score"] == round(sum([8.0, 7.5, 9.0, 8.5, 7.0, 8.0]) / 6, 2)
    assert row["flag"] is None
    assert row["reason"] is None


@pytest.mark.asyncio
async def test_runs_before_promotion_ignored(maker):
    from server.services import curator

    promoted = datetime.utcnow() - timedelta(days=10)
    await _seed_promoted(maker, promoted_at=promoted)
    await _equip(maker, 1, "my-skill")
    # Runs BEFORE promotion don't count toward usage.
    await _add_runs(maker, 1, [8.0, 9.0], at=promoted - timedelta(days=5))
    review = await curator.review_promoted_skills()
    assert review[0]["usage"] == 0
    assert review[0]["flag"] == "unused"


@pytest.mark.asyncio
async def test_only_promoted_reviewed(maker):
    from server.services import curator

    # An observing candidate is NOT the Curator's domain.
    async with maker() as s:
        s.add(SkillCandidate(key="obs", name="Obs", category="meta", description="d",
                             body="b", source="skill_creator", status="observing"))
        await s.commit()
    assert await curator.review_promoted_skills() == []


@pytest.mark.asyncio
async def test_retire(maker):
    from server.registry import service as registry_service
    from server.services import curator

    await _seed_promoted(maker, key="my-skill")
    await _equip(maker, 1, "my-skill")
    await _equip(maker, 2, "my-skill")

    res = await curator.retire_skill("my-skill")
    assert res == {"ok": True, "key": "my-skill", "unassigned": 2}

    async with maker() as s:
        pack = await s.get(SkillPack, "my-skill")
        assert pack.status == "retired"
        cand = (await s.execute(
            __import__("sqlalchemy").select(SkillCandidate).where(SkillCandidate.key == "my-skill")
        )).scalars().first()
        assert cand.status == "retired"
        caps = (await s.execute(
            __import__("sqlalchemy").select(SpawnCapability).where(
                SpawnCapability.kind == "skill", SpawnCapability.ref_key == "my-skill")
        )).scalars().all()
        assert caps == []

    # Non-assignable now: the registry choke point RAISES.
    with pytest.raises(registry_service.NotAssignableError):
        await registry_service.assert_assignable("skill", "my-skill")


@pytest.mark.asyncio
async def test_retire_non_promoted_key(maker):
    from server.services import curator

    # No promoted candidate for this key.
    res = await curator.retire_skill("nope")
    assert res["ok"] is False
    assert "not a promoted" in res["reason"]


@pytest.mark.asyncio
async def test_retire_observing_key_rejected(maker):
    from server.services import curator

    async with maker() as s:
        s.add(SkillCandidate(key="obs", name="Obs", category="meta", description="d",
                             body="b", source="skill_creator", status="observing"))
        await s.commit()
    res = await curator.retire_skill("obs")
    assert res["ok"] is False
