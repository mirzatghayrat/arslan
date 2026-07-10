"""S0 hemostasis — zero-tool (persona-only) spawns must get the SAME final-answer honesty
guards the equipped/answer paths get.

The gap (product audit): dispatcher.py's zero-tool branch streamed a persona-only spawn's
reply RAW — no deck/chart/search-claim guard, no forward-promise nudge, no salvage. So a
tool-less spawn could fabricate "已生成PPT并交付" / "正在生成中,稍等" completely unchecked,
the exact fabrication class the HX/PA rounds killed on the equipped path.

The fix reuses the REAL guard functions (promise_guard.find_promise ∪ tool_loop._claims_deck
/ _claims_search) + the same bounded correction, so the zero-tool path is corrected the same
way — never a weaker parallel copy. These tests pin:
  - the unit: promise_guard.correct_zero_tool detects deck/promise fabrication, corrects once,
    templates on re-fabrication, and leaves honest text untouched (no LLM call);
  - the flow: dispatcher.dispatch on a ZERO-TOOL spawn (unseeded registry → no wired tools →
    the legacy chat_stream branch) appends + streams the honest correction and keeps the
    original text; an honest reply passes through byte-for-byte with no extra LLM call.
"""
import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ConversationEvent, Spawn
from server.orchestrator import promise_guard


# ---------------------------------------------------------------------------
# Unit: promise_guard.correct_zero_tool (mirrors test_promise_guard's _SeqAdapter style)
# ---------------------------------------------------------------------------
class _SeqAdapter:
    """chat()-based stub returning queued contents in order; records every call."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.chat_calls: list[dict] = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.chat_calls.append({"system": system, "user": user})
        from arslan.models import LLMResponse
        content = self._replies.pop(0) if self._replies else ""
        return LLMResponse(content=content, tool_calls=[], usage={})


DECK_FAB = "已生成PPT并交付,共10页,内容涵盖注册、身份认证、法币入金、现货交易等章节,可直接下载。"
PROMISE_FAB = "好的,我这就为你把方案整理成 PPT,正在生成中,稍等,生成好第一时间发你。"
HONEST_FIX = "更正:我没有配备相应工具,做不出这个文件,上面的说法并不属实。"
HONEST_ANSWER = "护肤三步:先温和洁面,再用爽肤水二次清洁,最后涂保湿霜锁水。坚持一个月肤质会明显改善,白天务必防晒。"


@pytest.mark.asyncio
async def test_correct_zero_tool_none_on_honest_answer(monkeypatch):
    from server.orchestrator import tool_loop
    adapter = _SeqAdapter([HONEST_FIX])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    assert await promise_guard.correct_zero_tool(HONEST_ANSWER) is None
    assert adapter.chat_calls == []  # honest → zero extra LLM calls


@pytest.mark.asyncio
async def test_correct_zero_tool_corrects_deck_claim(monkeypatch):
    """The task's primary example: '已生成PPT并交付' — caught by tool_loop._claims_deck
    (find_promise misses it), corrected via one bounded re-synthesis."""
    from server.orchestrator import tool_loop
    adapter = _SeqAdapter([HONEST_FIX])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await promise_guard.correct_zero_tool(DECK_FAB)
    assert out is not None
    assert out["correction"] == HONEST_FIX
    assert out["corrected"] is True
    assert out["pattern"]  # a matched snippet / claim kind
    assert len(adapter.chat_calls) == 1


@pytest.mark.asyncio
async def test_correct_zero_tool_corrects_forward_promise(monkeypatch):
    """The HX incident class: '正在生成中,稍等' — caught by promise_guard.find_promise."""
    from server.orchestrator import tool_loop
    adapter = _SeqAdapter([HONEST_FIX])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await promise_guard.correct_zero_tool(PROMISE_FAB)
    assert out is not None
    assert out["correction"] == HONEST_FIX
    assert out["corrected"] is True
    assert len(adapter.chat_calls) == 1


@pytest.mark.asyncio
async def test_correct_zero_tool_templates_when_resynthesis_refabricates(monkeypatch):
    from server.orchestrator import tool_loop
    # the re-synthesis ALSO fabricates → deterministic template, never a second LLM loop
    adapter = _SeqAdapter(["别急,PPT 正在生成中,稍等"])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await promise_guard.correct_zero_tool(DECK_FAB)
    assert out is not None
    assert out["corrected"] is False
    assert "更正" in out["correction"]
    # the template itself must not re-trip the guard (no promise / claim language)
    assert promise_guard.correct_zero_tool  # sanity
    from server.orchestrator import tool_loop as tl
    assert promise_guard.find_promise(out["correction"]) is None
    assert not tl._claims_deck(out["correction"])
    assert not tl._claims_search(out["correction"])
    assert len(adapter.chat_calls) == 1  # bounded: exactly one


@pytest.mark.asyncio
async def test_correct_zero_tool_fail_open_on_llm_error(monkeypatch):
    from server.orchestrator import tool_loop

    def _boom():
        raise RuntimeError("no adapter")

    monkeypatch.setattr(tool_loop, "_get_adapter", _boom)
    out = await promise_guard.correct_zero_tool(DECK_FAB)
    assert out is not None
    assert out["corrected"] is False
    assert "更正" in out["correction"]


# ---------------------------------------------------------------------------
# Flow: dispatcher.dispatch on a ZERO-TOOL spawn (unseeded registry → no wired tools)
# ---------------------------------------------------------------------------
@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'zt.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            # NO registry seed → wired_tools_for_spawn returns [] → the zero-tool branch.
            s.add(Spawn(id=7, name="persona", domain_category="content-creator",
                        system_prompt="You are a persona-only assistant with no tools."))
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


class _StreamStub:
    """dispatcher adapter: chat_stream yields a preset final reply (the persona output)."""

    def __init__(self, reply):
        self._reply = reply

    async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
        yield self._reply


class _ChatStub:
    """tool_loop adapter used by correct_zero_tool's bounded re-synthesis."""

    def __init__(self, reply):
        self._reply = reply
        self.calls: list[dict] = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.calls.append({"system": system, "user": user})
        from arslan.models import LLMResponse
        return LLMResponse(content=self._reply, tool_calls=[], usage={})


