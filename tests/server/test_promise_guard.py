"""HX-1 A2+A3 — 空头支票拦截(deterministic promise interceptor)+ 主脑铁律.

Live incident (fully diagnosed): router said route→spawn, the doer-first gate diverted
to Arslan's self-answer, and the answer LLM FABRICATED "我把 PPT 交给 Deck Master 来生成,
它正在生成中,稍等" — zero dispatch, zero runs. These tests pin:
  - the regex tier (unit): real incident strings hit, honest text does not;
  - the regression (acceptance #4): route→doer-first→promising answer → bounded honest
    correction emitted+persisted, promise_intercept audit event logged, NO dispatch;
  - the false-positive guard (acceptance #1, GENERIC tier only): a turn that actually
    used tools never triggers on generic promise language;
  - A3: the built system prompt carries the no-background-execution iron rule.

PA-1 (second live incident, thread-1783523936187): the guard block sat behind a GLOBAL
`not tool_trace` exemption — Arslan called web_search every turn while its final text
claimed 「现在让 **Deck Master** 直接出PPT」 five turns in a row with ZERO dispatch, so
the guard never ran. The exemptions are now SPLIT: spawn-specific promises are exempt
only when the turn actually delegated (dispatch/propose_invite); generic promises keep
the tool_trace exemption. 验收③ replays all five real corpus sentences verbatim.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import ArslanMessage, Base, ConversationEvent, Spawn
from server.orchestrator import promise_guard


# ---------------------------------------------------------------------------
# Unit tier: the deterministic regexes
# ---------------------------------------------------------------------------

INCIDENT_1 = "现在我把完整的 OKX 新手指南 PPT 交给 Deck Master 来生成"
INCIDENT_2 = "它正在生成中,稍等"


def test_promise_re_hits_real_incident_strings():
    assert promise_guard.PROMISE_RE.search(INCIDENT_1)
    assert promise_guard.PROMISE_RE.search(INCIDENT_2)


def test_promise_re_hits_english_promises():
    assert promise_guard.PROMISE_RE.search("I'm working on it right now")
    assert promise_guard.PROMISE_RE.search("The deck is Generating, hang tight")
    assert promise_guard.PROMISE_RE.search("your report is in progress")
    assert promise_guard.PROMISE_RE.search("I'll get that over to the team")
    assert promise_guard.PROMISE_RE.search("I’ll have it ready")  # curly apostrophe


def test_promise_re_does_not_hit_honest_text():
    assert promise_guard.PROMISE_RE.search("我没有派发任务,这是我自己写的回答") is None
    assert promise_guard.PROMISE_RE.search("已完成,如下") is None
    assert promise_guard.PROMISE_RE.search("这是我直接给你的答案:第一……") is None


def test_find_promise_returns_snippet_and_union():
    assert promise_guard.find_promise("它正在生成中") == "正在生成"
    # K5: the spawn tier is gone — "让 <name> 跟进" is no longer a promise by itself
    assert promise_guard.find_promise("这事我让 Writer 跟进吧") is None
    assert promise_guard.find_promise("平平无奇的回答") is None
    assert promise_guard.find_promise("") is None


# ---------------------------------------------------------------------------
# Bounded correction unit: resynthesis once, template fallback, never loops
# ---------------------------------------------------------------------------


class _SeqAdapter:
    """chat()-based stub returning queued contents in order; records every call."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.chat_calls: list[dict] = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.chat_calls.append({"system": system, "user": user, "history": history,
                                "tools": tools, "temperature": temperature})
        from arslan.models import LLMResponse
        content = self._replies.pop(0) if self._replies else ""
        return LLMResponse(content=content, tool_calls=[], usage={})


PROMISING = ("好的,这个 OKX 新手指南我理解了。考虑到内容量和排版要求,做成 PPT 最合适。"
             "现在我把完整的 OKX 新手指南 PPT 交给 Deck Master 来生成,它正在生成中,稍等,"
             "生成好我第一时间给你。")
HONEST_FIX = "更正:上面的内容是我自己作答的,没有任何任务被派发,也没有东西在后台运行。"


@pytest.mark.asyncio
async def test_correct_returns_none_without_promise(monkeypatch):
    from server.orchestrator import tool_loop
    adapter = _SeqAdapter([HONEST_FIX])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    assert await promise_guard.correct("已完成,如下") is None
    assert adapter.chat_calls == []  # no promise → zero extra LLM calls


