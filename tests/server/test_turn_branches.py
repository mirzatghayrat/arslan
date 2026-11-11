"""Branches of a turn that LOOP1's c3 PRs found no other test reaching, each through a whole turn: a tool table read
again mid-batch (c3a), the batch's own paths (c3b), and the finish answer (c3c)."""
import pytest

from tests.server.scripted_turn import (  # noqa: F401 — the fixtures
    FINDERS,
    LONG,
    NOTHING_FOUND,
    REACHABLE,
    SKILL,
    Reply,
    Turn,
    batch,
    booted_db_fixture,
    call,
    job,
    lane,
    run_turn,
    searches,
    skill_saves,
    table,
    turn_db_fixture,
    wrap_up_at_one,
)

NEEDS_X = {"key": "needs_x", "description": "The needs_x tool.",
           "input_schema": {"type": "object", "required": ["x"], "properties": {"x": {"type": "string"}}}}
CLAIM = "I searched and found it."
TOOL_TEXT = '{"tool": "web_search", "args": {"query": "x"}}'
FROM_THE_NOTES = "Reference notes gathered by a researcher are given below."


def _reachable(tools):
    async def reachable():
        return list(tools)
    return reachable


# ── c3a: a table read again mid-batch ──

async def test_a_refresh_mid_batch_is_the_table_the_rest_of_the_batch_checks(monkeypatch, turn_db):
    """A saved skill reads the table again: the rest of that batch is checked against the new one, so a tool it added
    runs and a tool it added with a schema is held to that schema."""
    turn, saved = Turn(), {"done": False}
    skill_saves(monkeypatch, saved)
    replies = [batch(("create_skill", SKILL, "c1"), ("needs_x", {}, "c2"),
                     ("update_plan", {"items": [{"text": "after", "status": "in_progress"}]}, "c3")), Reply("Done.")]
    await run_turn(turn, monkeypatch, turn_db, replies, tools=table("create_skill"), saved=saved,
                   later_tools=[*table("create_skill", "update_plan"), NEEDS_X])
    needs_x, = turn.results("needs_x")
    assert "Invalid arguments for needs_x: missing required 'x'" in needs_x["summary"]
    plan, = turn.results("update_plan")
    assert plan["ok"] is True and plan["summary"] == "0/1 done"
    assert turn.requests[1]["tools"] == ["create_skill", "needs_x", "update_plan"]


async def test_what_the_turn_opened_with_stays_after_a_refresh(monkeypatch, turn_db):
    """run_command arrives with the refresh: the wrap-up note lists it as a tool that still runs, but the offline
    note, worked out from the opening table, stays away, and so does the refused search's offline hint."""
    turn, saved = Turn(), {"done": False}
    skill_saves(monkeypatch, saved)
    replies = [batch(("create_skill", SKILL, "c1"), ("list_dir", {"path": "~/a"}, "c2")),
               call("web_search", {"query": "b"}, "c3"), Reply("Wrapped up.")]
    await run_turn(turn, monkeypatch, turn_db, replies, tools=table("create_skill", "list_dir", "web_search"),
                   later_tools=table("create_skill", "list_dir", "web_search", "run_command"), saved=saved,
                   budget=wrap_up_at_one())
    note = turn.added(1)
    assert "Work budget nearly used" in note and "Tools that still run: run_command; any other call is refused." in note
    assert "can still be processed with run_command" not in note
    search, = turn.results("web_search")
    assert search["summary"] == "Wrapping up: no more research. Write the deliverable from what you have."


async def test_a_save_tool_added_mid_turn_does_not_start_the_finish_steps(monkeypatch, turn_db):
    """At the no-progress stop, a turn that opened with no save tool goes straight to text, even though the refresh
    added write_file: no "save the deliverable now" step."""
    turn, saved = Turn(), {"done": False}
    skill_saves(monkeypatch, saved)
    replies = [call("create_skill", SKILL, "c0"), *searches(5), Reply("Blocked; here is what is verified.")]
    await run_turn(turn, monkeypatch, turn_db, replies, tools=table("create_skill", "web_search"), saved=saved,
                   later_tools=table("create_skill", "web_search", "write_file"), answers=NOTHING_FOUND)
    assert turn.returned["stop_reason"] == "task_no_progress"
    assert turn.requests[-1]["tool_choice"] == "none"
    last = turn.added(len(turn.requests) - 1)
    assert "Repeated actions made no progress. Explain what was verified and what is blocked. Text only." in last
    assert not any("save the deliverable now" in turn.added(index) for index in range(len(turn.requests)))


