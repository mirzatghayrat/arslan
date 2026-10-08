"""0.1.52 S5: learned practices — detours from the turn's own trace, the user's
corrections, capture through the judgment layer (worth / merge / conflict), the D2
effect rule, recall into the status block, and the counters."""
import pytest
from sqlalchemy import select

from server.db.models import Lesson, Setting
from server.services import desktop_status, judgment, lessons
from server.services import personal_context as pc

CID = "c-lessons"


def ctx(**kw):
    return pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id=CID, model_is_local=True, **kw)


@pytest.fixture
def judge(monkeypatch):
    """answers[point] = True / False / None (no answer); records what was asked."""
    answers, asked = {}, []

    async def fake(point, state, *, ref=None, conversation_id=None):
        asked.append((point, state))
        answer = answers.get(point, True)
        return None if answer is None else judgment.Verdict(answer, 0.99 if answer else 0.01, 1)
    monkeypatch.setattr(judgment, "judge", fake)
    fake.answers, fake.asked = answers, asked
    return fake


async def rows(db):
    async with db() as s:
        return (await s.scalars(select(Lesson).order_by(Lesson.id))).all()


def correction(situation="Adding reminders on this Mac", advice="use Swift with EventKit", **kw):
    return lessons.candidate(situation, advice, source="user_correction", **kw)


def detour(situation="Reading calendar events", advice="use icalBuddy instead of AppleScript", source="detour"):
    return lessons.candidate(situation, advice, source=source)


# -- detours are host facts -----------------------------------------------------

def call(tool, ok, **args):
    result = {"ok": ok}
    if not ok:
        result.update(args.pop("result", {"error": "boom"}))
    return {"tool": tool, "args": args, "result": result}


def test_a_failure_then_a_different_route_that_worked_is_a_detour():
    trace = [call("run_command", False, command="osascript -e 'tell app \"Reminders\"'",
                  result={"error": "Not authorized to send Apple events (-1743)"}),
             call("run_command", True, command="swift add_reminder.swift")]
    [found] = lessons.detours(trace)
    assert found["failed"]["call"].startswith("osascript") and found["worked"]["call"].startswith("swift")
    assert found["quirk"] is True and "-1743" in found["failed"]["error"]


def test_reminders_refusing_apple_events_is_a_quirk_of_this_mac():
    trace = [call("run_command", False, command="osascript r.scpt",
                  result={"error": "exit code 1", "stderr": "Reminders got an error: A privilege violation occurred. (-10004)"}),
             call("run_command", True, command="swift r.swift")]
    assert lessons.detours(trace)[0]["quirk"] is True


def test_web_routes_count_and_a_plain_error_is_not_a_quirk():
    trace = [call("web_extract", False, url="https://a.example/x", result={"error": "HTTP 403"}),
             call("browser_open", True, url="https://a.example/x")]
    [found] = lessons.detours(trace)
    assert found["quirk"] is False and found["worked"]["tool"] == "browser_open"


@pytest.mark.parametrize("trace", [
    # the same route working on a retry is not a detour
    [call("run_command", False, command="python3 a.py"), call("run_command", True, command="python3 a.py --fix")],
    # refused by the user, or malformed: never a real try
    [call("run_command", False, command="rm -rf build", result={"code": "declined", "error": "declined"}),
     call("run_command", True, command="ls")],
    [call("write_file", False, result={"code": "invalid_arguments", "error": "bad"}), call("edit_file", True)],
    # a web failure is not "fixed" by a local step
    [call("web_search", False, query="x"), call("write_file", True, path="a.md")],
    # bookkeeping is not a route
    [call("update_plan", False), call("memory_note", True)],
    [call("run_command", True, command="ls")],
])
def test_what_is_not_a_detour(trace):
    assert lessons.detours(trace) == []


