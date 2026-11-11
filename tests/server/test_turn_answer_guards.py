"""What the answer guards and the stops say, through a whole turn: the words the model is sent back, the words the user
is shown, and where the turn ends. Each case is one path through the guards that no other test reaches."""
import pytest

from server.orchestrator import on_demand
from tests.server.scripted_turn import (  # noqa: F401 — the fixtures
    LONG,
    STOPPED_EARLY,
    Reply,
    Turn,
    batch,
    booted_db_fixture,
    call,
    card,
    extract,
    long_turn,
    refusal,
    run_turn,
    table,
    turn_db_fixture,
    wrap_up_at_one,
)
from tests.server.test_trajectory_golden import _tc

CLAIM = "I searched and found it."
THOUGHT = {"protocol": "openai", "reasoning": "thinking it over"}
NOT_CAUGHT = "Sorry, I didn't quite catch that — could you say it another way?"
FROM_THE_NOTES = "Reference notes gathered by a researcher are given below."
WRAPPING_UP = "Wrapping up: no more research. Write the deliverable from what you have."
CANNOT_WRITE = ("Your answer says you cannot write or save files, but this turn has edit_file, write_file for the "
                "workspace folder.")


async def test_a_promise_is_bounced(monkeypatch, turn_db):
    turn = Turn()
    await run_turn(turn, monkeypatch, turn_db, [Reply("I'll fetch that for you now."),
                                                Reply("Here is the honest answer.")])
    bounced, said = turn.requests[1]["messages"][1:]
    assert bounced["content"] == "I'll fetch that for you now." and said["role"] == "user"
    assert said["content"].startswith("The proposed answer only promises future action.")
    assert turn.returned["final"] == "Here is the honest answer."


@pytest.mark.parametrize("replies,native", [
    ([Reply(""), Reply('{"tool": "web_search"}')], 1),
    ([Reply(CLAIM), Reply("I searched again."), Reply("I searched a third time."), Reply("I searched one more time.")],
     3),
], ids=["an empty answer, salvaged into tool text", "claims, and the salvage still claims"])
async def test_a_salvage_with_nothing_usable_asks_the_user_to_say_it_another_way(replies, native, monkeypatch, turn_db):
    turn = Turn()
    await run_turn(turn, monkeypatch, turn_db, replies)
    assert len(turn.requests) == native and len(turn.legacy) == 1
    assert turn.returned["final"] == NOT_CAUGHT and turn.shown == NOT_CAUGHT


async def test_claims_after_work_are_written_again_from_the_notes(monkeypatch, turn_db):
    turn = Turn()
    replies = [call("read_file", {"path": "a.md"}), Reply(CLAIM), Reply("I searched again."),
               Reply("I searched a third time."), Reply("Written from the notes.")]
    await run_turn(turn, monkeypatch, turn_db, replies)
    assert len(turn.requests) == 4 and FROM_THE_NOTES in turn.legacy[-1]["system"]
    assert turn.returned["final"] == "Written from the notes." and turn.returned["stop_reason"] is None


async def test_the_forced_step_ignores_a_call_and_writes_from_the_notes(monkeypatch, turn_db):
    turn = Turn()
    replies = [call("web_search", {"query": "q"}), Reply("narration", [_tc("web_search", {"query": "z"}, "c2")]),
               Reply("Written from the notes.")]
    await run_turn(turn, monkeypatch, turn_db, replies, max_tool_calls=1)
    assert [args for _tool, args, _ in turn.ran] == [{"query": "q"}]
    assert FROM_THE_NOTES in turn.legacy[-1]["system"]
    assert turn.returned["final"] == "Written from the notes."


async def test_claims_with_nothing_usable_from_the_notes_show_the_findings(monkeypatch, turn_db):
    turn = Turn()
    replies = [call("read_file", {"path": "a.md"}), Reply(CLAIM), Reply("I searched again."),
               Reply("I searched a third time."), Reply("I searched once more.")]
    await run_turn(turn, monkeypatch, turn_db, replies)
    final = turn.returned["final"]
    assert final.startswith("[Findings so far]") and '"text": "a local note"' in final and STOPPED_EARLY in final


@pytest.mark.parametrize("answer,kept", [
    ("I can't save that to a file.", THOUGHT),
    ("<agent_status>an echo</agent_status>\nI can't save that to a file.", None),
], ids=["its continuation kept", "an echo stripped drops the continuation"])
async def test_a_denied_capability_is_bounced(answer, kept, monkeypatch, turn_db):
    turn = Turn()
    await run_turn(turn, monkeypatch, turn_db, [Reply(answer, continuation=THOUGHT), Reply("I can write it now.")])
    bounced, said = turn.requests[1]["messages"][1:]
    assert bounced["content"] == "I can't save that to a file." and bounced["_continuation"] == kept
    assert said["content"].startswith(CANNOT_WRITE)
    assert turn.returned["final"] == "I can write it now."


