"""JUDGE1 (v0.1.64, fix-forward on v0.1.63; ⓪Plan's audit of 2026-10-31): lessons' capture asked the judge
(memory.merge, memory.conflict) about up to two stored lessons without recall()'s gate. With a cloud model and cloud
memory off, a stored lesson still reached the cloud router model. The judgments ledger kept its text after the lesson
was deleted, and was pruned only at boot.

Now: a stored lesson reaches the judge only where memory may be shown to a model at all
(personal_context.may_show_memory, recall's own rule); merge and conflict rows name their lesson (`ref`), and
deleting the lesson deletes them; the ledger is pruned at most hourly while the app runs, not only at boot.
Fixture text is synthetic."""
import dataclasses
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from server.db.models import Judgment, Lesson
from server.services import judgment, lessons
from server.services import personal_context as pc

MARK = "QUARTERLYARCHIVE"


class Router:
    """The router-slot judge: "worth it" yes, everything else no; records what it was sent."""
    model = "cloud-router-fixture"

    def __init__(self):
        self.calls = []

    async def chat(self, *, system, user, **kwargs):
        self.calls.append(user)
        yes = "worth remembering" in user

        class Reply:
            content = '{"answer": %s, "p": %s}' % ("true" if yes else "false", "0.99" if yes else "0.01")
            usage = {}
        return Reply()


@pytest.fixture
def router(monkeypatch):
    adapter = Router()

    async def make():
        return adapter
    monkeypatch.setattr(judgment, "_adapter", make)
    return adapter


LOCAL = pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c-judge1", model_is_local=True)
CLOUD_OFF = dataclasses.replace(LOCAL, model_is_local=False, cloud_memory_allowed=False, cloud_memory_default=False)


async def _stored(db, status="active") -> int:
    async with db() as session:
        row = Lesson(situation=f"Exporting the {MARK} files", advice="use the archive tool with --full",
                     polarity="do", source="detour", status=status, evidence={})
        session.add(row)
        await session.commit()
        return row.id


async def _capture(ctx):
    cand = lessons.candidate(f"Exporting the {MARK} files", "use the archive tool", source="detour")
    if ctx is None:
        await lessons.capture([cand], conversation_id="c-judge1", external_seen=False)
        return
    with pc.bind(ctx):
        await lessons.capture([cand], conversation_id="c-judge1", external_seen=False)


def _sent_stored(router) -> bool:
    """Whether any judge call carried the stored lesson (its advice), not just the candidate."""
    return any("--full" in call for call in router.calls)


async def test_a_local_model_is_asked_about_the_stored_lesson(execution_db, router):
    await _stored(execution_db)
    await _capture(LOCAL)
    assert _sent_stored(router)                                              # positive control


@pytest.mark.parametrize("ctx", [
    CLOUD_OFF,
    dataclasses.replace(LOCAL, no_memory=True),
    dataclasses.replace(LOCAL, temporary=True),
    None,
], ids=["cloud-model-cloud-memory-off", "memory-off", "temporary", "no-context"])
async def test_no_stored_lesson_reaches_the_judge_where_memory_may_not_be_shown(execution_db, router, ctx):
    await _stored(execution_db)
    await _stored(execution_db, status="stale")                              # main also reads stopped ones
    await _capture(ctx)
    assert not _sent_stored(router)


async def test_recall_and_capture_follow_one_rule(execution_db, router):
    await _stored(execution_db)
    with pc.bind(CLOUD_OFF):
        assert await lessons.recall(f"Exporting the {MARK} files") == []
    with pc.bind(LOCAL):
        assert await lessons.recall(f"Exporting the {MARK} files") != []    # positive control


async def test_merge_and_conflict_rows_name_their_lesson(execution_db, router):
    lesson_id = await _stored(execution_db)
    await _capture(LOCAL)
    async with execution_db() as session:
        rows = (await session.execute(select(Judgment.point, Judgment.ref).where(
            Judgment.point.in_(("memory.merge", "memory.conflict"))))).all()
    assert rows and all(ref == f"lesson:{lesson_id}" for _, ref in rows)


async def test_deleting_a_lesson_deletes_the_judgments_about_it(client, router, monkeypatch):
    from server.db import session as db_session
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as session:
        keep = Lesson(situation="Another", advice="other", polarity="do", source="detour", status="active",
                      evidence={})
        gone = Lesson(situation=f"Exporting the {MARK} files", advice="use the archive tool with --full",
                      polarity="do", source="detour", status="active", evidence={})
        session.add_all([keep, gone])
        await session.commit()
        for lesson, point in ((gone, "memory.merge"), (gone, "memory.conflict"), (gone, "memory.applied"),
                              (keep, "memory.merge")):
            # The state holds the stored lesson's text, as the ledger keeps it (Activity shows it).
            session.add(Judgment(point=point, mode="active", state={"existing": lessons.render(lesson)},
                                 state_hash="h", ref=f"lesson:{lesson.id}"))
        await session.commit()
        gone_id, keep_id = gone.id, keep.id
    assert (await client.delete(f"/api/v1/lessons/{gone_id}")).status_code == 200
    async with client.db_maker() as session:
        rows = (await session.execute(select(Judgment.ref, Judgment.state))).all()
    assert not any(MARK in str(state) for _, state in rows)                  # nothing still holds its text
    assert [ref for ref, _ in rows] == [f"lesson:{keep_id}"]                 # the other lesson's row stays


async def test_the_ledger_is_pruned_while_the_app_runs(execution_db, router, monkeypatch):
    async with execution_db() as session:
        session.add(Judgment(point="memory.merge", mode="active", state={}, state_hash="h",
                             created_at=datetime.utcnow() - timedelta(days=judgment.KEEP_DAYS + 1)))
        await session.commit()
    monkeypatch.setitem(judgment._last_prune, "at", 0.0)
    await judgment.judge("memory.worth", {"kind": "detour", "candidate": "x", "evidence": "{}"})
    async with execution_db() as session:
        points = (await session.scalars(select(Judgment.point))).all()
    assert points == ["memory.worth"]                                        # the old row went, the new one stays
    pruned = []

    async def counting():
        pruned.append(1)
        return 0
    monkeypatch.setattr(judgment, "prune", counting)
    await judgment.judge("memory.worth", {"kind": "detour", "candidate": "y", "evidence": "{}"})
    assert pruned == []                                                      # at most once per PRUNE_EVERY_S
