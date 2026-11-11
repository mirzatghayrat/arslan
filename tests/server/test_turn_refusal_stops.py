"""A model that keeps sending one refused call is stopped for making no progress: after a few refusals the turn asks
for text only, takes no more calls, and ends as `task_no_progress`. Nothing runs on the way. The other no-progress
tests reach the stop through calls that ran; these reach it through refusals, one kind each."""
import pytest

from tests.server.scripted_turn import (  # noqa: F401 — the fixtures
    FINDERS,
    REACHABLE,
    STOPPED_EARLY,
    Reply,
    Turn,
    booted_db_fixture,
    call,
    run_turn,
    table,
    turn_db_fixture,
)


def _repeated(name, args):
    """Far past where the stop should end it."""
    return [*[call(name, args, f"c{index}") for index in range(8)], Reply("Stopped asking.")]


def _bad_json():
    return [*[Reply(None, [{"id": f"c{index}", "function": {"name": "web_search", "arguments": '{"query": '},
                            "arguments_raw": '{"query": '}]) for index in range(8)], Reply("Stopped asking.")]


CASES = {
    # the refusal's words, how many calls were answered before text only, and the tools the turn had
    "bad_json": (_bad_json(), "were not valid JSON", 6, {}),
    "schema_refused": (_repeated("write_file", {"path": "a.md"}), "missing required 'content'", 6, {}),
    "find_tools": (_repeated("find_tools", {"query": "attach"}), "1 tool(s) found", 5,
                   dict(tools=FINDERS, resolve_callable=lambda: _copy(REACHABLE))),
    "use_tool_refused": (_repeated("use_tool", {"name": "nothing"}), "There is no tool named 'nothing'", 3,
                         dict(tools=FINDERS, resolve_callable=lambda: _copy(REACHABLE))),
    "bad_choice": (_repeated("ask_user_choice", {"question": "Which?", "options": ["only"]}),
                   "needs a question plus 2-4 DISTINCT options", 3, dict(tools=table("ask_user_choice"))),
}


async def _copy(tools):
    return list(tools)


@pytest.mark.parametrize("kind", list(CASES))
async def test_a_refusal_repeated_ends_the_turn_for_no_progress(kind, monkeypatch, turn_db):
    replies, says, answered, own = CASES[kind]
    turn = await run_turn(Turn(), monkeypatch, turn_db, replies, **own)
    assert turn.returned["stop_reason"] == "task_no_progress", turn.returned
    assert turn.ran == []
    results = turn.results()
    assert len(results) == answered and all(says in frame["summary"] for frame in results), results
    choices = [request["tool_choice"] for request in turn.requests]
    assert choices == [None] * answered + ["none"], choices     # then text only, and the call it sent is not run
    if kind == "find_tools":    # what it found is written up from the notes
        assert "Reference notes" in turn.legacy[-1]["system"] and turn.shown.startswith("[Findings so far]")
    else:
        assert turn.shown.startswith(STOPPED_EARLY), turn.shown
