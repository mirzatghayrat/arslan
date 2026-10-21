"""K4b: background work is the same work in another place (decision D4).

Before, four texts pushed multi-step work out of the chat turn:
- start_background_work's description: "Do NOT do such work inline in this turn" and
  "Then reply in ONE short sentence";
- its result: "The job runs after this turn. Reply in one sentence; do not do the work here.";
- "How you work": "Work that takes several steps or minutes … goes to start_background_work";
- the docstrings: "the turn ends at once" and "ends its turn in one sentence".
"""
import types
import uuid

import pytest

from server.registry.task_tools import StartBackgroundWorkExecutor
from server.services import background_jobs, personal_context as pc, task_context, task_service

CID = "conv-k4b"
PUSHES = ("do not do such work inline", "one short sentence", "reply in one sentence", "runs after this turn",
          "do not do the work here", "the turn ends at once", "ends its turn in one sentence",
          "goes to start_background_work")


def _pushes(text: str) -> list[str]:
    return [phrase for phrase in PUSHES if phrase in " ".join(text.lower().split())]


@pytest.fixture
def turn_context(monkeypatch):

    async def load(cid, **kwargs):
        identity = str(uuid.uuid4())
        return pc.TaskMemoryContext(task_id=identity, run_id=f"turn-{identity}", conversation_id=cid,
                                    no_memory=True, no_learning=True, query=kwargs.get("user_message", ""))
    monkeypatch.setattr(task_context, "load", load)


async def _description() -> str:
    from server.orchestrator.arslan import _arslan_tools
    seen = {}

    async def turn(conversation_id, user_message, emit):
        seen["tools"] = {t["key"]: t["description"] for t in await _arslan_tools()}
        return "ok"
    with pc.bind(await task_context.load(CID, user_message="x")):
        await task_service.run_turn(turn, CID, "x", lambda e: None)
    return seen["tools"]["start_background_work"]


async def test_the_description_offers_background_as_the_same_work_elsewhere(execution_db, turn_context):
    text = await _description()
    assert _pushes(text) == []
    assert "same work" in text and "otherwise do the work in this turn" in text
    # the job sees the saved conversation, not this turn's tool results: the goal has to carry them
    assert "what is already done" in text and "what remains" in text


def test_how_you_work_no_longer_sends_multi_step_work_away():
    from server.orchestrator.arslan import _CAPABILITY_SELF
    assert _pushes(_CAPABILITY_SELF) == []
    assert "start_background_work" in _CAPABILITY_SELF and "same work" in _CAPABILITY_SELF


@pytest.mark.parametrize("queued", [False, True])
async def test_the_result_says_whether_the_job_started_or_waits_and_asks_for_no_one_liner(monkeypatch, queued):
    async def start(conversation_id, goal, criteria):
        return types.SimpleNamespace(job_id="job-1", acceptance=[{"id": "c1", "description": "Saved"}])
    monkeypatch.setattr(background_jobs, "start", start)
    monkeypatch.setattr(background_jobs, "active_count",
                        lambda: background_jobs.MAX_CONCURRENT if queued else 0)
    ctx = pc.TaskMemoryContext(task_id="t", run_id="turn-t", conversation_id=CID, no_memory=True,
                               no_learning=True, query="")
    with pc.bind(ctx):
        result = await StartBackgroundWorkExecutor().execute({"goal": "Tidy my notes", "criteria": []})
    assert result["ok"] and result["queued"] is queued
    note = result["note"]
    assert _pushes(note) == []
    if queued:
        assert "queued" in note and "starts when one finishes" in note and "has started" not in note
    else:
        assert "has started" in note and "queued" not in note
    assert "posted to this conversation" in note and "same work in this turn" in note


def test_the_docstrings_tell_the_same_story():
    assert _pushes(StartBackgroundWorkExecutor.__doc__ or "") == []
    assert _pushes(background_jobs.__doc__ or "") == []
