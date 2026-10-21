"""K4b: a long chat turn is told once that it may continue the rest as background work (⓪Plan Q1 = A).

After LONG_TURN_S of the turn's own time (a card's wait doesn't count), the next step's status block
carries one note for the model, and the user's reply gets one `note` line. Never twice in a turn, never
where start_background_work isn't offered (inside a job), and never in the system text or the tools:
K3's prefix stays byte-identical.
"""
import asyncio
import copy
import types

import pytest

from arslan import execution_budget as eb
from server.orchestrator import agent_status, tool_loop
from server.services import runtime_messages
from tests.server import test_trajectory_golden as golden


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


class _Recorder:
    def __init__(self, replies):
        self._r = list(replies)
        self.calls = []

    def native_trajectory(self):
        return True

    async def chat_trajectory(self, system, messages, tools=None, tool_choice=None, **kw):
        self.calls.append({"system": system, "messages": copy.deepcopy(messages),
                           "tools": None if tools is None else copy.deepcopy(tools)})
        return self._r.pop(0)


class _Search:
    """Each search takes `minutes` of the turn's time; inside a card's wait when `waiting`."""

    def __init__(self, clock, minutes, waiting=False):
        self.clock, self.minutes, self.waiting = clock, minutes, waiting

    async def execute(self, args):
        if self.waiting:
            with eb.paused():
                self.clock.now += self.minutes * 60
        else:
            self.clock.now += self.minutes * 60
        return {"ok": True, "results": [{"title": args["query"], "url": f"https://example.test/{args['query']}"}]}


def _searches(n):
    return [golden._Resp(None, [golden._tc("web_search", {"query": f"q{i}"}, f"s{i}")]) for i in range(n)]


async def _run(monkeypatch, *, minutes, waiting=False, offer_background=True):
    clock = _Clock()
    monkeypatch.setattr(eb, "time", types.SimpleNamespace(monotonic=clock.monotonic))

    async def english():
        return "en"
    monkeypatch.setattr(runtime_messages, "selected_locale", english)
    adapter = _Recorder(_searches(3) + [golden._Resp("Done.")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Search(clock, minutes, waiting))

    async def resolve():
        tools = [{"key": "web_search", "description": "search"}]
        return tools + ([{"key": "start_background_work", "description": "background"}] if offer_background else [])
    frames = []
    budget = eb.run_budget()
    async with asyncio.timeout(None) as timeout:
        with eb.scope(budget), eb.running_clock(budget, timeout):
            result = await tool_loop.run_native(system="SYS", user_content="research a lot", history=[],
                                                emit=frames.append, on_chunk=lambda c: None, resolve_tools=resolve)
    return result, adapter.calls, frames


def _status(call):
    content = call["messages"][-1]["content"]
    return content[content.rindex(agent_status.OPEN):] if agent_status.OPEN in content else ""


def _long_notes(frames):
    return [f for f in frames if f.get("type") == "note" and "10 minutes" in f.get("text", "")]


async def test_a_long_turn_is_told_once_in_the_status_block_and_the_user_sees_one_line(monkeypatch):
    result, calls, frames = await _run(monkeypatch, minutes=11)
    assert result["final"] == "Done."
    told = [i for i, call in enumerate(calls) if "start_background_work" in _status(call) and "10 minutes" in _status(call)]
    assert told == [1]                                            # after the first 11-minute step, once
    assert "what is already done" in _status(calls[1]) and "what remains" in _status(calls[1])
    assert _long_notes(frames) == [{"type": "note", "text": runtime_messages.render("turn_long", "en", minutes=10)}]
    # K3: the note never touches the cached prefix — the same system text and tools on every step, and each
    # request repeats the previous one byte for byte up to its status block.
    assert len({c["system"] for c in calls}) == 1 and all("10 minutes" not in c["system"] for c in calls)
    assert all(c["tools"] == calls[0]["tools"] for c in calls[:-1])
    for before, after in zip(calls[1:], calls[2:]):
        assert after["messages"][:len(before["messages"]) - 1] == before["messages"][:-1]


async def test_a_card_wait_does_not_count_toward_a_long_turn(monkeypatch):
    # 20 minutes: past LONG_TURN_S, short of the 30-minute soft wall clock (whose wrap-up would mask it)
    _, calls, frames = await _run(monkeypatch, minutes=20, waiting=True)
    assert not any("10 minutes" in _status(call) for call in calls) and _long_notes(frames) == []


async def test_a_short_turn_never_hears_it(monkeypatch):
    _, calls, frames = await _run(monkeypatch, minutes=3)                # 9 minutes in all
    assert not any("10 minutes" in _status(call) for call in calls) and _long_notes(frames) == []


async def test_no_note_where_background_work_is_not_offered(monkeypatch):
    """Inside a job (or anywhere start_background_work isn't a tool) there is nowhere to move to."""
    _, calls, frames = await _run(monkeypatch, minutes=11, offer_background=False)
    assert not any("10 minutes" in _status(call) for call in calls) and _long_notes(frames) == []


@pytest.mark.parametrize("locale", ["en", "zh", "ja", "es", "de", "fr"])
def test_the_user_line_exists_in_every_language_and_names_the_minutes(locale):
    assert str(tool_loop.LONG_TURN_S // 60) in runtime_messages.render("turn_long", locale, minutes=10)
