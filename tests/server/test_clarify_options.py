"""PA-3 — ask_user_choice: when Arslan genuinely needs the user to pick a direction,
it calls a native TERMINAL tool that ends the turn with a structured `clarify_options`
card (2-4 one-click options) instead of a free-text counter-question that restarts the
confirm loop. These tests pin:
  - the tool is registered in Arslan's answer-path toolset (+ the system-prompt nudge);
  - a model tool_call → clarify_options frame with options CLAMPED to 4, a compact
    arslan message persisted (history/recap keep the context), stream_end fired, and
    the turn ENDED after ONE LLM call (terminal tool — no synthesis round);
  - <2 valid options → recoverable tool error, NO frame, the model answers normally;
  - a resolver that does NOT wire ask_user_choice (spawn loops) never reaches the
    terminal path — the call degrades to the ordinary "tool not available" error.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import ArslanMessage, Base
from server.orchestrator.tool_loop import _parse_clarify_args
from arslan.models import LLMResponse


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'clarify.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


class _ClarifyAdapter:
    """chat()-stub: first call emits an ask_user_choice tool_call with the configured
    options; any later call returns a plain final answer. Records calls."""

    def __init__(self, options, question="接下来往哪个方向推进?"):
        self.chat_calls: list[dict] = []
        self._options = options
        self._question = question

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.chat_calls.append({"system": system, "user": user, "history": history,
                                "tools": tools})
        if len(self.chat_calls) == 1:
            return LLMResponse(content="", tool_calls=[{
                "id": "c1", "type": "function",
                "function": {"name": "ask_user_choice",
                             "arguments": {"question": self._question,
                                           "options": self._options}},
            }], usage={})
        return LLMResponse(content="好的,那我按通用方案来回答你。", tool_calls=[], usage={})


# ---------------------------------------------------------------------------
# Unit tier: _parse_clarify_args (validate + clamp)
# ---------------------------------------------------------------------------

def test_parse_clarify_args_clamps_to_four():
    args = {"question": "选哪个?",
            "options": [{"label": f"方向{i}", "hint": f"提示{i}"} for i in range(1, 6)]}
    clarify, err = _parse_clarify_args(args)
    assert err is None
    assert clarify["question"] == "选哪个?"
    assert [o["label"] for o in clarify["options"]] == ["方向1", "方向2", "方向3", "方向4"]
    assert clarify["options"][0]["hint"] == "提示1"


def test_parse_clarify_args_rejects_fewer_than_two():
    clarify, err = _parse_clarify_args({"question": "q", "options": [{"label": "只有一个"}]})
    assert clarify is None
    assert err  # recoverable tool error text the model can react to


def test_parse_clarify_args_rejects_missing_question_and_dedupes():
    assert _parse_clarify_args({"options": [{"label": "a"}, {"label": "b"}]})[0] is None
    # duplicate labels collapse — 2 copies of one option are NOT two choices
    clarify, err = _parse_clarify_args(
        {"question": "q", "options": [{"label": "同"}, {"label": "同"}]})
    assert clarify is None and err
    # bare-string options are accepted (some models send ["A", "B"])
    clarify, err = _parse_clarify_args({"question": "q", "options": ["走 A", "走 B"]})
    assert err is None
    assert [o["label"] for o in clarify["options"]] == ["走 A", "走 B"]


# ---------------------------------------------------------------------------
# Registration tier
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ask_user_choice_registered_in_arslan_toolset(maker):
    from server.orchestrator import arslan
    tools = await arslan._arslan_tools()
    assert any(t["key"] == "ask_user_choice" for t in tools)


# ---------------------------------------------------------------------------
# Flow tier: the real _handle_answer wiring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clarify_call_emits_frame_persists_message_and_ends_turn(maker, monkeypatch):
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    five = [{"label": f"方向{i}", "hint": f"提示{i}"} for i in range(1, 6)]
    adapter = _ClarifyAdapter(five)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events = []
    await arslan.handle_user_message("main", "帮我推进那个项目", events.append)

    # 1. exactly one clarify_options frame, options clamped 5 → 4, hints carried
    frames = [e for e in events if e["type"] == "clarify_options"]
    assert len(frames) == 1
    assert frames[0]["question"] == "接下来往哪个方向推进?"
    assert [o["label"] for o in frames[0]["options"]] == ["方向1", "方向2", "方向3", "方向4"]
    assert frames[0]["options"][0]["hint"] == "提示1"

    # 2. terminal: ONE LLM call total (no synthesis / follow-up round), stream closed
    assert len(adapter.chat_calls) == 1
    assert any(e["type"] == "stream_end" for e in events)

    # 3. the answer-path toolset really offered the tool + the system nudge is present
    tool_names = [t["function"]["name"] for t in (adapter.chat_calls[0]["tools"] or [])]
    assert "ask_user_choice" in tool_names
    assert "ask_user_choice" in adapter.chat_calls[0]["system"]

    # 4. compact text twin persisted (question + bulleted labels) so history/recap keep context
    async with db_session.AsyncSessionLocal() as s:
        msgs = (await s.execute(
            select(ArslanMessage).order_by(ArslanMessage.id))).scalars().all()
    arslan_msgs = [m for m in msgs if m.role == "arslan"]
    assert arslan_msgs
    compact = arslan_msgs[-1].content
    assert "接下来往哪个方向推进?" in compact
    for lab in ("方向1", "方向2", "方向3", "方向4"):
        assert lab in compact
    assert "方向5" not in compact  # clamp applies to the persisted twin too


@pytest.mark.asyncio
async def test_too_few_options_is_recoverable_tool_error_no_frame(maker, monkeypatch):
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    adapter = _ClarifyAdapter([{"label": "只有一个"}])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events = []
    await arslan.handle_user_message("main", "帮我推进", events.append)

    # no card frame; the model saw a TOOL RESULT error and recovered with a plain answer
    assert [e for e in events if e["type"] == "clarify_options"] == []
    assert len(adapter.chat_calls) == 2
    assert "TOOL RESULT for ask_user_choice" in adapter.chat_calls[1]["user"]
    streamed = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
    assert "通用方案" in streamed


@pytest.mark.asyncio
async def test_unwired_resolver_never_reaches_terminal_path(monkeypatch):
    """A resolver WITHOUT ask_user_choice (spawn loops) must not end the turn with a
    clarify — the call degrades to the ordinary 'tool not available' error."""
    from server.orchestrator import tool_loop

    adapter = _ClarifyAdapter([{"label": "A"}, {"label": "B"}])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    async def _resolve():
        return [{"key": "web_search", "description": "d"}]

    events = []
    result = await tool_loop.run_native(
        system="s", user_content="u", history=[], emit=events.append,
        on_chunk=lambda c: None, resolve_tools=_resolve, allow_escalation=False)
    assert result.get("clarify") is None
    assert result["final"]  # recovered into a normal answer
    assert [e for e in events if e.get("type") == "clarify_options"] == []
