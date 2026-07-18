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
from server.db.models import ArslanMessage, Base, ConversationEvent, Run, Spawn
from server.orchestrator import promise_guard


@pytest.fixture(autouse=True)
def _gate_no_llm(monkeypatch):
    """BUG1 cell-6 domain gate hygiene: this file's maker harness is a REAL sqlite with
    EMPTY provider tables, so the gate's draft adapter would legacy-fall-back to a LIVE
    api.openai.com call from inside a unit test. Neutralize the gate's LLM leg (null =
    no contradiction = chip floats, the pre-gate behavior these tests pin). The gate
    itself is tested in test_task_arbitration.py."""
    from server.services import staffing_gather

    async def _none(*a, **k):
        return None
    monkeypatch.setattr(staffing_gather, "extract_conflicting_domain", _none)

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


def test_spawn_promise_re_high_precision():
    rx = promise_guard.spawn_promise_re("Deck Master")
    assert rx.search("我把这个交给 Deck Master")
    assert rx.search("让 deck master 处理")
    assert rx.search("派 Deck Master 去做")
    assert rx.search("I handed it to Deck Master")
    assert rx.search("提到 Deck Master 这个名字而已") is None  # bare mention ≠ handoff claim
    # a DIFFERENT spawn's name doesn't hit this spawn's pattern
    assert promise_guard.spawn_promise_re("Research Analyst").search("交给 Deck Master") is None


def test_find_promise_returns_snippet_and_union():
    assert promise_guard.find_promise("它正在生成中") == "正在生成"
    # PROMISE_RE misses, spawn pattern catches (union semantics)
    text = "这事我让 Writer 跟进吧"
    assert promise_guard.PROMISE_RE.search(text) is None
    assert promise_guard.find_promise(text, spawn_name="Writer")
    assert promise_guard.find_promise("平平无奇的回答", spawn_name="Writer") is None
    assert promise_guard.find_promise("", spawn_name=None) is None


def test_find_promise_spawn_only_gate():
    """PA-1: the two tiers sit behind DIFFERENT exemption gates, so the caller must be
    able to scan the spawn tier alone (check_generic=False) when the generic tier is
    exempt (tool_trace non-empty) but the spawn tier is not (no real delegation)."""
    # generic-only promise language is ignored when the generic tier is gated off
    assert promise_guard.find_promise("它正在生成中,稍等", check_generic=False) is None
    assert promise_guard.find_promise(
        "它正在生成中,稍等", spawn_name="Deck Master", check_generic=False) is None
    # the spawn tier stays active without the generic tier
    assert promise_guard.find_promise(
        "现在让 Deck Master 直接出PPT", spawn_name="Deck Master", check_generic=False)


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
    assert await promise_guard.correct("已完成,如下", spawn_name="Deck Master") is None
    assert adapter.chat_calls == []  # no promise → zero extra LLM calls


@pytest.mark.asyncio
async def test_correct_resynthesizes_once_with_truth_statement(monkeypatch):
    from server.orchestrator import tool_loop
    adapter = _SeqAdapter([HONEST_FIX])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await promise_guard.correct(PROMISING, spawn_name="Deck Master")
    assert out is not None
    assert out["correction"] == HONEST_FIX
    assert out["corrected"] is True
    assert out["pattern"]
    # exactly ONE bounded LLM call, and its prompt states the literal truth
    assert len(adapter.chat_calls) == 1
    sent = adapter.chat_calls[0]["system"] + adapter.chat_calls[0]["user"]
    assert "本回合没有交办任何任务" in sent


@pytest.mark.asyncio
async def test_correct_falls_back_to_template_when_resynthesis_also_promises(monkeypatch):
    from server.orchestrator import tool_loop
    # correction attempt ALSO promises → deterministic template, never a second LLM loop
    adapter = _SeqAdapter(["别急,正在生成中,稍等"])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    out = await promise_guard.correct(PROMISING, spawn_name="Deck Master")
    assert out is not None
    assert out["corrected"] is False
    assert "更正" in out["correction"] and "Deck Master" in out["correction"]
    assert "并不属实" in out["correction"]
    assert len(adapter.chat_calls) == 1  # bounded: never more than one


