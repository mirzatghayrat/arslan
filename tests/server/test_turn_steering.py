"""A message the user sends while a turn works (K9b), through a whole turn: the calls of the batch not yet started are
not run and each gets its own result, and the message joins the turn right after the batch's results, before the next
request. A group of reads already running is kept whole."""
import pytest

from tests.server.scripted_turn import (  # noqa: F401 — the fixtures
    Reply,
    Turn,
    batch,
    booted_db_fixture,
    extract,
    message_arrives,
    run_turn,
    turn_db_fixture,
)

SKIPPED = "Not run: the user sent a message while you were working."
TWO_WRITES = batch(("write_file", {"path": "a.md", "content": "x"}, "c1"),
                   ("write_file", {"path": "b.md", "content": "y"}, "c2"))
STEERED = dict(steerable=True, conversation_id="steered")


def _once(action):
    done = []

    def first():
        if not done:
            done.append(True)
            action()
    return first


@pytest.mark.parametrize("arrives", ["while the model writes its reply", "while the first call runs"])
async def test_a_message_stops_the_rest_of_the_batch_and_comes_next(arrives, monkeypatch, turn_db):
    """Waiting before the first call (it is already past the check, so it runs) or sent while it runs: either way the
    second call is not run, and the message comes right after the two results."""
    turn = Turn()
    message = message_arrives(turn, monkeypatch)
    if arrives == "while the model writes its reply":
        turn.before_reply.append(message)
    else:
        turn.hooks["write_file"] = [_once(message)]
    await run_turn(turn, monkeypatch, turn_db, [TWO_WRITES, Reply("Read your message.")], **STEERED)
    assert [args["path"] for _tool, args, _around in turn.ran] == ["a.md"]
    first, second = turn.results("write_file")
    assert first["ok"] is True and second["summary"].startswith(SKIPPED), second
    assert turn.stored == ["also this"]
    after = turn.requests[1]["messages"]
    assert [message["role"] for message in after] == ["user", "assistant", "tool", "tool", "user"]
    assert '"code": "skipped_for_message"' in after[3]["content"] and after[3]["tool_call_id"] == "c2"
    assert after[4]["content"].startswith("also this")
    assert turn.returned["final"] == "Read your message." and turn.returned["stop_reason"] is None


async def test_a_big_batch_of_reads_is_kept_with_its_message(monkeypatch, turn_db):
    """Three long pages read together, a message sent while the first is read, and a long history: all three ran and
    stay whole, the earlier turns are compacted instead, and the message follows the three results."""
    turn = Turn()
    turn.hooks["web_extract"] = [_once(message_arrives(turn, monkeypatch))]
    old = [{"role": "user", "content": "old question " * 1800}, {"role": "assistant", "content": "old answer " * 2000}]
    reads = batch(*[("web_extract", {"url": f"https://example.test/{letter}"}, letter) for letter in "abc"])
    await run_turn(turn, monkeypatch, turn_db, [reads, Reply("Done.")], history=old,
                   answers={"web_extract": lambda args: extract(args, size=20_000)}, **STEERED)
    assert turn.tools_ran == ["web_extract"] * 3
    assert [frame["ok"] for frame in turn.results("web_extract")] == [True, True, True]
    after = turn.requests[1]["messages"]
    assert [message["role"] for message in after] == ["user", "assistant", "tool", "tool", "tool", "user"]
    assert [message["tool_call_id"] for message in after[2:5]] == ["a", "b", "c"]
    assert all("x" * 20_000 in message["content"] for message in after[2:5])
    assert after[5]["content"].startswith("also this") and turn.stored == ["also this"]
    assert not any("old question" in str(message["content"]) for message in after)
    assert turn.returned["history_compacted"] is True