async def test_three_cut_off_calls_force_text(monkeypatch, turn_db):
    turn = Turn()
    replies = [Reply(None, [_tc(name, {"path": "a.md"}, f"c{name}")], finish="length")
               for name in ("write_file", "edit_file", "read_file")] + [Reply("What is verified, and what remains.")]
    await run_turn(turn, monkeypatch, turn_db, replies)
    assert turn.ran == [] and len(turn.results()) == 3
    assert [request["tool_choice"] for request in turn.requests] == [None, None, None, "none"]
    assert ("Your tool calls kept exceeding the output limit and none of them ran. Report briefly what was verified "
            "and what remains. Text only.") in turn.added(3)
    assert turn.returned["stop_reason"] == "task_no_progress"


async def test_a_plan_change_with_no_project(monkeypatch, turn_db):
    turn = Turn()
    replies = [call("propose_plan_change", {"levels": [{"name": "one", "band": "doing"}], "reason": "changed"}),
               Reply("No project here.")]
    await run_turn(turn, monkeypatch, turn_db, replies, tools=table("propose_plan_change"))
    assert turn.kinds() == ["tool_call", "tool_result"]
    assert turn.results()[0]["summary"] == "this conversation has no project"


async def test_bookkeeping_still_runs_while_wrapping_up(monkeypatch, turn_db):
    """Past the soft limit the plan, a plan change and find_tools are still answered; a search is not."""
    turn = Turn()
    replies = [call("web_search", {"query": "a"}, "c1"),
               batch(("update_plan", {"items": [{"text": "finish", "status": "in_progress"}]}, "c2"),
                     ("propose_plan_change", {"levels": [{"name": "one", "band": "doing"}], "reason": "r"}, "c3"),
                     ("find_tools", {"query": "attach"}, "c4"), ("web_search", {"query": "b"}, "c5")),
               Reply("Wrapped up.")]

    async def reachable():
        return [*table("web_search", "update_plan", "propose_plan_change", "attach_file"), on_demand.FIND_TOOLS]
    await run_turn(turn, monkeypatch, turn_db, replies, budget=wrap_up_at_one(), resolve_callable=reachable,
                   tools=[*table("web_search", "update_plan", "propose_plan_change"), on_demand.FIND_TOOLS])
    results = {frame["tool"]: frame["summary"] for frame in turn.results()[1:]}
    assert results["update_plan"] == "0/1 done" and results["propose_plan_change"] == "this conversation has no project"
    assert results["find_tools"] == "1 tool(s) found" and results["web_search"] == WRAPPING_UP
    assert turn.tools_ran == ["web_search"]


async def test_a_choice_card_with_one_option_is_refused(monkeypatch, turn_db):
    turn = Turn()
    await run_turn(turn, monkeypatch, turn_db, [call("ask_user_choice", {"question": "Which?", "options": ["only one"]}),
                                                Reply("Plain question instead.")], tools=table("ask_user_choice"))
    assert turn.kinds() == ["tool_result"]
    assert turn.results()[0]["summary"].startswith("ask_user_choice needs a question plus 2-4 DISTINCT options")
    assert turn.returned["final"] == "Plain question instead."


async def test_wrapping_up_refuses_research_and_keeps_the_command_offline(monkeypatch, turn_db):
    """Past the soft limit a command still runs (offline, with its card) and a save still runs; a search is refused
    with the offline hint, since run_command was in the table."""
    turn = Turn()
    replies = [call("list_dir", {"path": "~/a"}, "c1"),
               batch(("run_command", {"command": "ls"}, "c2"), ("web_search", {"query": "b"}, "c3"),
                     ("write_file", {"path": "a.md", "content": "x"}, "c4")), Reply("Wrapped up.")]
    await run_turn(turn, monkeypatch, turn_db, replies, budget=wrap_up_at_one(), confirm_command=card(turn, "command"),
                   tools=table("list_dir", "web_search", "write_file", "run_command"))
    assert turn.tools_ran == ["list_dir", "run_command", "write_file"]
    assert turn.ran[1][2]["offline"] is True and [name for name, *_ in turn.cards] == ["command"]
    search, = turn.results("web_search")
    assert search["summary"].startswith(WRAPPING_UP + " Files you already fetched can still be processed with run_command")


