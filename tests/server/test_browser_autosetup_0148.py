"""0.1.48: Arslan sets its own browser up the first time it needs it."""
from server.registry import hands_tools
from server.registry.executors import EXECUTORS
from server.services import agent_browser, managed_browser


def _stub(monkeypatch, *, first_error, setup_error=None):
    calls, setups = [], []

    async def run(action, args):
        calls.append(action)
        if len(calls) == 1 and first_error:
            raise agent_browser.BrowserUnavailable(first_error)
        return "page text"

    async def setup():
        setups.append(1)
        if setup_error:
            raise RuntimeError(setup_error)
        return {"ready": True}

    monkeypatch.setattr(agent_browser, "run", run)
    monkeypatch.setattr(managed_browser, "setup", setup)
    monkeypatch.setattr(agent_browser, "current_url", lambda: "https://example.com/")
    return calls, setups


async def test_first_use_sets_up_then_opens(monkeypatch):
    calls, setups = _stub(monkeypatch, first_error="setup_required")
    r = await EXECUTORS["browser_open"].execute({"url": "https://example.com/"})
    assert r["ok"] is True and r["text"] == "page text"
    assert setups == [1] and calls == ["open", "open"]


async def test_no_node_is_reported_honestly_and_no_setup_is_tried(monkeypatch):
    calls, setups = _stub(monkeypatch, first_error="node_required")
    r = await EXECUTORS["browser_open"].execute({"url": "https://example.com/"})
    assert r["ok"] is False and "Node.js" in r["error"] and "web_extract" in r["error"]
    assert setups == []


async def test_a_failed_setup_says_so_and_offers_the_way_around(monkeypatch):
    calls, setups = _stub(monkeypatch, first_error="setup_required", setup_error="npm ci: network down")
    r = await EXECUTORS["browser_open"].execute({"url": "https://example.com/"})
    assert r["ok"] is False and "network down" in r["error"] and "web_extract" in r["error"]
    assert calls == ["open"]


def test_the_message_never_sends_the_user_to_a_settings_page():
    assert "Settings" not in hands_tools._unavailable_message("setup_failed: x")