@pytest.mark.asyncio
async def test_correct_falls_back_to_template_on_llm_error(monkeypatch):
    from server.orchestrator import tool_loop

    def _boom():
        raise RuntimeError("no adapter")

    monkeypatch.setattr(tool_loop, "_get_adapter", _boom)
    out = await promise_guard.correct(PROMISING, spawn_name=None)
    assert out is not None
    assert out["corrected"] is False
    assert "更正" in out["correction"]


@pytest.mark.asyncio
async def test_correct_spawn_only_gate(monkeypatch):
    """PA-1: with check_generic=False, generic-only promise text passes untouched (zero
    LLM calls), while a spawn handoff claim still corrects — and the re-synthesis gate
    keeps the FULL union (a correction must not contain ANY promise language)."""
    from server.orchestrator import tool_loop
    adapter = _SeqAdapter([HONEST_FIX])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    # generic-only text + generic tier gated off → not a hit, no correction attempt
    assert await promise_guard.correct(
        "它正在生成中,稍等", spawn_name="Deck Master", check_generic=False) is None
    assert adapter.chat_calls == []
    # spawn handoff claim → still corrected
    out = await promise_guard.correct(
        "现在让 Deck Master 直接出PPT", spawn_name="Deck Master", check_generic=False)
    assert out is not None and out["correction"] == HONEST_FIX and out["corrected"] is True
    # re-synthesis validation stays full-union: a GENERIC-promising correction is rejected
    adapter2 = _SeqAdapter(["别急,正在生成中,稍等"])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter2)
    out2 = await promise_guard.correct(
        "现在让 Deck Master 直接出PPT", spawn_name="Deck Master", check_generic=False)
    assert out2 is not None and out2["corrected"] is False


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
async def test_regression_doer_first_divert_promise_is_intercepted(maker, monkeypatch):
    """THE incident, replayed: route→spawn 6, user did NOT name the spawn → doer-first
    diverts to self-answer → answer promises a handoff → interceptor appends an honest
    correction (persisted), logs promise_intercept, and still dispatches NOTHING."""
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(action="route", spawn_id=6, task_brief="做 OKX 新手指南 PPT")

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    adapter = _SeqAdapter([PROMISING_LONG, HONEST_FIX])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    # background growth tasks would fire real LLM calls — not under test here
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)

    dispatched = []

    async def _no_dispatch(*a, **k):
        dispatched.append(a)

    monkeypatch.setattr(arslan, "_dispatch_spawn", _no_dispatch)

    events = []
    await arslan.handle_user_message("main", "帮我做一份 OKX 新手指南的 PPT", events.append)

    # 1. never dispatched (structurally true for the divert branch — pinned here)
    assert dispatched == []
    async with db_session.AsyncSessionLocal() as s:
        runs = (await s.execute(select(Run))).scalars().all()
        evs = (await s.execute(select(ConversationEvent))).scalars().all()
        msgs = (await s.execute(
            select(ArslanMessage).order_by(ArslanMessage.id))).scalars().all()
    assert runs == []

    # 2. the correction was emitted live AND persisted (history stays honest)
    streamed = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
    assert HONEST_FIX in streamed
    arslan_msgs = [m for m in msgs if m.role == "arslan"]
    assert arslan_msgs and HONEST_FIX in arslan_msgs[-1].content
    assert PROMISING_LONG in arslan_msgs[-1].content  # streamed text is kept, correction appended

    # 3. audit event (acceptance #1): promise_intercept row with tier/pattern/corrected
    hits = [e for e in evs if e.kind == "promise_intercept"]
    assert len(hits) == 1
    assert hits[0].ref["tier"] == "doer_first"
    assert hits[0].ref["corrected"] is True
    assert hits[0].ref["pattern"]
    assert "空头支票拦截" in hits[0].summary

    # 4. the re-synthesis prompt carried the literal truth statement
    resynth = adapter.chat_calls[-1]
    assert "本回合没有交办任何任务" in (resynth["system"] + resynth["user"])

    # A3: the answer's system prompt carries the iron rule
    assert "没有后台执行" in adapter.chat_calls[0]["system"]