@pytest.mark.asyncio
async def test_correct_resynthesizes_once_with_truth_statement(monkeypatch):
    from server.orchestrator import tool_loop
    adapter = _SeqAdapter([HONEST_FIX])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await promise_guard.correct(PROMISING)
    assert out is not None
    assert out["correction"] == HONEST_FIX
    assert out["corrected"] is True
    assert out["pattern"]
    # exactly ONE bounded LLM call, and its prompt states the literal truth
    assert len(adapter.chat_calls) == 1
    sent = adapter.chat_calls[0]["system"] + adapter.chat_calls[0]["user"]
    assert "这一轮没有调用任何工具" in sent


@pytest.mark.asyncio
async def test_correct_falls_back_to_template_when_resynthesis_also_promises(monkeypatch):
    from server.orchestrator import tool_loop
    # correction attempt ALSO promises → deterministic template, never a second LLM loop
    adapter = _SeqAdapter(["别急,正在生成中,稍等"])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await promise_guard.correct(PROMISING)
    assert out is not None
    assert out["corrected"] is False
    assert "Correction" in out["correction"] and "my own" in out["correction"]
    assert len(adapter.chat_calls) == 1  # bounded: never more than one


@pytest.mark.asyncio
async def test_correct_falls_back_to_template_on_llm_error(monkeypatch):
    from server.orchestrator import tool_loop

    def _boom():
        raise RuntimeError("no adapter")

    monkeypatch.setattr(tool_loop, "_get_adapter", _boom)
    out = await promise_guard.correct(PROMISING)
    assert out is not None
    assert out["corrected"] is False
    assert "Correction" in out["correction"]


# ---------------------------------------------------------------------------
# Flow tier: the real _handle_answer / doer-first wiring (acceptance #1 + #4)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'guard.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with m() as s:
        s.add(Spawn(id=6, name="Deck Master", domain_category="content-creator",
                    capabilities=["deck"], system_prompt="You make decks."))
        s.add(Spawn(id=7, name="Research Analyst", domain_category="researcher",
                    capabilities=["research"], system_prompt="You research."))
        await s.commit()

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


# Long (>160 chars) so tool_loop's deferral-stub salvage doesn't consume mock replies first.
PROMISING_LONG = PROMISING + "这份 PPT 会覆盖注册、身份认证、法币入金、现货交易、合约风险提示等章节," \
                             "每一节都配有操作截图位与要点说明,整体控制在二十页以内,风格沿用你上次喜欢的深色模板。"


@pytest.mark.asyncio
async def test_tier2_generic_answer_promise_is_intercepted(maker, monkeypatch):
    """Plain answer turn (no spawn inferred): generic PROMISE_RE still triggers, audit
    event says tier=answer, and the correction prompt has no spawn name requirement."""
    from server.orchestrator import arslan, tool_loop


    adapter = _SeqAdapter([PROMISING_LONG, HONEST_FIX])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events = []
    await arslan.handle_user_message("main", "帮我做个东西", events.append)

    streamed = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
    assert HONEST_FIX in streamed
    async with db_session.AsyncSessionLocal() as s:
        evs = (await s.execute(select(ConversationEvent))).scalars().all()
    hits = [e for e in evs if e.kind == "promise_intercept"]
    assert len(hits) == 1
    assert hits[0].ref["tier"] == "answer"


@pytest.mark.asyncio
async def test_generic_tier_stays_quiet_while_a_background_job_really_runs(maker, monkeypatch):
    """0.1.42: with a job of this conversation running, "it's being done in the
    background" is true; the correction ("nothing is running") would be the lie.
    A finished job does not count — the guard is back once nothing runs."""
    from server.orchestrator import arslan, tool_loop
    from server.services import background_jobs


    background_jobs._reset_for_tests()
    job = background_jobs.Job(job_id="job-live", conversation_id="main", goal="deck", acceptance=[])
    job.phase = "running"
    background_jobs._jobs[job.job_id] = job
    try:
        adapter = _SeqAdapter([PROMISING_LONG, HONEST_FIX])
        monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
        events = []
        await arslan.handle_user_message("main", "进度怎么样", events.append)
        streamed = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
        assert HONEST_FIX not in streamed
        job.phase = "finished"
        adapter = _SeqAdapter([PROMISING_LONG, HONEST_FIX])
        monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
        events = []
        await arslan.handle_user_message("main", "帮我做个东西", events.append)
        streamed = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
        assert HONEST_FIX in streamed
    finally:
        background_jobs._reset_for_tests()