# ── c3b: the batch ──

async def test_an_unshown_tool_with_bad_arguments_is_told_to_send_use_tool_again(monkeypatch, turn_db):
    turn = Turn()
    await run_turn(turn, monkeypatch, turn_db, [call("attach_file", {}), Reply("Done.")], tools=FINDERS,
                   resolve_callable=_reachable(REACHABLE))
    assert turn.ran == [] and turn.kinds() == ["tool_result"]
    assert turn.results()[0]["summary"] == ("Invalid arguments for attach_file: missing required 'path' (string). "
                                            "Nothing was executed; send use_tool again with corrected arguments.")


async def test_a_tool_a_card_shows_mid_batch_runs_directly(monkeypatch, turn_db):
    """Shown by the refresh, it is a shown tool for the rest of the batch: run by its name, not unwrapped."""
    turn, saved = Turn(), {"done": False}
    skill_saves(monkeypatch, saved)
    replies = [batch(("create_skill", SKILL, "c1"), ("attach_file", {"path": "a.md"}, "c2")), Reply("Attached.")]
    await run_turn(turn, monkeypatch, turn_db, replies, tools=[*FINDERS, *table("create_skill")], saved=saved,
                   later_tools=[*FINDERS, *table("create_skill", "attach_file")],
                   resolve_callable=_reachable([*REACHABLE, *table("create_skill")]))
    assert turn.ran == [("attach_file", {"path": "a.md"}, turn.ran[0][2])]
    assert turn.kinds() == ["tool_call", "tool_result", "tool_call", "tool_result"]
    assert turn.results("attach_file")[0]["ok"] is True


async def test_a_plan_change_through_use_tool_is_answered_by_its_own_branch(monkeypatch, turn_db):
    turn = Turn()
    replies = [call("use_tool", {"name": "propose_plan_change", "arguments": {
        "levels": [{"name": "one", "band": "doing"}], "reason": "changed"}}), Reply("No project here.")]
    await run_turn(turn, monkeypatch, turn_db, replies, tools=FINDERS,
                   resolve_callable=_reachable([*REACHABLE, *table("propose_plan_change")]))
    assert [(frame["type"], frame["tool"]) for frame in turn.frames] == [
        ("tool_call", "propose_plan_change"), ("tool_result", "propose_plan_change")]
    assert turn.frames[1]["summary"] == "this conversation has no project"
    assert '"error": "this conversation has no project"' in turn.added(1)


async def test_a_later_save_that_compacts_nothing_keeps_the_earlier_compaction(monkeypatch, turn_db):
    turn = Turn()
    links = "| a | https://example.test/a |\n| b | https://example.test/b |\n| c | https://not-read.test/z |"
    replies = [batch(("web_extract", {"url": "https://example.test/a"}, "c1"),
                     ("web_extract", {"url": "https://example.test/b"}, "c2")),
               call("write_file", {"path": "report.md", "content": links}, "c3"),
               call("write_file", {"path": "second.md", "content": "more"}, "c4"), Reply("Saved both.")]
    await run_turn(turn, monkeypatch, turn_db, replies)
    assert [args.get("path") for tool, args, _ in turn.ran if tool == "write_file"] == ["report.md", "second.md"]
    assert "[Host check on report.md" in turn.added(2)
    assert turn.returned["history_compacted"] is True


async def test_a_lane_keeps_the_fingerprints_of_every_step(monkeypatch, turn_db):
    turn = Turn()
    progress = lane(turn)
    replies = [call("web_search", {"query": "a"}, "c1"), call("web_search", {"query": "b"}, "c2"), Reply("Done.")]
    await run_turn(turn, monkeypatch, turn_db, replies, progress_lane=progress)
    steps = [prints for reason, prints in turn.checkpoints if reason == "loop_progress"]
    assert [len(prints) for prints in steps] == [1, 2], steps
    assert set(steps[0]) < set(steps[1])
    assert turn.returned["final"] == "Done."


# ── c3c: the finish answer ──

async def test_the_forced_steps_denial_is_kept(monkeypatch, turn_db):
    """Nothing may be called any more, so a denial in the forced step's answer gets no capability correction."""
    turn = Turn()
    await run_turn(turn, monkeypatch, turn_db, [call("web_search", {"query": "q"}),
                                                Reply("I can't save that to a file.")], max_tool_calls=1)
    assert [request["tool_choice"] for request in turn.requests] == [None, "none"]
    assert turn.returned["final"] == "I can't save that to a file."
    assert turn.returned["stop_reason"] == "task_budget_exhausted"


