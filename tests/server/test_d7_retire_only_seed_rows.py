"""D7 (docs/plans/0162/D7-retire-only-seed-rows.md): the boot-time retirement deletes only rows the
seeder planted. A skill the user brought in under a retired key survives every boot, whichever way
it was written:

- imported from a SKILL.md: category "imported" (skill_import);
- installed through Capabilities: source_id set (capability_flow);
- authored and promoted: a SkillCandidate of that key with promoted_at, whatever its status since
  (skill_forge, expert_conversion; the curator retires it, reject_candidate overwrites any status);
- made from a GitHub repo in Discover before v0.1.64: its key starts with "gh-" (the discovery
  centre, removed in CAP1a; its rows stay).

In each case a seed row with another retired key, in the same database, is still deleted."""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, SkillCandidate, SkillPack
from server.registry import seeder

SEED = "maps"                         # a retired key, as the seeder once planted it


def _pack(key: str, category: str, **extra) -> SkillPack:
    return SkillPack(key=key, name=key, category=category, description="d", tier="safe",
                     status=extra.pop("status", "registered"), body="## Trigger\nx", **extra)


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _boot(db, *rows) -> set[str]:
    db.add(_pack(SEED, "productivity"))
    for row in rows:
        db.add(row)
    await db.commit()
    await seeder.seed_registry_with(db)
    db.expire_all()
    return {key for key in seeder.RETIRED_SKILL_KEYS if await db.get(SkillPack, key) is not None}


@pytest.mark.asyncio
async def test_an_imported_skill_under_a_retired_key_survives_a_boot_with_its_scripts(db, tmp_path):
    scripts = tmp_path / "skill_scripts" / "notion"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text("print('hi')\n")
    assert await _boot(db, _pack("notion", "imported")) == {"notion"}
    assert (scripts / "run.py").exists()


@pytest.mark.asyncio
async def test_a_skill_installed_through_capabilities_survives_whatever_its_category(db):
    assert await _boot(db, _pack("obsidian", "writing", source_id="a" * 32)) == {"obsidian"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["promoted", "retired", "rejected"])
async def test_an_authored_skill_under_a_retired_key_survives(db, status):
    # "retired": the curator retired it; "rejected": reject_candidate ran on it after promotion
    # (②Main's review of #293: it does not check the candidate is still open).
    candidate = SkillCandidate(key="powerpoint", name="powerpoint", category="method", description="d",
                               body="## Trigger\nx", status=status, promoted_at=datetime(2026, 10, 1))
    assert await _boot(db, candidate, _pack("powerpoint", "method", status="registered" if status ==
                                            "promoted" else "retired")) == {"powerpoint"}


@pytest.mark.asyncio
async def test_promoting_then_rejecting_through_the_forge_keeps_the_skill(db, monkeypatch, tmp_path):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    import server.db.session as db_session
    from server.services import skill_forge
    monkeypatch.setattr(db_session, "AsyncSessionLocal",
                        async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False))
    cand = await skill_forge.create_candidate(key="notion", name="Notion notes", category="method",
                                              description="How I keep notes",
                                              body="## Trigger\nWhen the user asks to file a note.\n\n"
                                                   "## Decision Rules\nKeep each note short, dated and in the user's words.")
    assert (await skill_forge.promote_candidate(cand.id))["ok"]
    assert (await skill_forge.reject_candidate(cand.id))["ok"]
    assert await _boot(db) == {"notion"}


@pytest.mark.asyncio
async def test_a_candidate_that_never_went_live_does_not_shield_a_seed_row(db):
    candidate = SkillCandidate(key="notion", name="notion", category="method", description="d",
                               body="## Trigger\nx", status="rejected")
    assert await _boot(db, candidate, _pack("notion", "productivity")) == set()


@pytest.mark.asyncio
async def test_seed_rows_on_the_list_are_still_deleted(db):
    assert await _boot(db, _pack("obsidian", "productivity")) == set()


def test_no_retired_key_can_be_a_discover_skill():
    # The removed discovery centre made every Discover skill "gh-…"; a retired key never is.
    assert not [key for key in seeder.RETIRED_SKILL_KEYS if key.startswith("gh-")]
