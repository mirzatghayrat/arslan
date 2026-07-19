"""The first tick after enabling curation must not be a historical backfill.

WHY THIS EXISTS. `curation_enabled` gates a loop that spends: one judgment-LLM call per
producing spawn per conversation. Its candidate query selects EVERY conversation with an
undistilled spawn deliverable and no activity for 6h — which, the moment the switch is
turned on, is every such conversation ever recorded. Throttled at MAX_PER_TICK=5 per
15 minutes that is ~480 conversation-sweeps a day, continuing for days on an install with
history, starting 5 minutes after the flip. The module's own docstring says MAX_PER_TICK
exists to "bound the first-tick historical backfill" — bounding the RATE, not the total.

So enabling curation means "curate from here on". Reaching back over history is a
separate, explicit act; this round does not add that action, and says so rather than
pretending the history was handled.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from server.db.models import ArslanMessage, Setting, Spawn
from server.services import curation_loop, settings_service

#  is a conftest fixture (file-backed DB + watcher module-state reset).


async def _conversation(Session, cid: str, *, last_activity: datetime) -> None:
    """A conversation with an undistilled spawn deliverable, idle since `last_activity`."""
    async with Session() as db:
        if not (await db.execute(select(Spawn).where(Spawn.id == 1))).scalars().first():
            db.add(Spawn(id=1, name="S", domain_category="x", system_prompt="P",
                         generation_level=1, config={}))
        db.add(ArslanMessage(conversation_id=cid, role="spawn_summary", content="x",
                             display_content="x", spawn_id=1, timestamp=last_activity))
        await db.commit()


async def _enable(Session, **extra: str) -> None:
    async with Session() as db:
        db.add(Setting(key="curation_enabled", value="true"))
        for k, v in extra.items():
            db.add(Setting(key=k, value=v))
        await db.commit()


async def test_conversations_older_than_the_switch_are_not_swept(wdb):
    """🔴 The whole point. Turning the switch on must not enqueue months of history."""
    Session = wdb
    boundary = datetime.utcnow() - timedelta(days=1)
    await _conversation(Session, "ancient", last_activity=boundary - timedelta(days=30))
    await _conversation(Session, "fresh", last_activity=datetime.utcnow() - timedelta(hours=12))
    await _enable(Session, curation_backfill_from=boundary.isoformat())

    assert await curation_loop._candidates() == ["fresh"]


async def test_a_missing_boundary_is_recorded_on_the_first_tick_and_sweeps_nothing_old(wdb):
    """Fail-closed for SPEND, and self-healing. Someone can enable curation by writing
    the row directly; with no boundary recorded, backfilling would be the expensive
    reading. Record 'now' instead, sweep only forward, and say so in the log."""
    Session = wdb
    await _conversation(Session, "ancient", last_activity=datetime.utcnow() - timedelta(days=30))
    await _enable(Session)

    async with Session() as db:
        assert await settings_service.curation_backfill_from(db) is None

    await curation_loop.ensure_backfill_boundary()

    async with Session() as db:
        boundary = await settings_service.curation_backfill_from(db)
    assert boundary is not None, "the boundary must be recorded, not left implicit"
    assert await curation_loop._candidates() == []


async def test_the_boundary_is_written_once_and_never_moved_forward(wdb):
    """A boundary that advanced on every tick would be a sweep that never runs — every
    candidate would always sit before the newly-written floor.

    The floor is seeded to a past moment rather than letting the first call write "now",
    because a candidate must ALSO have been idle for IDLE_WINDOW_S (6h) to qualify: with
    a floor at `now` nothing can satisfy both conditions, so a candidate assertion would
    be vacuous. (My first version of this test did exactly that and failed for the wrong
    reason.)
    """
    Session = wdb
    flipped = datetime.utcnow() - timedelta(days=2)
    await _enable(Session, curation_backfill_from=flipped.isoformat())
    await _conversation(Session, "after", last_activity=datetime.utcnow() - timedelta(hours=12))

    await curation_loop.ensure_backfill_boundary()
    async with Session() as db:
        first = await settings_service.curation_backfill_from(db)
    await curation_loop.ensure_backfill_boundary()
    async with Session() as db:
        second = await settings_service.curation_backfill_from(db)

    assert first == second == flipped.replace(microsecond=flipped.microsecond), (
        "the boundary moved — conversations active after the flip would be skipped")
    assert await curation_loop._candidates() == ["after"]


async def test_turning_curation_OFF_AND_ON_AGAIN_does_not_backfill_the_gap(wdb):
    """🔴 The case the gate exists for, and the one my first version never touched.

    The boundary was written once PER DATABASE rather than once per ENABLE. So the most
    likely real sequence — enable, find it expensive, disable, use the app for months,
    enable again — left the stale first-enable floor in place and swept the entire OFF
    window. The gate protected only the first enable in the lifetime of the install.

    My `test_the_boundary_is_written_once_and_never_moved_forward` asserted stability
    across two ticks with curation continuously ON, which is correct — and by only ever
    exercising that direction it certified the write-once rule as sound at the exact
    transition where it is wrong. Ninth round of that pattern.
    """
    Session = wdb
    await _enable(Session)
    await curation_loop.ensure_backfill_boundary()
    async with Session() as db:
        first = await settings_service.curation_backfill_from(db)
    assert first is not None

    # ...turned off, then months of ordinary use...
    async with Session() as db:
        await settings_service.update_settings(db, {"curation_enabled": False})
    await curation_loop.ensure_backfill_boundary()          # a tick while OFF
    for i in range(3):
        await _conversation(Session, f"gap-{i}",
                            last_activity=datetime.utcnow() - timedelta(days=30 * (i + 1)))

    # ...and enabled again.
    async with Session() as db:
        await settings_service.update_settings(db, {"curation_enabled": True})
    await curation_loop.ensure_backfill_boundary()

    assert await curation_loop._candidates() == [], (
        "the off-period was backfilled — the boundary must belong to the CURRENT "
        "enablement, not to the first one this database ever saw")
    async with Session() as db:
        second = await settings_service.curation_backfill_from(db)
    assert second is not None and second > first, "a re-enable must record a fresh floor"


async def test_disabling_curation_clears_the_boundary_even_without_the_loop(wdb):
    """The toggle can happen while the app is down, so the settings WRITE path clears it
    too — the loop observing an off-tick is belt and braces, not the only mechanism."""
    Session = wdb
    await _enable(Session)
    await curation_loop.ensure_backfill_boundary()
    async with Session() as db:
        assert await settings_service.curation_backfill_from(db) is not None
        await settings_service.update_settings(db, {"curation_enabled": False})
    async with Session() as db:
        assert await settings_service.curation_backfill_from(db) is None


async def test_the_LOOP_clears_a_boundary_the_write_path_never_saw(wdb):
    """🔴 Isolates the second mechanism. The settings write path clears the boundary on
    disable, and in every ordinary scenario it gets there first — so a test that only
    goes through update_settings passes with the loop's clearing deleted, and the two
    halves mask each other. (That is exactly what my first mutation check found.)

    Here the boundary is written STRAIGHT INTO THE DB with curation already off: the
    shape left by a direct edit, or by a build that predates the write-path clearing.
    Only the loop can clean that up.
    """
    Session = wdb
    stale = datetime.utcnow() - timedelta(days=200)
    async with Session() as db:
        db.add(Setting(key="curation_backfill_from", value=stale.isoformat()))
        await db.commit()

    await curation_loop.ensure_backfill_boundary()          # a tick while OFF

    async with Session() as db:
        assert await settings_service.curation_backfill_from(db) is None, (
            "a stale boundary left by a direct DB edit survived — enabling curation "
            "would then backfill everything since it was written")


async def test_no_boundary_is_written_while_curation_is_OFF(wdb):
    """Recording a boundary for a disabled loop would silently decide, months early,
    which history is forever out of scope."""
    Session = wdb
    await curation_loop.ensure_backfill_boundary()
    async with Session() as db:
        assert await settings_service.curation_backfill_from(db) is None


@pytest.mark.parametrize("bad", ["", "not-a-date", "yesterday"])
async def test_an_unparsable_boundary_does_not_silently_reopen_the_backfill(wdb, bad):
    """A corrupt value must not fall back to 'no gate' — that is the expensive direction
    and it would be invisible."""
    Session = wdb
    await _conversation(Session, "ancient", last_activity=datetime.utcnow() - timedelta(days=30))
    await _enable(Session, curation_backfill_from=bad)

    assert await curation_loop._candidates() == []