def test_at_most_two_detours_and_one_per_failed_route():
    trace = [call("run_command", False, command="osascript a"), call("run_command", False, command="osascript b"),
             call("run_command", True, command="swift a"), call("web_search", False, query="q"),
             call("web_extract", True, url="u"), call("run_command", False, command="brew x"),
             call("run_command", True, command="port x")]
    found = lessons.detours(trace)
    assert len(found) == 2
    assert found[0]["failed"]["call"] == "osascript a" and found[1]["failed"]["tool"] == "web_search"


# -- capture -------------------------------------------------------------------

async def test_the_users_correction_takes_effect_at_once_and_is_announced(execution_db, judge):
    desktop_status._events.clear()
    seen = []
    [learned] = await lessons.capture([correction()], conversation_id=CID, emit=seen.append)
    assert learned["status"] == "active" and learned["source"] == "user_correction"
    assert seen == [{"type": "lesson_learned", "lesson": learned}]
    assert desktop_status._events[-1]["kind"] == "lesson_learned"
    assert [p for p, _ in judge.asked] == ["memory.worth"]


@pytest.mark.parametrize("external,status", [(False, "active"), (True, "proposed")])
async def test_a_detour_takes_effect_only_when_the_turn_read_nothing_from_outside(execution_db, judge, external, status):
    [learned] = await lessons.capture([detour()], conversation_id=CID, external_seen=external)
    assert learned["status"] == status


async def test_with_the_setting_off_everything_waits(execution_db, judge):
    async with execution_db() as db:
        db.add(Setting(key="learned_practices_take_effect", value="false"))
        await db.commit()
    out = await lessons.capture([correction(), detour()], external_seen=False)
    assert [x["status"] for x in out] == ["proposed", "proposed"]


async def test_not_worth_keeping_is_dropped_and_no_answer_keeps_only_the_users_words(execution_db, judge):
    judge.answers["memory.worth"] = False
    assert await lessons.capture([correction(), detour()], external_seen=False) == []
    judge.answers["memory.worth"] = None
    out = await lessons.capture([correction(), detour()], external_seen=False)
    assert [(x["source"], x["status"]) for x in out] == [("user_correction", "proposed")]


async def test_credentials_never_become_a_lesson(execution_db, judge):
    bad = lessons.candidate("Calling the API", "use key sk-abcdefghijklmnopqrstuvwxyz123456", source="user_correction")
    assert await lessons.capture([bad]) == [] and judge.asked == []


async def test_a_duplicate_merges_into_the_existing_lesson(execution_db, judge):
    await lessons.capture([detour()], external_seen=False)
    judge.answers["memory.merge"] = True
    out = await lessons.capture([correction("Reading calendar events", "use icalBuddy, never AppleScript")])
    assert out == []
    [row] = await rows(execution_db)
    assert row.advice == "use icalBuddy, never AppleScript" and row.evidence["seen"] == 2


async def test_the_users_newer_correction_replaces_a_contradicting_lesson(execution_db, judge):
    await lessons.capture([correction("Reading calendar events", "use AppleScript")])
    judge.answers.update({"memory.merge": False, "memory.conflict": True})
    await lessons.capture([correction("Reading calendar events", "AppleScript", polarity="avoid")])
    old, new = await rows(execution_db)
    assert (old.status, new.status, new.polarity) == ("archived", "active", "avoid")


async def test_a_detour_never_overrides_a_lesson_on_its_own(execution_db, judge):
    await lessons.capture([correction("Reading calendar events", "use AppleScript")])
    judge.answers.update({"memory.merge": False, "memory.conflict": True})
    await lessons.capture([detour("Reading calendar events", "use icalBuddy")], external_seen=False)
    old, new = await rows(execution_db)
    assert (old.status, new.status) == ("active", "proposed")


