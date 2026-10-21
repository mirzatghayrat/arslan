"""H3 (v0.1.63, decision U8): a chat turn has no Hands limits of its own — no five actions, no one
app — only the run's limits (K4), the same as background work; and Stop stops a chat turn's Hands
calls as it stops a job's. The protections H1 kept are pinned here too: one card per app, risky
steps every time. Hands is faked (the contract fixtures); nothing is sent to a model."""
import asyncio

from server.orchestrator import arslan
from server.registry import hands_tools
from server.services import desktop_status, hands_service, task_service
from tests.server import test_hands_0153 as base

isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job

SAVE = {"app": "Notes", "element": "Save", "ref": "@sfixture0:e3"}


async def test_a_chat_turn_acts_many_times_across_apps_asking_once_per_app(hands, asks, in_turn):
    seen, _ = asks
    click, press = hands_tools.DesktopClickExecutor(), hands_tools.DesktopPressExecutor()
    with desktop_status.working("c1"):
        for _ in range(7):
            assert (await click.execute(SAVE))["ok"]
        for _ in range(3):
            assert (await press.execute({"app": "Messages", "keys": "tab"}))["ok"]
        assert (await click.execute(SAVE))["ok"]                     # back in the first app
    assert hands.ops("click") == ["click"] * 8 and hands.ops("press") == ["press"] * 3
    assert [(f["kind"], f.get("target")) for f in seen if f["kind"] == "desktop_app"] == [
        ("desktop_app", "Notes"), ("desktop_app", "Messages")]


async def test_a_risky_step_still_asks_every_time_in_a_chat_turn(hands, asks, in_turn):
    seen, _ = asks
    hands.target = {**hands.target, "name": "Delete"}
    click = hands_tools.DesktopClickExecutor()
    with desktop_status.working("c1"):
        for _ in range(6):
            assert (await click.execute({"app": "Notes", "element": "Tidy up", "ref": "@sfixture0:e4"}))["ok"]
    assert [f["kind"] for f in seen] == ["desktop_app"] + ["desktop_risky"] * 6


async def test_stop_in_a_chat_turn_refuses_its_next_hands_calls_before_hands_is_asked(hands, asks, in_turn):
    click = hands_tools.DesktopClickExecutor()
    with desktop_status.working("c1"):
        assert (await click.execute(SAVE))["ok"]
        hands_service.stop_running_jobs()
        sent = len(hands.calls)
        acted = await click.execute(SAVE)
        opened = await hands_tools.DesktopOpenExecutor().execute({"app": "Notes"})
        batch = await hands_tools.DesktopBatchExecutor().execute(
            {"app": "Notes", "steps": [{"action": "press", "keys": "tab"}]})
    assert acted["code"] == "stopped_by_user" and acted["executed"] is False
    assert opened["code"] == "stopped_by_user" and opened["executed"] is False
    assert batch["ok"] is False and "(stopped_by_user)" in batch["text"]
    assert {op for op, _ in hands.calls[sent:]} <= {"snapshot", "find", "list_windows", "capture_window",
                                                    "which_app", "status"}   # the batch's closing look only
    assert hands.ops("click") == ["click"] and hands.ops("press") == []


async def test_stop_stops_every_turn_in_flight_not_only_those_that_used_hands(hands, asks, in_turn):
    with desktop_status.working("c1"):
        hands_service.stop_running_jobs()
        result = await hands_tools.DesktopPressExecutor().execute({"app": "Notes", "keys": "tab"})
    assert result["code"] == "stopped_by_user" and hands.ops("press") == []


async def test_a_turn_running_alongside_is_stopped_too_and_a_new_turn_is_not(hands, asks, in_turn):
    press = hands_tools.DesktopPressExecutor()
    stopped, go_on = asyncio.Event(), asyncio.Event()
    results: list[dict] = []

    async def other_turn():
        with desktop_status.working("c2"):
            stopped.set()
            await go_on.wait()
            results.append(await press.execute({"app": "Notes", "keys": "tab"}))

    other = asyncio.ensure_future(other_turn())
    await stopped.wait()
    hands_service.stop_running_jobs()                # Stop while the other turn is in flight
    go_on.set()
    await other
    assert results[0]["code"] == "stopped_by_user"
    with desktop_status.working("c2"):               # the next turn in the same conversation
        assert (await press.execute({"app": "Notes", "keys": "tab"}))["ok"]
    assert hands.ops("press") == ["press"]


async def test_a_stop_mark_goes_when_its_turn_ends(hands, asks, in_turn):
    with desktop_status.working("c1"):
        hands_service.stop_running_jobs()
        assert hands_service.stopped(None)
    assert not hands_service.stopped(None)
    assert hands_service._stopped_turns == set()


async def test_a_job_is_still_stopped_by_its_id(hands, asks, in_job):
    hands_service.stop_running_jobs()
    hands_service._stopped.add("job-1")              # a job that is running (background_jobs is faked here)
    result = await hands_tools.DesktopPressExecutor().execute({"app": "Notes", "keys": "tab"})
    assert result["code"] == "stopped_by_user" and hands.ops("press") == []


async def test_the_trace_says_which_way_hands_acted(hands, asks, in_turn):
    with desktop_status.working("c1"):
        assert (await hands_tools.DesktopMenuExecutor().execute({"app": "Notes", "path": ["Format", "Bold"]}))["ok"]
    assert [e.get("mode_used") for e in hands_service.read_trace() if e["op"] == "menu"] == ["background"]


async def test_the_chat_tools_no_longer_mention_a_cap(execution_db, hands, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(task_service, "current", lambda: object())
    described = " ".join(t["description"] for t in await arslan._arslan_tools() if t["key"].startswith("desktop_"))
    assert "five" not in described and "all in one app" not in described
    assert "start background work" not in described