async def test_a_denial_that_also_promises_gets_the_promise_bounce(monkeypatch, turn_db):
    turn = Turn()
    await run_turn(turn, monkeypatch, turn_db, [Reply("I can't save that to a file. I'll fetch that for you now."),
                                                Reply("Here is what I know.")])
    bounce = turn.added(1)
    assert "The proposed answer only promises future action" in bounce
    assert "Your answer says you cannot write" not in bounce
    assert turn.returned["final"] == "Here is what I know."


@pytest.mark.parametrize("forced_answer", [CLAIM, TOOL_TEXT], ids=["a claim", "tool-call text"])
async def test_the_forced_steps_unusable_answer_is_written_again_from_the_notes(forced_answer, monkeypatch, turn_db):
    turn = Turn()
    replies = [call("read_file", {"path": "a.md"}), Reply(forced_answer), Reply("Written from the notes.")]
    await run_turn(turn, monkeypatch, turn_db, replies, max_tool_calls=1)
    assert [request["tool_choice"] for request in turn.requests] == [None, "none"]
    assert FROM_THE_NOTES in turn.legacy[-1]["system"] and "a local note" in turn.legacy[-1]["user"]
    assert turn.returned["final"] == "Written from the notes." and turn.shown == "Written from the notes."
    assert turn.returned["stop_reason"] == "task_budget_exhausted"


async def test_a_deferral_with_no_tools_is_salvaged(monkeypatch, turn_db):
    """With nothing to call, a promise isn't bounced back to the model: the salvage answers in plain text."""
    turn = Turn()
    await run_turn(turn, monkeypatch, turn_db, [Reply("I'll fetch that for you now."),
                                                Reply("A plain answer from the salvage.")], tools=[])
    assert len(turn.requests) == 1 and len(turn.legacy) == 1
    assert "Answer the user's message directly, in plain text, right NOW." in turn.legacy[0]["system"]
    assert turn.returned["final"] == "A plain answer from the salvage."


async def test_a_streamed_claim_is_kept_after_work_when_the_notes_give_nothing(monkeypatch, turn_db):
    """Claims that went out while written are restarted twice; the third is kept when the write-up from the notes
    comes back empty."""
    turn = Turn()
    replies = [call("read_file", {"path": "a.md"}), Reply("I searched everywhere. " + LONG),
               Reply("I searched everywhere again. " + LONG), Reply("I searched everywhere a third time. " + LONG),
               Reply("")]
    await run_turn(turn, monkeypatch, turn_db, replies)
    assert turn.kinds() == ["tool_call", "tool_result", "stream_restart", "stream_restart"]
    assert FROM_THE_NOTES in turn.legacy[-1]["system"]
    assert turn.returned["final"].startswith("I searched everywhere a third time.")


async def test_a_skill_card_reached_through_use_tool(monkeypatch, turn_db):
    turn = Turn()
    skill_saves(monkeypatch, {"done": False})
    await run_turn(turn, monkeypatch, turn_db, [call("use_tool", {"name": "create_skill", "arguments": SKILL}),
                                                Reply("Saved it.")],
                   tools=FINDERS, resolve_callable=_reachable([*REACHABLE, *table("create_skill")]))
    assert [(frame["type"], frame["tool"]) for frame in turn.frames] == [
        ("tool_call", "create_skill"), ("tool_result", "create_skill")]
    assert turn.returned["tool_trace"] == [{"tool": "create_skill", "args": SKILL,
                                            "result": {"ok": True, "saved": "weekly"}}]


async def test_a_streamed_forced_step_fails_its_checks_with_no_repair(monkeypatch, turn_db):
    turn = Turn()
    runtime = job(turn, monkeypatch, [["bad one"]], answer_only=True, links=["https://not-read.test/z"])
    replies = [call("web_search", {"query": "q"}), Reply(LONG + "Source: https://not-read.test/z")]
    await run_turn(turn, monkeypatch, turn_db, replies, max_tool_calls=1)
    assert turn.shown.endswith("\n\nThese links were not verified: https://not-read.test/z")
    assert runtime.pause_reason == "task_validation_failed" and len(runtime.progress.validation_repairs) == 0
    assert len(turn.requests) == 2
