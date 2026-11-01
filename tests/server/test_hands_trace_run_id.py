"""The run a Hands call was made in, on its trace entry (v0.1.64, for INB7-c4b: Progress shows a run's
Hands calls with that run). Matching calls to runs by time goes wrong when runs overlap; the run's own
id does not. Hands is faked (test_hands_0153's FakeHands)."""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from server.registry import hands_tools
from server.services import (background_jobs, execution_context, hands_client, hands_service, host_run,
                             personal_context as pc, run_registry)
from tests.server import test_background_jobs as bg
from tests.server import test_hands_0153 as base

isolated, hands, asks = base.isolated, base.hands, base.asks
fresh, active = bg.fresh, bg.active


def _turn(conversation: str):
    return pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id=conversation))


async def _run_in(conversation: str, body):
    """A recorded run in a conversation, as a chat reply makes one (host_run binds the run's id)."""
    with _turn(conversation):
        return await host_run.execute(conversation, "x", lambda event: None, body)


async def _look(app: str = "Notes") -> None:
    assert (await hands_tools.DesktopLookExecutor().execute({"app": app}))["ok"]


async def test_runs_that_overlap_each_put_their_own_id_on_their_hands_calls(hands, asks):
    ids, second_began, first_looked = {}, asyncio.Event(), asyncio.Event()

    async def first(emit):
        ids["c1"] = execution_context.current_run_id()
        await second_began.wait()            # it looks while a run that began later is still going
        await _look("Notes")
        first_looked.set()

    async def second(emit):
        ids["c2"] = execution_context.current_run_id()
        second_began.set()
        await first_looked.wait()
        await _look("Messages")

    await asyncio.gather(_run_in("c1", first), _run_in("c2", second))
    looks = {e["conversation"]: e["run_id"] for e in hands_service.read_trace() if e["op"] == "look"}
    assert looks == ids and len(set(ids.values())) == 2 and all(isinstance(i, int) for i in ids.values())


async def test_a_chat_and_its_job_in_one_conversation_each_put_their_own_run_on_their_calls(
        hands, asks, active, monkeypatch):
    """The job's run starts later and is still going when the chat looks, so the newest run in flight in the
    conversation is the wrong one for the chat's call."""
    from server.orchestrator import arslan
    ids, job_looked, chat_looked = {}, asyncio.Event(), asyncio.Event()

    async def job_body(conversation_id, goal, emit, confirmations):
        ids["job"] = execution_context.current_run_id()
        emit({"type": "tool_call", "tool": "desktop_look", "target": "Notes"})   # the job's run is its own
        await _look("Notes")                 # while the chat's run is going
        job_looked.set()
        await asyncio.wait_for(chat_looked.wait(), 10)
        return "Done: looked"
    monkeypatch.setattr(arslan, "background_body", job_body)
    window = bg._a_window_answering({"Use Notes?": "task"})   # a job asks on the conversation's windows
    run_registry.attach_sink("c1", window)
    try:
        async def chat(emit):
            ids["chat"] = execution_context.current_run_id()
            ids["started"] = await background_jobs.start("c1", "Look at my notes", [], outside_seen=False)
            await asyncio.wait_for(job_looked.wait(), 10)
            await _look("Messages")
            chat_looked.set()
        await _run_in("c1", chat)
        await bg._wait(lambda: ids["started"].task.done(), 15)
    finally:
        run_registry.detach_sink("c1", window)
    job = ids["started"]
    looks = {e["app"]: (e["run_id"], e["job"], e["conversation"])
             for e in hands_service.read_trace() if e["op"] == "look"}
    assert looks == {"Notes": (job.run_id, job.job_id, "c1"), "Messages": (ids["chat"], None, "c1")}
    assert job.run_id == ids["job"] != ids["chat"]


async def test_the_trace_api_gives_every_entry_a_run_id_null_where_there_was_none(client, hands, asks):
    # An entry as written before v0.1.64, in the file today's calls go to, and lines that are no entry.
    old = {"at": "2026-11-01T08:00:00+00:00", "conversation": "c0", "job": None, "app": "Notes",
           "bundle_id": "com.apple.Notes", "op": "click", "outcome": "ok", "ms": 12, "target": "Save"}
    day = datetime.now(timezone.utc).date().isoformat()
    with (hands_service._trace_dir() / f"{day}.jsonl").open("a") as f:
        f.write(json.dumps(old) + "\nnull\n[1, 2]\n\"text\"\n")
    ran = {}

    async def body(emit):
        ran["id"] = execution_context.current_run_id()
        await _look()
    await _run_in("c1", body)
    with _turn("c1"):
        await _look()                        # outside any run
    outside, inside, before = (await client.get("/api/v1/hands/trace")).json()["entries"]
    assert before == {**old, "run_id": None}
    assert isinstance(ran["id"], int) and inside["run_id"] == ran["id"] and inside["conversation"] == "c1"
    assert outside["run_id"] is None and outside["conversation"] == "c1"


async def test_an_entry_keeps_the_fields_it_sets_and_one_it_cannot_write_is_logged(hands, asks, caplog):
    started = time.monotonic()
    with _turn("c1"), execution_context.bind_run(7):
        hands_tools._trace("click", "Notes", "ok", started, run_id=99, conversation="c9", ms=-1,
                           at="1999-01-01T00:00:00+00:00")
    with execution_context.bind_run(uuid.uuid4()):          # not an int: no run
        hands_tools._trace("click", "Notes", "ok", started)
    with caplog.at_level(logging.WARNING, logger=hands_tools.__name__):
        hands_tools._trace("click", "Notes" + chr(0xD800), "error", started)   # a lone surrogate: not UTF-8
        hands_tools._trace("look", "Notes", "ok", started, screenshot=object())  # not JSON
    entries = hands_service.read_trace()
    assert [(e["run_id"], e["conversation"], e["ms"] >= 0) for e in entries] == [(None, None, True), (7, "c1", True)]
    assert not any(e["at"].startswith("1999") for e in entries)    # the time is the writer's
    assert caplog.text.count("not written") == 2


async def test_an_action_cancelled_with_its_request_out_is_on_the_record(hands, asks, monkeypatch):
    sent, real, after = asyncio.Event(), hands_client.call, []

    async def held(op, args=None, **kw):
        if op != "click":
            return await real(op, args, **kw)
        hands.calls.append((op, dict(args or {})))
        sent.set()
        await asyncio.Event().wait()         # Hands has it; no answer comes before the run is cancelled
    monkeypatch.setattr(hands_client, "call", held)
    ran = {}

    async def body(emit):
        ran["id"] = execution_context.current_run_id()
        await hands_tools.DesktopClickExecutor().execute({"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"})
        after.append("went on")
    with _turn("c1"):
        task = asyncio.create_task(host_run.execute("c1", "x", lambda event: None, body))
        await asyncio.wait_for(sent.wait(), 5)
        assert run_registry.cancel(ran["id"])
        assert await asyncio.wait_for(task, 5) is None
    (entry,) = [e for e in hands_service.read_trace() if e["op"] == "click"]
    assert (entry["outcome"], entry["run_id"], entry["target"]) == ("cancelled", ran["id"], "Save")
    assert after == []