async def test_a_pinned_lesson_is_never_retired_by_a_conflict(execution_db, judge):
    await lessons.capture([correction("Reading calendar events", "use AppleScript")])
    async with execution_db() as db:
        (await db.get(Lesson, 1)).pinned = True
        await db.commit()
    judge.answers.update({"memory.merge": False, "memory.conflict": True})
    await lessons.capture([correction("Reading calendar events", "AppleScript", polarity="avoid")])
    old, new = await rows(execution_db)
    assert (old.status, new.status) == ("active", "proposed")


# -- recall ----------------------------------------------------------------------

async def seed(db, *items, status="active"):
    from datetime import datetime
    async with db() as s:
        for situation, advice in items:
            s.add(Lesson(situation=situation, advice=advice, polarity="do", source="detour", status=status,
                         created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
        await s.commit()


async def test_recall_picks_what_matches_and_counts_it(execution_db):
    await seed(execution_db, ("Adding reminders", "use Swift with EventKit"), ("Converting video", "use ffmpeg"))
    await seed(execution_db, ("Adding reminders quickly", "proposed only"), status="proposed")
    with pc.bind(ctx()):
        picked = await lessons.recall("add three reminders for tomorrow")
    assert [p["text"] for p in picked] == ["Adding reminders → use Swift with EventKit"]
    first, second, third = await rows(execution_db)
    assert (first.recalled, second.recalled, third.recalled) == (1, 0, 0) and first.last_used_at


async def test_recall_keeps_to_five_and_800_characters(execution_db):
    await seed(execution_db, *[(f"Reminders case {i}", "x" * 100) for i in range(8)])
    with pc.bind(ctx()):
        picked = await lessons.recall("reminders")
    assert len(picked) == 5 and sum(len(p["text"]) for p in picked) <= 800
    await seed(execution_db, *[(f"Reminders long {i}", "y" * 390) for i in range(3)])
    with pc.bind(ctx()):
        assert sum(len(p["text"]) for p in await lessons.recall("reminders long")) <= 800


@pytest.mark.parametrize("context", [None, ctx(temporary=True), ctx(no_memory=True),
                                     pc.TaskMemoryContext(task_id="t", run_id="r", model_is_local=False)])
async def test_recall_follows_memory_permissions(execution_db, context):
    await seed(execution_db, ("Adding reminders", "use Swift"))
    if context is None:
        assert await lessons.recall("reminders") == []
    else:
        with pc.bind(context):
            assert await lessons.recall("reminders") == []
    cloud_on = pc.TaskMemoryContext(task_id="t", run_id="r", model_is_local=False, cloud_memory_default=True)
    with pc.bind(cloud_on):
        assert len(await lessons.recall("reminders")) == 1


async def test_recalled_lessons_ride_in_the_status_block_of_the_first_request(execution_db, monkeypatch):
    from server.orchestrator import tool_loop
    from tests.server import test_trajectory_golden as golden
    await seed(execution_db, ("Adding reminders", "use Swift with EventKit"))
    recorder = golden._Recorder([golden._Resp("done")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: recorder)
    monkeypatch.setattr(lessons, "later", lambda coro: coro.close())

    async def resolve():
        return []
    with pc.bind(ctx(query="add two reminders")):
        await tool_loop.run_native(system="S", user_content="add two reminders", history=[], emit=lambda e: None,
                                   on_chunk=lambda c: None, resolve_tools=resolve)
    sent = str(recorder.calls[0])
    assert "<agent_status" in sent and "Adding reminders → use Swift with EventKit" in sent
    assert "Adding reminders" not in str(recorder.calls[0].get("system", ""))


# -- counters ------------------------------------------------------------------

@pytest.mark.parametrize("applied,ok,expected", [(True, True, (1, 1, 0)), (True, False, (1, 0, 1)),
                                                 (False, True, (0, 0, 0))])
async def test_applied_fills_the_counters(execution_db, judge, applied, ok, expected):
    await seed(execution_db, ("Adding reminders", "use Swift"))
    judge.answers["memory.applied"] = applied
    await lessons.record_applied([{"id": 1, "text": "Adding reminders → use Swift"}],
                                 [call("run_command", True, command="swift r.swift")], ok=ok)
    [row] = await rows(execution_db)
    assert (row.followed, row.succeeded, row.failed) == expected
    point, state = judge.asked[-1]
    assert point == "memory.applied" and state["steps"] == ["run_command: swift r.swift → ok"]


async def test_after_turn_learns_from_a_detour(execution_db, judge, monkeypatch):
    chats = []

    class Adapter:
        async def chat(self, *, system, user):
            chats.append(user)
            assert "-1743" in user and "swift" in user

            class R:
                content = '{"situation": "Adding reminders on this Mac", "advice": "use Swift with EventKit"}'
            return R()

    async def adapter():
        return Adapter()
    monkeypatch.setattr(lessons, "_detour_adapter", adapter)
    trace = [call("run_command", False, command="osascript r", result={"error": "Not authorized (-1743)"}),
             call("run_command", True, command="swift r.swift")]
    with pc.bind(ctx()):
        await lessons.after_turn(conversation_id=CID, user_request="add a reminder", trace=trace,
                                 external_seen=False, recalled=[], ok=True)
    [row] = await rows(execution_db)
    assert (row.source, row.status, row.advice) == ("machine_quirk", "active", "use Swift with EventKit")
    for off in (ctx(no_learning=True), ctx(no_memory=True), ctx(temporary=True)):
        with pc.bind(off):
            await lessons.after_turn(conversation_id=CID, user_request="x", trace=trace, external_seen=False,
                                     recalled=[{"id": 1, "text": "t"}], ok=True)
    assert len(chats) == 1 and (await rows(execution_db))[0].followed == 0


async def test_a_one_off_detour_is_skipped(execution_db, judge, monkeypatch):
    class Adapter:
        async def chat(self, *, system, user):
            class R:
                content = '{"skip": true, "situation": "Running a script", "advice": "spell python right"}'
            return R()

    async def adapter():
        return Adapter()
    monkeypatch.setattr(lessons, "_detour_adapter", adapter)
    found = lessons.detours([call("run_command", False, command="pyhton a.py"),
                             call("run_command", True, command="python3 a.py")])
    assert await lessons.detour_candidates(found, "run it", CID) == []


# -- the user's correction, from turn_facts -------------------------------------

async def test_a_correction_in_the_users_words_becomes_a_lesson(monkeypatch):
    from server.services import turn_facts
    captured = []

    class Adapter:
        async def chat(self, *, system, user):
            class R:
                content = ('{"new_facts": [], "practices": [{"situation": "Adding reminders", '
                           '"advice": "AppleScript", "avoid": true}]}')
            return R()

    async def adapter():
        return Adapter()

    async def working(cid):
        return {"history": []}

    async def facts_text(**k):
        return ""

    async def fake_capture(made, **kw):
        captured.append((made, kw))
        return []
    monkeypatch.setattr(turn_facts, "_get_adapter", adapter)
    monkeypatch.setattr(turn_facts.memory, "assemble_working_context", working)
    monkeypatch.setattr(turn_facts.memory, "facts_text", facts_text)
    monkeypatch.setattr(lessons, "capture", fake_capture)
    pending = []
    monkeypatch.setattr(lessons, "later", pending.append)
    await turn_facts.capture(CID, "don't use AppleScript for reminders", lambda e: None)
    [coro] = pending
    await coro
    [(made, kw)] = captured
    assert made[0].source == "user_correction" and made[0].polarity == "avoid"
    assert kw["external_seen"] is False


def test_practices_parse_is_bounded_and_strict():
    from server.services import turn_facts
    content = ('{"practices": [{"situation": "a", "advice": "b"}, {"situation": "c"}, '
               '{"situation": "d", "advice": "e", "avoid": "yes"}, {"situation": "f", "advice": "g"}]}')
    assert turn_facts.parse_practices(content) == [
        {"situation": "a", "advice": "b", "avoid": False}, {"situation": "d", "advice": "e", "avoid": False}]


# -- Brain API -------------------------------------------------------------------

async def test_brain_lists_accepts_undoes_pins_and_deletes(client):
    from datetime import datetime

    from server.db import session as db_session
    async with db_session.AsyncSessionLocal() as db:
        db.add(Lesson(situation="Adding reminders", advice="use Swift", polarity="do", source="detour",
                      status="proposed", created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
        await db.commit()
    [item] = (await client.get("/api/v1/lessons")).json()
    assert item["status"] == "proposed" and item["text"] == "Adding reminders → use Swift"
    assert (await client.post(f"/api/v1/lessons/{item['id']}/status", json={"status": "active"})).json()["status"] == "active"
    assert (await client.post(f"/api/v1/lessons/{item['id']}/status", json={"status": "proposed"})).status_code == 422
    assert (await client.post(f"/api/v1/lessons/{item['id']}/pin", json={"pinned": True})).json()["pinned"] is True
    assert (await client.get("/api/v1/lessons?status=archived")).json() == []
    assert (await client.delete(f"/api/v1/lessons/{item['id']}")).json()["deleted"] is True
    assert (await client.get("/api/v1/lessons")).json() == []
    assert (await client.post("/api/v1/lessons/999/pin", json={"pinned": True})).status_code == 404


async def test_the_setting_defaults_on(client):
    assert (await client.get("/api/v1/settings")).json()["learned_practices_take_effect"] is True
    r = await client.put("/api/v1/settings", json={"learned_practices_take_effect": False})
    assert r.status_code == 200 and (await client.get("/api/v1/settings")).json()["learned_practices_take_effect"] is False


async def test_after_turn_work_runs_detached_from_the_finished_turn():
    """The turn's attempt is closed when this runs; a model call through its checkpoint
    is refused (task_attempt_stale). The work keeps the turn's memory permissions."""
    import asyncio

    from arslan import execution_checkpoint
    seen = {}

    async def refuse(reason):
        raise RuntimeError("task_attempt_stale")

    async def work():
        await execution_checkpoint.save("before_model")      # must not reach `refuse`
        seen["ctx"] = pc.current()
    context = ctx()
    with pc.bind(context), execution_checkpoint.bind(refuse):
        lessons.later(work())
        await asyncio.gather(*list(lessons._background))
    assert seen["ctx"] is context


# -- L1 (0.1.55): a request is not a correction, and what just worked is not overruled --

FINDER = ("在访达里把文件改名", "在访达里完成，而不是用命令行")   # the 2026-10-05 real-Mac lesson


@pytest.fixture
def fresh_worked():
    lessons._WORKED.clear()
    yield
    lessons._WORKED.clear()


def test_only_a_message_after_an_arslan_reply_can_correct():
    from server.services.turn_facts import answers_earlier_reply as after
    first = [{"role": "user", "content": "在访达里把 a.txt 改名为 b.txt"}, {"role": "assistant", "content": "改好了"}]
    assert after(first) is False                      # the conversation's first message
    later = first + [{"role": "user", "content": "下次别用命令行"}, {"role": "assistant", "content": "好"}]
    assert after(later) is True
    assert after([{"role": "user", "content": "x"}], summary="earlier turns") is True


async def test_a_first_request_is_learned_only_as_a_proposal(execution_db, judge, fresh_worked):
    first = correction(*FINDER, evidence={"conversation_id": CID, "answers_earlier_reply": False})
    [learned] = await lessons.capture([first], conversation_id=CID)
    assert learned["status"] == "proposed"


async def test_a_correction_against_the_route_that_just_worked_waits(execution_db, judge, fresh_worked):
    lessons.note_turn(CID, [call("run_command", True, command="mv ~/Desktop/a.txt ~/Desktop/b.txt")])
    judge.answers["memory.conflict"] = True
    real = correction(*FINDER, evidence={"conversation_id": CID, "answers_earlier_reply": True})
    [learned] = await lessons.capture([real], conversation_id=CID)
    assert learned["status"] == "proposed"
    [(point, state)] = [a for a in judge.asked if a[0] == "memory.conflict"]
    assert "mv ~/Desktop/a.txt" in state["existing"]


async def test_a_real_correction_after_a_wrong_route_still_takes_effect_at_once(execution_db, judge, fresh_worked):
    """The mirror: Arslan used AppleScript (it worked, but the user wants EventKit) —
    the judge says no contradiction with a different route... and with no route
    worked at all the correction applies at once, as in 0.1.52."""
    real = correction(evidence={"conversation_id": CID, "answers_earlier_reply": True})
    [learned] = await lessons.capture([real], conversation_id=CID)
    assert learned["status"] == "active"
    lessons.note_turn(CID, [call("run_command", True, command="swift add_reminder.swift")])
    judge.answers.update({"memory.conflict": False, "memory.merge": False})
    again = correction("Listing reminders", "use EventKit, not AppleScript",
                       evidence={"conversation_id": CID, "answers_earlier_reply": True})
    [learned] = await lessons.capture([again], conversation_id=CID)
    assert learned["status"] == "active"


async def test_no_judge_answer_on_the_contradiction_check_waits(execution_db, judge, fresh_worked):
    lessons.note_turn(CID, [call("run_command", True, command="mv a b")])
    judge.answers["memory.conflict"] = None
    real = correction(*FINDER, evidence={"conversation_id": CID, "answers_earlier_reply": True})
    [learned] = await lessons.capture([real], conversation_id=CID)
    assert learned["status"] == "proposed"


async def test_turn_facts_marks_a_first_message(monkeypatch):
    from server.services import turn_facts
    captured = []

    class Adapter:
        async def chat(self, *, system, user):
            class R:
                content = ('{"new_facts": [], "practices": [{"situation": "%s", "advice": "%s"}]}' % FINDER)
            return R()

    async def adapter():
        return Adapter()

    async def working(cid):
        return {"history": [{"role": "user", "content": "在访达里把 a 改名为 b"},
                            {"role": "assistant", "content": "已改名"}]}

    async def facts_text(**k):
        return ""

    async def fake_capture(made, **kw):
        captured.append(made)
        return []
    monkeypatch.setattr(turn_facts, "_get_adapter", adapter)
    monkeypatch.setattr(turn_facts.memory, "assemble_working_context", working)
    monkeypatch.setattr(turn_facts.memory, "facts_text", facts_text)
    monkeypatch.setattr(lessons, "capture", fake_capture)
    pending = []
    monkeypatch.setattr(lessons, "later", pending.append)
    await turn_facts.capture(CID, "在访达里把 a 改名为 b", lambda e: None)
    await pending[0]
    assert captured[0][0].evidence["answers_earlier_reply"] is False


def test_the_host_turn_records_what_worked_before_learning(monkeypatch, fresh_worked):
    from server.orchestrator import tool_loop
    scheduled = []
    monkeypatch.setattr(tool_loop, "_host_turn", lambda *a: True)
    monkeypatch.setattr(lessons, "later", lambda coro: (coro.close(), scheduled.append(1)))
    tool_loop._learn_after({"conversation_id": CID}, {"tool_trace": [call("run_command", True, command="mv a b")]},
                           {"final": "ok"})
    assert lessons._WORKED[CID] == ["run_command: mv a b"] and scheduled == [1]


def test_hands_refused_by_macos_never_teaches_another_route():
    """L1: the real-Mac proposal "PERM_DENIED → use osascript" contradicted the advice
    the model is given (stop, ask the user to allow Arslan Hands)."""
    trace = [call("desktop_look", False, app="Notes", result={"code": "PERM_DENIED", "error": "refused"}),
             call("run_command", True, command="osascript -e 'tell app \"Notes\"'")]
    assert lessons.detours(trace) == []
