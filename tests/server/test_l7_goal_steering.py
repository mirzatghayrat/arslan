"""L7-3: a goal job's turn is steerable under its own key, the job id (`TurnRequest.steer_key`), never its
conversation's: `/goal note` reaches it at its next tool boundary (K9b), and a chat message never lands in it."""
import pytest

from tests.server.scripted_turn import (  # noqa: F401 — the fixtures
    Reply,
    Turn,
    batch,
    booted_db_fixture,
    message_arrives,
    run_turn,
    turn_db_fixture,
)

TWO_WRITES = batch(("write_file", {"path": "a.md", "content": "x"}, "c1"),
                   ("write_file", {"path": "b.md", "content": "y"}, "c2"))
GOAL_JOB = dict(steerable=True, conversation_id="steered", steer_key="job-goal")


def _once(action):
    done = []

    def first():
        if not done:
            done.append(True)
            action()
    return first


@pytest.mark.parametrize("box,reaches", [("job-goal", True), ("steered", False)],
                         ids=["a note in the job's own box", "a chat message in the conversation's box"])
async def test_a_goal_job_reads_only_its_own_box(box, reaches, monkeypatch, turn_db):
    turn = Turn()
    turn.hooks["write_file"] = [_once(message_arrives(turn, monkeypatch, conversation_id=box))]
    await run_turn(turn, monkeypatch, turn_db, [TWO_WRITES, Reply("Noted.")], **GOAL_JOB)
    if reaches:
        assert turn.tools_ran == ["write_file"] and turn.stored == ["also this"]
        assert turn.requests[1]["messages"][-1]["content"].startswith("also this")
    else:
        assert turn.tools_ran == ["write_file", "write_file"] and turn.stored == []
        assert not any("also this" in str(message["content"]) for message in turn.requests[1]["messages"])