@pytest.mark.asyncio
async def test_zero_tool_dispatch_deck_fabrication_is_corrected(maker, monkeypatch):
    """THE gap, closed: a persona-only spawn fabricates a delivered PPT → the correction is
    appended (persisted in full_output) AND streamed live; the original text is kept; exactly
    ONE bounded re-synthesis fires; a promise_intercept(tier=zero_tool) audit event is logged."""
    from server.orchestrator import dispatcher, tool_loop

    chat_stub = _ChatStub(HONEST_FIX)
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _StreamStub(DECK_FAB))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: chat_stub)

    chunks: list[str] = []
    out = await dispatcher.dispatch("main", spawn_id=7, task_brief="给我做个 OKX 新手 PPT",
                                    on_chunk=chunks.append)

    # correction appended + persisted, original fabrication kept
    assert HONEST_FIX in out["full_output"]
    assert DECK_FAB in out["full_output"]
    # correction streamed live (not just persisted)
    assert HONEST_FIX in "".join(chunks)
    # exactly one bounded re-synthesis LLM call
    assert len(chat_stub.calls) == 1
    # audit event
    async with db_session.AsyncSessionLocal() as s:
        evs = (await s.execute(select(ConversationEvent))).scalars().all()
    hits = [e for e in evs if e.kind == "promise_intercept"]
    assert len(hits) == 1
    assert hits[0].ref["tier"] == "zero_tool"
    assert hits[0].ref["pattern"]


@pytest.mark.asyncio
async def test_zero_tool_dispatch_forward_promise_is_corrected(maker, monkeypatch):
    from server.orchestrator import dispatcher, tool_loop

    chat_stub = _ChatStub(HONEST_FIX)
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _StreamStub(PROMISE_FAB))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: chat_stub)

    chunks: list[str] = []
    out = await dispatcher.dispatch("main", spawn_id=7, task_brief="做个方案",
                                    on_chunk=chunks.append)
    assert HONEST_FIX in out["full_output"]
    assert HONEST_FIX in "".join(chunks)
    assert len(chat_stub.calls) == 1


@pytest.mark.asyncio
async def test_zero_tool_dispatch_honest_answer_untouched(maker, monkeypatch):
    """No false positive: an honest persona reply passes through byte-for-byte with NO
    correction appended and NO extra LLM call."""
    from server.orchestrator import dispatcher, tool_loop

    chat_stub = _ChatStub("SHOULD NOT BE CALLED")
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _StreamStub(HONEST_ANSWER))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: chat_stub)

    chunks: list[str] = []
    out = await dispatcher.dispatch("main", spawn_id=7, task_brief="护肤建议",
                                    on_chunk=chunks.append)
    assert out["full_output"] == HONEST_ANSWER   # unchanged
    assert "".join(chunks) == HONEST_ANSWER      # nothing extra streamed
    assert chat_stub.calls == []                 # no re-synthesis call
    async with db_session.AsyncSessionLocal() as s:
        evs = (await s.execute(select(ConversationEvent))).scalars().all()
    assert [e for e in evs if e.kind == "promise_intercept"] == []