@pytest.mark.asyncio
async def test_tier2_generic_answer_promise_is_intercepted(maker, monkeypatch):
    """Plain answer turn (no spawn inferred): generic PROMISE_RE still triggers, audit
    event says tier=answer, and the correction prompt has no spawn name requirement."""
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)
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
async def test_negative_tool_using_answer_never_triggers(maker, monkeypatch):
    """Acceptance #1 false-positive guard — GENERIC tier only (PA-1 narrowed this): on a
    plain answer turn (no spawn inferred, so the spawn tier is inactive) that actually
    CALLED a tool, generic promising language ('正在…' narrating real work) must NOT
    trigger the interceptor. Spawn-delegation claims are NOT exempted by tool use — see
    the PA-1 corpus tests below."""
    from server.orchestrator import arslan, router, tool_loop
    from server.registry import executors
    from arslan.models import LLMResponse

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

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
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)
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
# PA-1 验收③ — the five REAL corpus sentences (thread-1783523936187, verbatim).
# Every one of these was Arslan's final text on a turn that ALSO called web_search,
# with zero dispatch — the old global `not tool_trace` exemption skipped the guard
# 5/5 times. Spawn-specific promises must intercept regardless of tool use; only a
# real delegation (dispatch / propose_invite → turn_delegated=True) exempts.
# ---------------------------------------------------------------------------


PA1_CORPUS = [
    # (msg id, routed spawn id, spawn name, Arslan's final text — VERBATIM from the incident)
    ("msg480", 7, "Research Analyst",
     "先让 **Research Analyst** 快速收集最新的半导体行业数据"),
    ("msg482", 6, "Deck Master",
     "好了,信息已经收集够了。我现在让 **Deck Master** 直接出PPT,按OKX那种暗色磨砂玻璃+金色点缀的风格"),
    ("msg484", 6, "Deck Master",
     "好的,资料已经齐了。现在让 **Deck Master** 直接生成整页可编辑的HTML"),
    ("msg486", 6, "Deck Master",
     "好,信息都收集齐了。现在让 **Deck Master** 直接出整页长滚动的HTML,暗色磨砂玻璃+金色点缀风格"),
    ("msg488", 6, "Deck Master",
     "好,资料已经全部齐了。现在让 **Deck Master** 直接出整页长滚动HTML。**Deck Master**,请按以下要求执行"),
]


def _tool_then_claim_adapter(claim: str):
    """Adapter replaying the incident turn shape: call 1 = a web_search tool call
    (tool_trace becomes NON-empty), call 2 = the delegation claim as the final text,
    call 3 = the guard's honest re-synthesis."""
    from arslan.models import LLMResponse

    class _ToolThenClaim:
        def __init__(self):
            self.chat_calls = []
            self._n = 0

        async def chat(self, system, user, history=None, tools=None, temperature=0.7):
            self.chat_calls.append({"system": system, "user": user})
            self._n += 1
            if self._n == 1:
                return LLMResponse(content="", tool_calls=[{
                    "id": "c1", "type": "function",
                    "function": {"name": "web_search", "arguments": {"query": "半导体行业"}},
                }], usage={})
            if self._n == 2:
                return LLMResponse(content=claim, tool_calls=[], usage={})
            return LLMResponse(content=HONEST_FIX, tool_calls=[], usage={})

    return _ToolThenClaim()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "msg_id,spawn_id,spawn_name,claim", PA1_CORPUS, ids=[c[0] for c in PA1_CORPUS])