@pytest.mark.asyncio
async def test_negative_tool_using_answer_never_triggers(maker, monkeypatch):
    """Acceptance #1 false-positive guard — GENERIC tier only (PA-1 narrowed this): on a
    plain answer turn (no spawn inferred, so the spawn tier is inactive) that actually
    CALLED a tool, generic promising language ('正在…' narrating real work) must NOT
    trigger the interceptor. Spawn-delegation claims are NOT exempted by tool use — see
    the PA-1 corpus tests below."""
    from server.orchestrator import arslan, tool_loop
    from server.registry import executors
    from arslan.models import LLMResponse


    class _ToolThenPromise:
        def __init__(self):
            self.chat_calls = []
            self._n = 0

        async def chat(self, system, user, history=None, tools=None, temperature=0.7):
            self.chat_calls.append({"system": system, "user": user})
            self._n += 1
            if self._n == 1:
                return LLMResponse(content="", tool_calls=[{
                    "id": "c1", "type": "function",
                    "function": {"name": "web_search", "arguments": {"query": "okx"}},
                }], usage={})
            return LLMResponse(content=PROMISING_LONG, tool_calls=[], usage={})

    adapter = _ToolThenPromise()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    class _Stub:
        async def execute(self, args):
            return {"ok": True, "results": [{"title": "t", "url": "u"}]}

    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Stub())

    events = []
    await arslan.handle_user_message("main", "查一下 okx 然后总结", events.append)

    assert len(adapter.chat_calls) == 2  # tool step + final — NO correction call
    async with db_session.AsyncSessionLocal() as s:
        evs = (await s.execute(select(ConversationEvent))).scalars().all()
    assert [e for e in evs if e.kind == "promise_intercept"] == []
    streamed = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
    assert "更正" not in streamed


@pytest.mark.asyncio
async def test_interceptor_failure_is_fail_open(maker, monkeypatch):
    """Interceptor errors must never break the answer turn: the promising answer is
    still persisted and stream_end still fires."""
    from server.orchestrator import arslan, tool_loop


    adapter = _SeqAdapter([PROMISING_LONG])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    async def _boom(*a, **k):
        raise RuntimeError("guard exploded")

    monkeypatch.setattr(arslan.promise_guard, "correct", _boom)

    events = []
    await arslan.handle_user_message("main", "帮我做个东西", events.append)
    types = [e["type"] for e in events]
    assert "stream_end" in types
    async with db_session.AsyncSessionLocal() as s:
        msgs = (await s.execute(select(ArslanMessage))).scalars().all()
    assert any(m.role == "arslan" and PROMISING_LONG in m.content for m in msgs)


# ---------------------------------------------------------------------------
# A3 iron rule (constant-level pin, in addition to the flow assert above)
# ---------------------------------------------------------------------------


def test_a3_iron_rule_constant():
    # 0.1.48: background work exists now (0.1.42); the rule is that nothing is described as
    # running unless a tool call started it.
    from server.orchestrator import arslan
    assert "start_background_work" in arslan._NO_BACKGROUND_EXEC
    assert "Never describe something as in progress" in arslan._NO_BACKGROUND_EXEC


# ---------------------------------------------------------------------------
# PA-4: no-repaste iron rule (constant pin + built-prompt flow assert, A3 pattern)
# ---------------------------------------------------------------------------


def test_pa4_no_repaste_rule_constant():
    from server.orchestrator import arslan
    assert "is never re-pasted whole" in arslan._NO_REPASTE
    assert "same outline as above" in arslan._NO_REPASTE


@pytest.mark.asyncio
async def test_pa4_answer_system_prompt_carries_no_repaste_rule(maker, monkeypatch):
    """PA-4: the converse system prompt must carry the no-repaste rule — the live
    incident re-pasted the SAME outline verbatim 3x across consecutive answer turns."""
    from server.orchestrator import arslan, tool_loop


    honest_long = "这是一段普通的、不含任何承诺语言、也不重贴旧内容的长回答,用来验证系统提示词。" * 5
    adapter = _SeqAdapter([honest_long])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    await arslan.handle_user_message("main", "随便聊聊", lambda e: None)

    assert "is never re-pasted whole" in adapter.chat_calls[0]["system"]
