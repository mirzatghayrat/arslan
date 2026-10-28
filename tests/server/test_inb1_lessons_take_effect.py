"""INB1 (v0.1.64, the user's item 6): learned practices take effect directly. Nothing waits in a queue
for the user's OK any more; what does not take effect is "not in effect", with its reason, and the
user sees it in Memory. Nothing that did not take effect is ever switched on by this card.

The gate itself (outside content, merges) is S64-0's and its tests are there; these pin the lesson
side: the reason Memory shows, the badge, three failures in a row, turning one on by hand, and a
correction against a pinned lesson that must not get lost.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from server.db.models import Lesson, MemoryProposal, Setting
from server.services import judgment, lessons, proactive_service
from server.services import personal_context as pc


@pytest.fixture
def judge(monkeypatch):
    """answers[point] = True / False / None (no answer), or a function of what is asked."""
    answers = {}

    async def fake(point, state, *, ref=None, conversation_id=None):
        answer = answers.get(point, True)
        answer = answer(state) if callable(answer) else answer
        return None if answer is None else judgment.Verdict(answer, 0.99 if answer else 0.01, 1)
    monkeypatch.setattr(judgment, "judge", fake)
    fake.answers = answers
    return fake


async def _rows(db):
    async with db() as session:
        return (await session.scalars(select(Lesson).order_by(Lesson.id))).all()


async def _seed(db, *, status="active", evidence=None, pinned=False, advice="use Swift with EventKit"):
    async with db() as session:
        row = Lesson(situation="Adding reminders", advice=advice, polarity="do", source="detour", status=status,
                     evidence=evidence, pinned=pinned, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(row)
        await session.commit()
        return row.id


def _detour(advice, situation="Reading calendar events"):
    return lessons.candidate(situation, advice, source="detour")


def _correction(advice, situation="Reading calendar events", **kw):
    return lessons.candidate(situation, advice, source="user_correction", **kw)


# -- what Memory shows: every lesson that is not in effect says why ------------------------------

async def _setting_off(db):
    async with db() as session:
        session.add(Setting(key="learned_practices_take_effect", value="false"))
        await session.commit()


@pytest.mark.parametrize("case,reason", [
    ("outside", "outside_content"),
    ("setting_off", "setting_off"),
    ("no_judgement", "no_judgement"),
    ("not_a_correction", "not_a_correction"),
    ("conflicts", "conflicts"),
])
async def test_every_lesson_that_does_not_take_effect_is_listed_with_its_reason(execution_db, judge, case, reason):
    judge.answers.update({"memory.merge": False, "memory.conflict": False})
    if case == "outside":
        out = await lessons.capture([_detour("use icalBuddy")], external_seen=True)
    elif case == "setting_off":
        await _setting_off(execution_db)
        out = await lessons.capture([_detour("use icalBuddy")], external_seen=False)
    elif case == "no_judgement":
        judge.answers["memory.worth"] = None
        out = await lessons.capture([_correction("use icalBuddy")], external_seen=False)
    elif case == "not_a_correction":
        said = _correction("use icalBuddy", evidence={"answers_earlier_reply": False})
        out = await lessons.capture([said], external_seen=False)
    else:
        await lessons.capture([_detour("use icalBuddy")], external_seen=False)
        judge.answers["memory.conflict"] = True
        out = await lessons.capture([_detour("use AppleScript")], external_seen=False)
    learned = out[-1]
    assert learned["status"] == "proposed" and learned["not_in_effect"] == reason
    listed = {row.id: lessons.present(row) for row in await _rows(execution_db)}
    assert listed[learned["id"]]["not_in_effect"] == reason


async def test_a_lesson_in_effect_has_no_reason(execution_db, judge):
    [learned] = await lessons.capture([_detour("use icalBuddy")], external_seen=False)
    assert learned["status"] == "active" and learned["not_in_effect"] is None


async def test_a_waiting_lesson_from_before_v0_1_64_with_no_reason_counts_as_outside_content(client):
    from server.db import session as db_session
    await _seed(db_session.AsyncSessionLocal, status="proposed", evidence=None)
    await _seed(db_session.AsyncSessionLocal, status="proposed", evidence={"seen": 2})
    listed = (await client.get("/api/v1/lessons?status=proposed")).json()
    assert [item["not_in_effect"] for item in listed] == ["outside_content", "outside_content"]


# -- the badge counts no learned practice ---------------------------------------------------------

async def test_the_badge_no_longer_counts_learned_practices_that_wait(execution_db):
    await _seed(execution_db, status="proposed", evidence={lessons.NOT_IN_EFFECT: "outside_content"})
    await _seed(execution_db, status="proposed")
    async with execution_db() as session:
        session.add(MemoryProposal(kind="memory_v2", table_name="memory_v2", reason="sensitive", status="pending"))
        await session.commit()
    assert (await proactive_service.summary())["memory"] == 1      # the memory proposal (INB2 removes it)


# -- three failures in a row stop a practice ------------------------------------------------------

async def _apply(lesson_id, ok, *, followed=True, judge):
    judge.answers["memory.applied"] = followed
    await lessons.record_applied([{"id": lesson_id, "text": "Adding reminders → use Swift with EventKit"}],
                                 [{"tool": "run_command", "args": {"command": "swift r.swift"},
                                   "result": {"ok": ok}}], ok=ok)


async def test_three_failures_in_a_row_stop_a_practice_and_say_why(execution_db, judge):
    lesson_id = await _seed(execution_db)
    for _ in range(3):
        await _apply(lesson_id, False, judge=judge)
    [row] = await _rows(execution_db)
    assert (row.status, row.failed, row.followed) == ("stale", 3, 3)
    assert row.evidence[lessons.NOT_IN_EFFECT] == "failed_repeatedly"      # written when it stops
    assert lessons.present(row)["not_in_effect"] == "failed_repeatedly"
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c", model_is_local=True)):
        assert await lessons.recall("add reminders with swift") == []


async def test_a_success_starts_the_count_again(execution_db, judge):
    lesson_id = await _seed(execution_db)
    for ok in (False, False, True, False, False):
        await _apply(lesson_id, ok, judge=judge)
    [row] = await _rows(execution_db)
    assert (row.status, row.evidence[lessons.FAIL_STREAK], row.failed, row.succeeded) == ("active", 2, 4, 1)


async def test_a_turn_that_did_not_follow_the_practice_does_not_count(execution_db, judge):
    lesson_id = await _seed(execution_db)
    for _ in range(3):
        await _apply(lesson_id, False, followed=False, judge=judge)
    [row] = await _rows(execution_db)
    assert (row.status, row.failed) == ("active", 0)
    assert lessons.FAIL_STREAK not in (row.evidence or {})


async def test_a_pinned_practice_is_never_stopped_by_failures(execution_db, judge):
    lesson_id = await _seed(execution_db, pinned=True)
    for _ in range(4):
        await _apply(lesson_id, False, judge=judge)
    [row] = await _rows(execution_db)
    assert (row.status, row.failed) == ("active", 4)


# -- turning one on by hand -------------------------------------------------------------------------

async def test_turning_a_lesson_on_in_memory_clears_why_it_waited(client):
    from server.db import session as db_session
    waited = await _seed(db_session.AsyncSessionLocal, status="proposed",
                         evidence={lessons.NOT_IN_EFFECT: "conflicts", lessons.CONFLICTS_WITH: 7, "seen": 2})
    stopped = await _seed(db_session.AsyncSessionLocal, status="stale",
                          evidence={lessons.NOT_IN_EFFECT: "failed_repeatedly", lessons.FAIL_STREAK: 3})
    for lesson_id in (waited, stopped):
        item = (await client.post(f"/api/v1/lessons/{lesson_id}/status", json={"status": "active"})).json()
        assert item["status"] == "active" and item["not_in_effect"] is None
        assert not {lessons.NOT_IN_EFFECT, lessons.CONFLICTS_WITH, lessons.FAIL_STREAK} & set(item["evidence"])
    listed = {item["id"]: item for item in (await client.get("/api/v1/lessons?status=active")).json()}
    assert listed[waited]["evidence"] == {"seen": 2}                 # only the bookkeeping keys go


# -- a correction against a pinned lesson is kept, waiting, in the user's words --------------------

async def test_a_correction_against_a_pinned_lesson_waits_in_the_users_words(execution_db, judge):
    """S64-0's recheck (N2): the user's correction merged into a lesson that waits against a pinned
    one was dropped (no row, nothing shown). It is kept as its own waiting lesson in the user's words."""
    judge.answers.update({"memory.merge": False, "memory.conflict": False})
    [first] = await lessons.capture([_detour("use icalBuddy")], external_seen=False)
    async with execution_db() as session:
        (await session.get(Lesson, first["id"])).pinned = True
        await session.commit()
    judge.answers["memory.conflict"] = True
    await lessons.capture([_detour("use AppleScript")], external_seen=False)
    judge.answers.update({"memory.conflict": False, "memory.merge": lambda pair: "AppleScript" in pair["existing"]})
    [kept] = await lessons.capture([_correction("use AppleScript's Calendar dictionary")])
    assert (kept["status"], kept["advice"], kept["not_in_effect"]) == (
        "proposed", "use AppleScript's Calendar dictionary", "conflicts")
    assert kept["evidence"][lessons.CONFLICTS_WITH] == first["id"]
    pinned, waiting, mine = await _rows(execution_db)
    assert (pinned.status, waiting.status, waiting.advice) == ("active", "proposed", "use AppleScript")
