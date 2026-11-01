"""The run a Hands call was made in, on its trace entry (v0.1.64, for INB7-c4b: Progress shows a run's
Hands calls with that run). Matching calls to runs by time goes wrong when runs overlap; the run's own
id does not. Hands is faked (test_hands_0153's FakeHands)."""
import asyncio
import json
from datetime import datetime, timezone

from server.registry import hands_tools
from server.services import execution_context, hands_service, host_run, personal_context as pc
from tests.server import test_hands_0153 as base

isolated, hands, asks = base.isolated, base.hands, base.asks


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


async def test_the_trace_api_gives_every_entry_a_run_id_null_where_there_was_none(client, hands, asks):
    # An entry as written before v0.1.64, in the file today's calls go to.
    old = {"at": "2026-11-01T08:00:00+00:00", "conversation": "c0", "job": None, "app": "Notes",
           "bundle_id": "com.apple.Notes", "op": "click", "outcome": "ok", "ms": 12, "target": "Save"}
    day = datetime.now(timezone.utc).date().isoformat()
    with (hands_service._trace_dir() / f"{day}.jsonl").open("a") as f:
        f.write(json.dumps(old) + "\n")
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