async def test_pa1_corpus_spawn_promise_intercepted_despite_tool_use(
        maker, monkeypatch, msg_id, spawn_id, spawn_name, claim):
    """PA-1 验收③: the incident turn replayed — doer-first divert, web_search WAS called
    (tool_trace non-empty), final text claims the handoff. The guard must STILL intercept:
    correction appended (streamed + persisted) and promise_intercept event logged."""
    from server.orchestrator import arslan, router, tool_loop
    from server.registry import executors

    async def _fake_route(conv, msg):
        return router.RouterResult(action="route", spawn_id=spawn_id,
                                   task_brief="半导体行业 PPT")

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan, "_fire_dual_track", lambda *a, **k: None)
    adapter = _tool_then_claim_adapter(claim)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    class _Stub:
        async def execute(self, args):
            return {"ok": True, "results": [{"title": "t", "url": "u"}]}

    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Stub())

    dispatched = []

    async def _no_dispatch(*a, **k):
        dispatched.append(a)

    monkeypatch.setattr(arslan, "_dispatch_spawn", _no_dispatch)

    events = []
    # user never names the spawn → doer-first divert (the incident shape)
    await arslan.handle_user_message("main", "帮我做一份半导体行业的PPT", events.append)

    # the turn really used a tool AND really never delegated
    assert dispatched == []
    assert len(adapter.chat_calls) == 3  # tool step + claim + correction re-synthesis
    # …yet the spawn-handoff claim IS intercepted: correction streamed + persisted
    streamed = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
    assert HONEST_FIX in streamed
    async with db_session.AsyncSessionLocal() as s:
        evs = (await s.execute(select(ConversationEvent))).scalars().all()
        msgs = (await s.execute(
            select(ArslanMessage).order_by(ArslanMessage.id))).scalars().all()
    arslan_msgs = [m for m in msgs if m.role == "arslan"]
    assert arslan_msgs and HONEST_FIX in arslan_msgs[-1].content
    assert claim in arslan_msgs[-1].content  # claim kept, correction appended
    hits = [e for e in evs if e.kind == "promise_intercept"]
    assert len(hits) == 1
    assert hits[0].ref["tier"] == "doer_first"
    assert hits[0].ref["pattern"] and spawn_name in hits[0].ref["pattern"]


@pytest.mark.asyncio
async def test_pa1_spawn_promise_exempt_when_turn_actually_delegated(maker, monkeypatch):
    """The honest exemption: a turn that REALLY delegated (turn_delegated=True — a
    dispatch or propose_invite happened) may name the handoff; no interception."""
    from server.orchestrator import arslan, tool_loop

    claim = PA1_CORPUS[1][3]  # 「我现在让 **Deck Master** 直接出PPT…」
    # long enough to dodge tool_loop's deferral-stub salvage; still spawn-promising
    claim_long = claim + "整份会覆盖行业规模、供应链格局、先进制程竞争、AI 芯片需求与政策风险五个章节," \
                         "每章配数据图表位与要点注释,整体控制在十五页以内。"
    adapter = _SeqAdapter([claim_long])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events = []
    await arslan._handle_answer("main", "帮我做一份半导体行业的PPT", events.append,
                                intercept_spawn_name="Deck Master", turn_delegated=True)

    assert len(adapter.chat_calls) == 1  # no correction re-synthesis call
    streamed = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
    assert "更正" not in streamed
    async with db_session.AsyncSessionLocal() as s:
        evs = (await s.execute(select(ConversationEvent))).scalars().all()
    assert [e for e in evs if e.kind == "promise_intercept"] == []


# ---------------------------------------------------------------------------
# A3 iron rule (constant-level pin, in addition to the flow assert above)
# ---------------------------------------------------------------------------


def test_a3_iron_rule_constant():
    from server.orchestrator import arslan
    assert "没有后台执行" in arslan._NO_BACKGROUND_EXEC
    assert "如实说明" in arslan._NO_BACKGROUND_EXEC


# ---------------------------------------------------------------------------
# PA-4: no-repaste iron rule (constant pin + built-prompt flow assert, A3 pattern)
# ---------------------------------------------------------------------------


def test_pa4_no_repaste_rule_constant():
    from server.orchestrator import arslan
    assert "不要整段重贴" in arslan._NO_REPASTE
    assert "沿用上面那份大纲" in arslan._NO_REPASTE


@pytest.mark.asyncio
async def test_pa4_answer_system_prompt_carries_no_repaste_rule(maker, monkeypatch):
    """PA-4: the converse system prompt must carry the no-repaste rule — the live
    incident re-pasted the SAME outline verbatim 3x across consecutive answer turns."""
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    honest_long = "这是一段普通的、不含任何承诺语言、也不重贴旧内容的长回答,用来验证系统提示词。" * 5
    adapter = _SeqAdapter([honest_long])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    await arslan.handle_user_message("main", "随便聊聊", lambda e: None)

    assert "不要整段重贴" in adapter.chat_calls[0]["system"]