@pytest.mark.parametrize("second", ["ask_user_choice", "reads"])
async def test_wrapping_up_refuses_a_choice_card_and_reads(second, monkeypatch, turn_db):
    turn = Turn()
    if second == "ask_user_choice":
        replies = [call("web_search", {"query": "a"}, "c1"),
                   call("ask_user_choice", {"question": "Which?", "options": ["A", "B"]}, "c2"), Reply("Wrapped up.")]
        own = dict(tools=table("web_search", "ask_user_choice"))
    else:
        replies = [call("list_dir", {"path": "~/a"}, "c1"),
                   batch(("read_file", {"path": "b.md"}, "c2"), ("list_dir", {"path": "~/c"}, "c3"),
                         ("write_file", {"path": "d.md", "content": "x"}, "c4")), Reply("Wrapped up.")]
        own = {}
    await run_turn(turn, monkeypatch, turn_db, replies, budget=wrap_up_at_one(), **own)
    refused = [frame["tool"] for frame in turn.results() if frame["summary"] == WRAPPING_UP]
    assert refused == (["ask_user_choice"] if second == "ask_user_choice" else ["read_file", "list_dir"])
    assert "clarify" not in turn.kinds()
    if second == "reads":       # two refusals while wrapping up: text only
        assert turn.tools_ran == ["list_dir", "write_file"]
        assert [request["tool_choice"] for request in turn.requests] == [None, None, "none"]


async def test_a_batch_too_big_to_deliver_is_cut_and_said(monkeypatch, turn_db):
    turn = Turn()
    reads = batch(*[("web_extract", {"url": f"https://example.test/{letter}"}, letter) for letter in "abc"])
    await run_turn(turn, monkeypatch, turn_db, [reads, Reply("Done.")],
                   answers={"web_extract": lambda args: extract(args, size=38_000)})
    first = turn.requests[1]["messages"][2]
    assert first["tool_call_id"] == "a" and first["content"].startswith("[Result omitted before delivery")
    assert "The newest tool-result batch exceeded the bounded delivery window." in turn.added(1)
    assert turn.returned["history_compacted"] is True


@pytest.mark.parametrize("history,step", [
    ([{"role": "user", "content": "old question " * 1800}, {"role": "assistant", "content": "old answer " * 2000}], 1),
    ([{"role": "user", "content": "old question " * 3000}, {"role": "assistant", "content": "old answer " * 3000},
      {"role": "user", "content": "next question"}, {"role": "assistant", "content": "next answer"}], 0),
], ids=["a big batch kept whole", "a long history"])
async def test_earlier_turns_are_compacted_and_the_model_is_told(history, step, monkeypatch, turn_db):
    turn = Turn()
    if step:
        replies = [batch(*[("web_extract", {"url": f"https://example.test/{letter}"}, letter) for letter in "abc"]),
                   Reply("Done.")]
        own = dict(answers={"web_extract": lambda args: extract(args, size=20_000)})
    else:
        replies, own = [call("web_search", {"query": "a"}), Reply("Done.")], {}
    await run_turn(turn, monkeypatch, turn_db, replies, history=history, **own)
    sent = turn.requests[step]["messages"]
    assert "Earlier conversation turns were compacted. Do not repeat completed effects." in str(sent[-1]["content"])
    assert not any("old question" in str(message["content"]) for message in sent)
    if step:
        assert [message.get("tool_call_id") for message in sent[2:5]] == ["a", "b", "c"]
    assert turn.returned["history_compacted"] is True


async def test_a_long_turn_says_so_once(monkeypatch, turn_db):
    turn = Turn()
    long_turn(turn, monkeypatch, "web_search")
    await run_turn(turn, monkeypatch, turn_db, [call("web_search", {"query": "a"}), Reply("Done.")],
                   tools=table("web_search", "start_background_work"))
    assert turn.kinds() == ["tool_call", "tool_result", "note"]
    assert turn.frames[-1]["text"] == ("This turn has been working for 10 minutes; if what is left is long, Arslan "
                                       "may continue it in the background.")


async def test_an_answer_cut_twice_is_continued_twice(monkeypatch, turn_db):
    turn = Turn()
    await run_turn(turn, monkeypatch, turn_db, [Reply("One", finish="length"), Reply(" two", finish="length"),
                                                Reply(" three", finish="length")])
    assert len(turn.requests) == 3
    for index in (1, 2):
        assert turn.requests[index]["messages"][-1]["content"].endswith(
            "Your previous reply was cut off by the output limit. Continue exactly where it stopped, without "
            "repeating anything already written and without any preamble.")
    assert turn.returned["final"] == "One two three"


async def test_images_the_model_refuses_are_read_on_this_mac(monkeypatch, turn_db):
    turn = Turn()
    replies = [call("desktop_look", {"app": "Notes"}), Reply(raises=refusal(400, "this model does not support image input")),
               Reply("Read it as text.")]
    await run_turn(turn, monkeypatch, turn_db, replies, tools=table("desktop_look"), ocr=True)
    assert len(turn.requests) == 3
    looked = turn.requests[2]["messages"][2]["content"]
    assert ("[screenshot of the window: this model cannot take images; the text this Mac read off it follows]"
            in looked) and "text on the window" in looked
    assert turn.returned["final"] == "Read it as text."
