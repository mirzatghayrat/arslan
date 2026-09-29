"""0.1.45 hands: looking is free; acting happens only inside a background job and
asks first (once per website / per Shortcut, every time for an AppleScript);
passwords are never typed. The browser itself is faked here — nothing launches."""
import sys
from unittest.mock import AsyncMock

import pytest

from server.orchestrator import arslan
from server.registry import hands_tools
from server.services import agent_browser, approvals, background_jobs, personal_context as pc, task_service

pytestmark = pytest.mark.one_arslan


@pytest.fixture
def browser(monkeypatch):
    state = {"url": "https://github.com/me/repo", "calls": []}

    async def run(action, arguments):
        state["calls"].append((action, arguments))
        if action == "open":
            agent_browser.validate_url(arguments["url"])
            state["url"] = arguments["url"]
        return f"- Page URL: {state['url']}\n- button \"Star\" [ref=e1]"
    monkeypatch.setattr(agent_browser, "run", run)
    monkeypatch.setattr(agent_browser, "current_url", lambda: state["url"])
    monkeypatch.setattr(agent_browser, "available", lambda: True)
    return state


@pytest.fixture
def asks(monkeypatch):
    seen, answer = [], {"value": True}

    async def ask(conversation_id, frame):
        seen.append(frame)
        return answer["value"]
    monkeypatch.setattr(approvals, "ask", ask)
    return seen, answer


@pytest.fixture
def in_job():
    token = background_jobs._inside_job.set("job-1")
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c1")):
        yield
    background_jobs._inside_job.reset(token)
    hands_tools.forget_job("job-1")


async def test_a_turn_can_look_but_is_told_to_act_in_the_background(execution_db, browser, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(task_service, "current", lambda: object())
    keys = [t["key"] for t in await arslan._arslan_tools()]
    assert {"browser_open", "browser_look", "browser_back", "mac_list_shortcuts"} <= set(keys)
    assert not {"browser_click", "browser_type", "mac_run_shortcut", "mac_applescript"} & set(keys)
    result = await hands_tools.BrowserClickExecutor().execute({"element": "Star", "ref": "e1"})
    assert result["code"] == "act_in_background" and browser["calls"] == []


async def test_inside_a_job_the_hands_are_offered(execution_db, browser, in_job, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(task_service, "current", lambda: object())
    keys = {t["key"] for t in await arslan._arslan_tools()}
    assert {"browser_click", "browser_type", "browser_select", "browser_press",
            "mac_run_shortcut", "mac_applescript"} <= keys


async def test_the_first_action_on_a_site_asks_once_then_proceeds(browser, asks, in_job):
    seen, _ = asks
    click = hands_tools.BrowserClickExecutor()
    assert (await click.execute({"element": "Star", "ref": "e1"}))["ok"]
    assert (await click.execute({"element": "Star", "ref": "e1"}))["ok"]
    assert [(f["kind"], f["target"]) for f in seen] == [("browser_site", "https://github.com")]
    await hands_tools.BrowserOpenExecutor().execute({"url": "https://example.com/"})
    assert (await click.execute({"element": "Link", "ref": "e2"}))["ok"]
    assert [f["target"] for f in seen] == ["https://github.com", "https://example.com"], "a new site asks again"


async def test_a_declined_site_is_not_touched(browser, asks, in_job):
    _, answer = asks
    answer["value"] = False
    result = await hands_tools.BrowserClickExecutor().execute({"element": "Delete repo", "ref": "e9"})
    assert result["code"] == "declined"
    assert not [c for c in browser["calls"] if c[0] == "click"]


async def test_passwords_are_never_typed(browser, asks, in_job):
    seen, _ = asks
    for element in ("Password", "密码", "Enter your passcode"):
        result = await hands_tools.BrowserTypeExecutor().execute({"element": element, "ref": "e3", "text": "x"})
        assert result["code"] == "no_passwords"
    assert seen == [] and browser["calls"] == []


async def test_looking_is_free_and_page_text_is_marked_external(browser, asks, in_job):
    seen, _ = asks
    result = await hands_tools.BrowserOpenExecutor().execute({"url": "https://example.com/"})
    assert result["ok"] and result["external"] is True and seen == []
    bad = await hands_tools.BrowserOpenExecutor().execute({"url": "http://192.168.1.1/"})
    assert bad["ok"] is False


async def test_scripts_ask_every_time_shortcuts_once(asks, in_job, monkeypatch):
    seen, _ = asks
    ran = []

    async def fake_run(argv, *, timeout=120):
        ran.append(argv)
        return {"ok": True, "external": True, "text": "done", "summary": "done"}
    monkeypatch.setattr(hands_tools, "_run", fake_run)
    script = hands_tools.MacAppleScriptExecutor()
    shortcut = hands_tools.MacRunShortcutExecutor()
    for _ in range(2):
        assert (await script.execute({"script": 'tell application "Reminders" to count reminders'}))["ok"]
        assert (await shortcut.execute({"name": "Log water"}))["ok"]
    kinds = [f["kind"] for f in seen]
    assert kinds.count("mac_script") == 2 and kinds.count("mac_shortcut") == 1
    assert seen[0]["detail"].startswith('tell application "Reminders"'), "the full script is shown"
    assert len(ran) == 4


async def test_approvals_do_not_outlive_their_job(browser, asks):
    seen, _ = asks
    for job in ("job-a", "job-b"):
        token = background_jobs._inside_job.set(job)
        with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c1")):
            await hands_tools.BrowserClickExecutor().execute({"element": "Star", "ref": "e1"})
        background_jobs._inside_job.reset(token)
        hands_tools.forget_job(job)
    assert len(seen) == 2


async def test_effects_of_the_hands():
    assert await task_service.effect_of("browser_open", {}) == "read"
    assert await task_service.effect_of("browser_look", {}) == "read"
    assert await task_service.effect_of("browser_click", {}) == "external_write"
    assert await task_service.effect_of("mac_applescript", {}) == "external_write"
    assert await task_service.effect_of("mac_list_shortcuts", {}) == "read"


def test_the_card_answers_route_like_every_other_background_card():
    assert approvals.ANSWERS["confirm_action"] is True and approvals.ANSWERS["cancel_action"] is False
    assert AsyncMock  # (import kept for readers adding cases)


async def test_run_translates_to_playwright_0_0_80_and_always_returns_an_inline_snapshot(monkeypatch):
    """Probed in the real runtime: element args are `target`; actions reply with a
    snapshot FILE link, so every call is followed by an inline browser_snapshot."""
    calls = []

    async def call(tool, arguments):
        calls.append((tool, arguments))
        return "- Page URL: https://example.com/\n- link [ref=e13]" if tool == "browser_snapshot" else "[Snapshot](file.yml)"
    monkeypatch.setattr(agent_browser._worker, "call", call)
    text = await agent_browser.run("click", {"element": "More", "ref": "e13"})
    assert calls == [("browser_click", {"element": "More", "target": "e13"}), ("browser_snapshot", {})]
    assert "[ref=e13]" in text
    calls.clear()
    await agent_browser.run("look", {})
    assert calls == [("browser_snapshot", {})]
    with pytest.raises(ValueError):
        await agent_browser.run("open", {"url": "http://localhost:8080/"})
