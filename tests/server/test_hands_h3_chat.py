"""H3 (v0.1.63, decision U8): a chat turn has no Hands limits of its own — no five actions, no one
app — only the run's limits (K4), the same as background work; and Stop stops a chat turn's Hands
calls as it stops a job's. The protections H1 kept are pinned here too: one card per app, risky
steps every time. Hands is faked (the contract fixtures); nothing is sent to a model."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from server.orchestrator import arslan
from server.registry import hands_tools
from server.services import desktop_status, hands_client, hands_service, permissions, task_service
from server.services import personal_context as pc
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
        looked = await hands_tools.DesktopLookExecutor().execute({"app": "Notes"})
    assert acted["code"] == "stopped_by_user" and acted["executed"] is False
    assert opened["code"] == "stopped_by_user" and opened["executed"] is False
    assert batch["ok"] is False and "(stopped_by_user)" in batch["text"]
    assert looked["code"] == "stopped_by_user"
    assert hands.calls[sent:] == []          # nothing at all: no closing look, no look (a look can borrow)


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


# ── ②Main's review of #290: Stop after a card, looks, Return, the job-only tools ─────────────────

@pytest.fixture
def stop_at_card(asks):
    """A card that is answered yes after the user pressed Stop meanwhile (the phone, say)."""
    seen, _ = asks

    async def surface(frame):
        seen.append(frame)
        hands_service.stop_running_jobs()
        hands_service._stopped.add("job-1")          # the job fixture's job (background_jobs is not running it)
        options = frame.get("options") or [None]
        return {"approved": True, "scope": options[0], "note": "", "by": "mac"}
    with permissions.asking_with(surface):
        yield seen


async def _click_after_stop_at_card(hands, seen):
    with desktop_status.working("c1"):
        result = await hands_tools.DesktopClickExecutor().execute(SAVE)
    assert [f["kind"] for f in seen] == ["desktop_app"]
    assert result["code"] == "stopped_by_user" and result["executed"] is False and hands.ops("click") == []


async def test_an_action_whose_app_card_is_answered_after_stop_is_not_sent_in_a_turn(hands, stop_at_card, in_turn):
    await _click_after_stop_at_card(hands, stop_at_card)


async def test_an_action_whose_app_card_is_answered_after_stop_is_not_sent_in_a_job(hands, stop_at_card, in_job):
    await _click_after_stop_at_card(hands, stop_at_card)


async def test_a_risky_action_whose_card_is_answered_after_stop_is_not_sent(hands, asks, in_turn):
    seen, _ = asks
    click = hands_tools.DesktopClickExecutor()
    with desktop_status.working("c1"):
        assert (await click.execute(SAVE))["ok"]                     # the app card, answered before Stop
        hands.target = {**hands.target, "name": "Send"}

        async def surface(frame):
            seen.append(frame)
            hands_service.stop_running_jobs()
            return {"approved": True, "scope": (frame.get("options") or [None])[0], "note": "", "by": "mac"}
        with permissions.asking_with(surface):
            result = await click.execute({"app": "Notes", "element": "Send", "ref": "@sfixture0:e4"})
    assert seen[-1]["kind"] == "desktop_risky"
    assert result["code"] == "stopped_by_user" and hands.ops("click") == ["click"]


async def test_an_open_whose_card_is_answered_after_stop_does_not_open_in_a_turn(hands, stop_at_card, in_turn,
                                                                                   monkeypatch):
    await _open_after_stop_at_card(monkeypatch)


async def test_an_open_whose_card_is_answered_after_stop_does_not_open_in_a_job(hands, stop_at_card, in_job,
                                                                                  monkeypatch):
    await _open_after_stop_at_card(monkeypatch)


async def _open_after_stop_at_card(monkeypatch):
    ran = []

    async def exec_(*argv, **kw):
        ran.append(argv)
        raise AssertionError("open ran after Stop")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_)
    with desktop_status.working("c1"):
        result = await hands_tools.DesktopOpenExecutor().execute({"app": "TextEdit"})
    assert result["code"] == "stopped_by_user" and ran == []


async def test_an_open_in_a_stopped_job_is_refused_before_its_card(hands, asks, in_job):
    seen, _ = asks
    hands_service._stopped.add("job-1")
    result = await hands_tools.DesktopOpenExecutor().execute({"app": "TextEdit"})
    assert result["code"] == "stopped_by_user" and seen == []


async def test_typing_stopped_after_the_text_is_set_does_not_press_return(hands, asks, in_turn, monkeypatch):
    real = hands.call

    async def stop_after_setting(op, args=None, **kw):
        out = await real(op, args, **kw)
        if op == "set_value":
            hands_service.stop_running_jobs()
        return out
    monkeypatch.setattr(hands_client, "call", stop_after_setting)
    with desktop_status.working("c1"):
        result = await hands_tools.DesktopTypeExecutor().execute(
            {"app": "Notes", "element": "Title", "ref": "@sfixture0:e3", "text": "hello", "submit": True})
    assert result["ok"] is False and result["code"] == "stopped_by_user"
    assert hands.ops("set_value") == ["set_value"] and hands.ops("press") == []


async def test_a_job_started_by_a_stopped_turn_is_stopped(hands, asks, in_turn, monkeypatch):
    from server.registry import task_tools
    from server.services import background_jobs
    started = iter(["job-after-stop", "job-before-stop"])

    async def start(conversation_id, goal, criteria, **kw):  # noqa: ARG001 — the job is not run here
        return SimpleNamespace(job_id=next(started), acceptance=[])
    monkeypatch.setattr(background_jobs, "start", start)
    with desktop_status.working("c1"):
        hands_service.stop_running_jobs()
        assert (await task_tools.StartBackgroundWorkExecutor().execute({"goal": "tidy the notes"}))["ok"]
    with desktop_status.working("c1"):                # a turn that was not stopped
        assert (await task_tools.StartBackgroundWorkExecutor().execute({"goal": "tidy the notes"}))["ok"]
    assert hands_service.stopped("job-after-stop") and not hands_service.stopped("job-before-stop")


async def test_a_stopped_job_runs_no_shortcut_script_or_takeover(hands, asks, in_job, monkeypatch):
    seen, _ = asks
    ran = []

    async def run(argv, **kw):
        ran.append(argv)
        return {"ok": True, "external": False, "text": "ran"}
    monkeypatch.setattr(hands_tools, "_run", run)
    hands_service._stopped.add("job-1")
    results = [await hands_tools.MacRunShortcutExecutor().execute({"name": "Tidy"}),
               await hands_tools.MacAppleScriptExecutor().execute({"script": 'tell application "Notes" to activate'}),
               await hands_tools.DesktopTakeoverExecutor().execute({"why": "drag photos", "minutes": 2})]
    assert [r["code"] for r in results] == ["stopped_by_user"] * 3
    assert ran == [] and seen == [] and hands.ops("takeover_begin") == []


@pytest.mark.parametrize("tool", ["shortcut", "script"])
async def test_a_shortcut_or_script_whose_card_is_answered_after_stop_does_not_run(hands, stop_at_card, in_job,
                                                                                    monkeypatch, tool):
    ran = []

    async def run(argv, **kw):
        ran.append(argv)
        return {"ok": True, "external": False, "text": "ran"}
    monkeypatch.setattr(hands_tools, "_run", run)
    result = await (hands_tools.MacRunShortcutExecutor().execute({"name": "Tidy"}) if tool == "shortcut" else
                    hands_tools.MacAppleScriptExecutor().execute({"script": 'tell application "Notes" to activate'}))
    assert result["code"] == "stopped_by_user" and ran == []


# ── surviving mutations: a cap above five, every turn stopped, scheduled runs ────────────────────

async def test_a_new_turn_acts_while_a_stopped_turn_is_still_running(hands, asks, in_turn):
    press = hands_tools.DesktopPressExecutor()
    with desktop_status.working("c1"):                # stopped, and still in flight
        hands_service.stop_running_jobs()
        with desktop_status.working("c1"):            # the next message's turn starts meanwhile
            assert (await press.execute({"app": "Notes", "keys": "tab"}))["ok"]
        assert (await press.execute({"app": "Notes", "keys": "tab"}))["code"] == "stopped_by_user"
    assert hands.ops("press") == ["press"]


async def test_stop_stops_a_scheduled_run(hands, asks, in_turn):
    with desktop_status.working("c1", kind="scheduled"):
        hands_service.stop_running_jobs()
        result = await hands_tools.DesktopPressExecutor().execute({"app": "Notes", "keys": "tab"})
    assert result["code"] == "stopped_by_user" and hands.ops("press") == []


async def test_a_chat_turn_runs_past_the_old_cap_to_k4s_wrap_up(hands, asks, in_turn, monkeypatch):
    """The card: a chat turn acting many times meets the run's limit (K4), told in K4's own words."""
    from arslan.execution_budget import Budget, Limits, scope
    from arslan.models import LLMResponse
    from server.orchestrator import tool_loop
    systems, calls = [], iter(range(100))

    class Adapter:
        async def chat(self, system, user, history=None, tools=None, **kw):
            systems.append((user, tools))
            if tools and any(t["function"]["name"] == "desktop_press" for t in tools):
                i = next(calls)
                return LLMResponse(usage={}, content="", tool_calls=[{"id": f"c{i}", "type": "function", "function": {
                    "name": "desktop_press", "arguments": {"app": "Notes", "keys": "tab", "element": f"row {i}"}}}])
            return LLMResponse(usage={}, content="Done: moved through the list.")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())

    async def tools():
        return [{"key": "desktop_press", "description": "press"}]
    with desktop_status.working("c1"), scope(Budget(Limits(tool_calls=40), soft=Limits(tool_calls=30))) as budget:
        result = await tool_loop.run_native(system="S", user_content="tab through", history=[],
                                            resolve_tools=tools, emit=lambda e: None, on_chunk=lambda c: None)
    assert len(hands.ops("press")) == 30 == budget.tool_calls       # every one reached Hands; K4 stopped it
    assert result["final"] == "Done: moved through the list."
    assert any("Work budget nearly used" in s for s, _ in systems)
    assert json.dumps(systems[-1][1] or []).count("desktop_press") == 0


async def test_a_scheduled_run_keeps_five_actions_in_one_app(hands, asks, monkeypatch):
    async def exec_(*argv, **kw):
        raise AssertionError("a second app was opened in a scheduled run")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_)
    press = hands_tools.DesktopPressExecutor()
    with pc.bind(pc.TaskMemoryContext(task_id="s", run_id="fire-1", conversation_id="scheduled-1")), \
            desktop_status.working("scheduled-1", kind="scheduled"):
        codes = [(await press.execute({"app": "Notes", "keys": "tab"})).get("code") for _ in range(6)]
        assert codes == [None] * 5 + ["act_in_background"]
    with pc.bind(pc.TaskMemoryContext(task_id="s", run_id="fire-2", conversation_id="scheduled-1")), \
            desktop_status.working("scheduled-1", kind="scheduled"):
        assert (await press.execute({"app": "Notes", "keys": "tab"}))["ok"]          # the next fire starts at 0
        other = await press.execute({"app": "Messages", "keys": "tab"})
        opened = await hands_tools.DesktopOpenExecutor().execute({"app": "TextEdit"})   # not running: would open
    assert other["code"] == "act_in_background" and "one app" in other["error"]
    assert opened["code"] == "act_in_background"
    assert hands.ops("press") == ["press"] * 6


async def test_a_batch_in_a_scheduled_run_counts_each_step(hands, asks):
    steps = [{"action": "press", "keys": "tab"}] * 7
    with pc.bind(pc.TaskMemoryContext(task_id="s", run_id="fire-1", conversation_id="scheduled-1")), \
            desktop_status.working("scheduled-1", kind="scheduled"):
        result = await hands_tools.DesktopBatchExecutor().execute({"app": "Notes", "steps": steps})
    assert hands.ops("press") == ["press"] * hands_tools.SCHEDULED_ACTIONS
    assert f"stopped at step {hands_tools.SCHEDULED_ACTIONS + 1} (act_in_background)" in result["text"]


async def test_only_a_scheduled_run_is_told_of_the_cap(execution_db, hands, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(task_service, "current", lambda: object())

    async def described():
        return " ".join(t["description"] for t in await arslan._arslan_tools() if t["key"].startswith("desktop_"))
    with desktop_status.working("c1"):
        assert "five" not in await described()
    with desktop_status.working("scheduled-1", kind="scheduled"):
        # S1 (R7, U14 a): a scheduled run cannot act at all; the five-action cap stays behind it (⓪Plan, Q3)
        assert "A scheduled run cannot act on this Mac" in await described()


# ── S1a (U14 a): a scheduled run is told to tell the user, not to start background work ─────────────

def _scheduled():
    return desktop_status.working("scheduled-1", kind="scheduled")


async def _refusals() -> dict:
    with pc.bind(pc.TaskMemoryContext(task_id="s", run_id="fire-1", conversation_id="scheduled-1")):
        return {
            "browser": await hands_tools.BrowserClickExecutor().execute({"element": "Buy"}),
            "shortcut": await hands_tools.MacRunShortcutExecutor().execute({"name": "Morning"}),
            "takeover": await hands_tools.DesktopTakeoverExecutor().execute({"why": "tidy", "minutes": 5}),
        }


async def test_a_scheduled_runs_refusals_never_send_it_to_background_work(hands, asks):
    """R7 takes start_background_work out of a scheduled run; its refusals say what it can do instead."""
    with _scheduled():
        results = await _refusals()
    for name, result in results.items():
        assert result["code"] == "act_in_background" and result["executed"] is False, name
        assert "start_background_work" not in result["error"] and "Tell the user" in result["error"], name
        assert "background work" not in result["error"], name           # it has none (R7)
    assert hands.ops("press") == []


async def test_a_chat_turns_refusals_still_name_background_work(hands, asks):
    with desktop_status.working("c1"):
        results = await _refusals()
    assert all("start_background_work" in r["error"] for r in results.values()), results


async def test_the_scheduled_cap_says_tell_the_user(hands, asks):
    press = hands_tools.DesktopPressExecutor()
    with pc.bind(pc.TaskMemoryContext(task_id="s", run_id="fire-9", conversation_id="scheduled-1")), _scheduled():
        results = [await press.execute({"app": "Notes", "keys": "tab"}) for _ in range(hands_tools.SCHEDULED_ACTIONS + 1)]
    last = results[-1]
    assert last["code"] == "act_in_background" and "Tell the user" in last["error"]
    assert "start_background_work" not in last["error"]
