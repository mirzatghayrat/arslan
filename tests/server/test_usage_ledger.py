"""S3-M3: usage_ledger — best-effort per-scope token accounting for LLM calls that
never produce a Run row (router / judge / memory compaction / titler / direct spawn
chat) plus Arslan's answer path.

Contract under test:
  - migration _0029 creates the table idempotently (repo re-applies every boot);
  - usage_ledger.scope(...) opens usage_sink.collecting() and, on exit, writes ONE
    ledger row PER (model, provider) bucket (estimate paths stay honest);
  - a ledger/DB failure NEVER breaks the wrapped business call;
  - NESTING SAFETY: the judge task is created (via schedule_scoring) INSIDE
    _dispatch_spawn's active collecting scope and inherits its contextvars — the
    judge's own scope() must open a FRESH bucket (stealing nothing, seeing nothing),
    so the dispatch Run's usage is neither diminished nor is the judge row inflated.
"""
import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arslan.llm import usage_sink
from arslan.models import LLMResponse
from server.db import session as db_session
from server.db.models import Base, Run, Spawn, UsageLedger
from server.services import run_recorder, usage_ledger
from tests.server.conftest import build_ws_client


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda run_id: None)
    yield Session
    await engine.dispose()


async def _rows(Session) -> list[UsageLedger]:
    async with Session() as db:
        return list((await db.execute(
            select(UsageLedger).order_by(UsageLedger.id))).scalars().all())


class _ReportingAdapter:
    """Stub LLMAdapter whose chat() reports usage into the ACTIVE usage_sink —
    mirrors the real adapter choke point (report_detail + report)."""

    def __init__(self, *, content="ok", tokens_in=100, tokens_out=40,
                 model="claude-x", provider="anthropic"):
        self.content = content
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.model = model
        self.provider = provider

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        usage_sink.report_detail(tokens_in=self.tokens_in, tokens_out=self.tokens_out,
                                 model=self.model, provider=self.provider)
        usage_sink.report((self.tokens_in or 0) + (self.tokens_out or 0))
        return LLMResponse(content=self.content, usage={})


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

async def test_0029_creates_usage_ledger_idempotent():
    from server.db.migrations.versions._0029_usage_ledger import upgrade_sync
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            # PRE-EXISTING-DB path: run the migration WITHOUT create_all first.
            await conn.run_sync(upgrade_sync)
            await conn.run_sync(upgrade_sync)  # idempotent
            tables = {r[0] for r in (await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"))}
            assert "usage_ledger" in tables
            cols = {r[1] for r in (await conn.exec_driver_sql(
                "PRAGMA table_info(usage_ledger)"))}
            assert {"id", "ts", "scope", "conversation_id", "run_id", "model",
                    "provider", "tokens_in", "tokens_out", "tokens_total",
                    "tokens_estimated"} <= cols
            # boot order parity: create_all AFTER the migration must also be a no-op
            await conn.run_sync(Base.metadata.create_all)
            idx = {r[0] for r in (await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='usage_ledger'"))}
            assert "ix_usage_ledger_ts" in idx
            assert "ix_usage_ledger_conversation_id" in idx
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# scope() core semantics
# ---------------------------------------------------------------------------

async def test_scope_writes_one_row_per_bucket(memdb):
    async with usage_ledger.scope("router", "c1"):
        usage_sink.report_detail(tokens_in=120, tokens_out=80,
                                 model="claude-x", provider="anthropic")
        usage_sink.report(200)
        usage_sink.report_detail(tokens_in=10, tokens_out=5,
                                 model="gpt-y", provider="openai")
        usage_sink.report(15)
    rows = await _rows(memdb)
    assert len(rows) == 2
    by_model = {r.model: r for r in rows}
    a = by_model["claude-x"]
    assert (a.scope, a.conversation_id) == ("router", "c1")
    assert (a.tokens_in, a.tokens_out, a.tokens_total) == (120, 80, 200)
    assert a.tokens_estimated is False
    b = by_model["gpt-y"]
    assert (b.tokens_in, b.tokens_out, b.tokens_total) == (10, 5, 15)


async def test_scope_single_blind_bucket_gets_estimated_total(memdb):
    """Stream-estimate path: the adapter reports the estimate ONLY via report()
    while detail gets a both-None bucket — the row must carry the estimate."""
    async with usage_ledger.scope("answer", "c2"):
        usage_sink.report(500)
        usage_sink.report_detail(tokens_in=None, tokens_out=None,
                                 model="claude-x", provider="anthropic")
    rows = await _rows(memdb)
    assert len(rows) == 1
    r = rows[0]
    assert (r.model, r.tokens_in, r.tokens_out) == ("claude-x", None, None)
    assert r.tokens_total == 500
    assert r.tokens_estimated is True


async def test_scope_same_bucket_estimate_then_real_row_marked_estimated(memdb):
    """Review I1 alignment: an estimate report followed by a REAL report into the SAME
    (model, provider) bucket leaves the bucket with real-looking fields but a sticky
    estimated flag — the ledger row must carry tokens_estimated=True (the estimated
    call's tokens are unattributable; only the real portion lands in the total)."""
    async with usage_ledger.scope("answer", "c-est"):
        # stream estimate fallback: total via report() only, both-None detail bucket
        usage_sink.report(500)
        usage_sink.report_detail(tokens_in=None, tokens_out=None,
                                 model="claude-x", provider="anthropic")
        # then a real (non-stream) call on the SAME model in the same scope
        usage_sink.report_detail(tokens_in=100, tokens_out=40,
                                 model="claude-x", provider="anthropic")
        usage_sink.report(140)
    rows = await _rows(memdb)
    assert len(rows) == 1
    r = rows[0]
    assert (r.model, r.tokens_in, r.tokens_out) == ("claude-x", 100, 40)
    assert r.tokens_total == 140  # real portion only — the 500 estimate is unattributable
    assert r.tokens_estimated is True


async def test_scope_pure_estimate_without_detail_writes_scope_row(memdb):
    async with usage_ledger.scope("memory", None):
        usage_sink.report(300)
    rows = await _rows(memdb)
    assert len(rows) == 1
    r = rows[0]
    assert (r.scope, r.conversation_id, r.model, r.provider) == ("memory", None, None, None)
    assert (r.tokens_total, r.tokens_estimated) == (300, True)


async def test_scope_without_usage_writes_nothing(memdb):
    async with usage_ledger.scope("titler", "c3"):
        pass
    assert await _rows(memdb) == []


async def test_scope_writes_even_when_wrapped_call_raises(memdb):
    """Tokens burned on a failing call are still tokens burned."""
    with pytest.raises(RuntimeError):
        async with usage_ledger.scope("judge", "c4", run_id=7):
            usage_sink.report_detail(tokens_in=9, tokens_out=1,
                                     model="claude-x", provider="anthropic")
            usage_sink.report(10)
            raise RuntimeError("boom")
    rows = await _rows(memdb)
    assert len(rows) == 1
    assert (rows[0].scope, rows[0].run_id, rows[0].tokens_total) == ("judge", 7, 10)


async def test_ledger_db_failure_never_breaks_wrapped_call(memdb, monkeypatch):
    def _broken_session_factory(*a, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", _broken_session_factory)
    done = False
    async with usage_ledger.scope("router", "c5"):
        usage_sink.report(50)
        done = True
    assert done  # no exception escaped the scope


# ---------------------------------------------------------------------------
# Capture point: answer (_handle_answer)
# ---------------------------------------------------------------------------

async def test_answer_path_writes_answer_row(memdb, monkeypatch):
    from server.orchestrator import arslan, tool_loop

    async def fake_run_native(*, system, user_content, history, emit, on_chunk,
                              resolve_tools, allow_escalation, confirm_command=None,
                              conversation_id=None):
        usage_sink.report_detail(tokens_in=100, tokens_out=40,
                                 model="claude-x", provider="anthropic")
        usage_sink.report(140)
        on_chunk("hi")
        # non-empty tool_trace → the generic promise guard is skipped
        return {"final": "hello there", "tool_trace": [{"tool": "web_search"}]}

    monkeypatch.setattr(tool_loop, "run_native", fake_run_native)
    events: list[dict] = []
    out = await arslan._handle_answer("c-ans", "你好", events.append)
    assert out == "hello there"
    rows = await _rows(memdb)
    assert len(rows) == 1
    r = rows[0]
    assert (r.scope, r.conversation_id) == ("answer", "c-ans")
    assert (r.tokens_in, r.tokens_out, r.tokens_total) == (100, 40, 140)
    assert r.tokens_estimated is False


# ---------------------------------------------------------------------------
# Capture point: router (route())
# ---------------------------------------------------------------------------

async def test_router_decision_writes_router_row(memdb, monkeypatch):
    from server.orchestrator import router
    adapter = _ReportingAdapter(content='{"action": "answer", "reason": "smalltalk"}',
                                tokens_in=30, tokens_out=12)
    monkeypatch.setattr(router, "_get_adapter", lambda: adapter)
    result = await router.route("c-rt", "hello")
    assert result.action == "answer"
    rows = await _rows(memdb)
    assert len(rows) == 1
    r = rows[0]
    assert (r.scope, r.conversation_id) == ("router", "c-rt")
    assert (r.tokens_in, r.tokens_out, r.tokens_total) == (30, 12, 42)


# ---------------------------------------------------------------------------
# Capture point: judge (run_eval_service.score())
# ---------------------------------------------------------------------------

_JUDGE_JSON = ('{"dimensions": {"task_completion": {"status": "yes", "score": 8, '
               '"comment": "ok"}}, "overall": {"score": 8.0, "badge": "good"}}')


async def test_judge_score_writes_judge_row(memdb, monkeypatch):
    from server.services import run_eval_service

    async with memdb() as db:
        run = Run(conversation_id="c-j", user_message="do it", spawn_name="Mermer")
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    async def fake_build_adapter(role):
        assert role == "judge"
        return _ReportingAdapter(content=_JUDGE_JSON, tokens_in=70, tokens_out=25)

    monkeypatch.setattr(run_eval_service, "build_adapter", fake_build_adapter)
    await run_eval_service.score(run_id)

    async with memdb() as db:
        run = await db.get(Run, run_id)
    assert run.status == "scored"
    rows = await _rows(memdb)
    assert len(rows) == 1
    r = rows[0]
    assert (r.scope, r.conversation_id, r.run_id) == ("judge", "c-j", run_id)
    assert (r.tokens_in, r.tokens_out, r.tokens_total) == (70, 25, 95)


async def test_judge_scope_does_not_diminish_dispatch_run_usage(memdb, monkeypatch):
    """NESTING DANGER regression: schedule_scoring creates the judge task from INSIDE
    _dispatch_spawn's usage_sink.collecting() region, so the task INHERITS the active
    bucket via its context copy. The judge's usage_ledger.scope() must open a FRESH
    bucket: the dispatch Run keeps its full usage (not diminished), and the judge
    ledger row carries ONLY the judge's own tokens (not run + judge)."""
    from server.orchestrator import arslan, dispatcher
    from server.services import roster_service, run_eval_service
    from server.orchestrator import memory as _memory

    async with memdb() as db:
        s = Spawn(name="Mermer", domain_category="research", system_prompt="You research.")
        db.add(s)
        await db.commit()
        await db.refresh(s)
        spawn_id = s.id

    judge_tasks: list[asyncio.Task] = []
    # Mirror run_recorder._default_schedule: create_task INSIDE the caller's context
    # (i.e. inside the dispatch collecting scope) — the inheritance under test.
    monkeypatch.setattr(
        run_recorder, "schedule_scoring",
        lambda rid: judge_tasks.append(asyncio.create_task(run_eval_service.score(rid))))

    async def fake_build_adapter(role):
        return _ReportingAdapter(content=_JUDGE_JSON, tokens_in=7, tokens_out=3)
    monkeypatch.setattr(run_eval_service, "build_adapter", fake_build_adapter)

    async def fake_dispatch(conversation_id, *, spawn_id, task_brief, on_chunk=None,
                            on_event=None, prior_output=None, instruction=None,
                            allow_escalation=True, mode="execute", attached_context=None,
                            run_id=None):
        usage_sink.report_detail(tokens_in=120, tokens_out=80,
                                 model="claude-x", provider="anthropic")
        usage_sink.report(200)
        sid = await _memory.add_message(conversation_id, "spawn_summary", "delivered",
                                        display_content="delivered", spawn_id=spawn_id)
        return {"full_output": "delivered", "spawn_name": "Mermer",
                "summary_message_id": sid, "assistant_message_id": 1, "escalation": None}
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)

    await roster_service.join("c-n", spawn_id, via="invited")
    events: list[dict] = []
    await arslan.dispatch_routed("c-n", spawn_id, "do it", False, events.append)
    assert judge_tasks, "judge task was never scheduled"
    await asyncio.gather(*judge_tasks)

    async with memdb() as db:
        run = (await db.execute(select(Run))).scalars().one()
    # Dispatch Run keeps its FULL usage — nothing stolen by the judge scope.
    assert run.task_tokens == 200
    assert (run.tokens_in, run.tokens_out) == (120, 80)
    assert run.status == "scored"
    # S3-M3 Task 5: the run's stream_end frame carries the SAME usage finalize read
    # (built inside the collecting scope). "claude-x" has no price → usd present, None.
    ends = [e for e in events if e["type"] == "stream_end"]
    assert len(ends) == 1
    assert ends[0]["usage"] == {"tokens_in": 120, "tokens_out": 80, "tokens_total": 200,
                                "estimated": False, "usd": None}
    judge_rows = [r for r in await _rows(memdb) if r.scope == "judge"]
    assert len(judge_rows) == 1
    # Judge row = judge's own tokens ONLY (a leaked inherited bucket would show 127/83).
    assert (judge_rows[0].tokens_in, judge_rows[0].tokens_out) == (7, 3)
    assert judge_rows[0].tokens_total == 10
    assert judge_rows[0].run_id == run.id


# ---------------------------------------------------------------------------
# Capture point: memory compaction (maybe_compact)
# ---------------------------------------------------------------------------

async def test_memory_compaction_writes_memory_row(memdb, monkeypatch):
    from server.orchestrator import memory

    await memory.add_message("c-m", "user", "这是第一条很长的消息内容需要被压缩掉")
    await memory.add_message("c-m", "arslan", "这是第二条回复内容同样很长")
    monkeypatch.setattr(memory, "_token_budget", lambda: 0)
    monkeypatch.setattr(memory, "_summary_token_cap", lambda: 10000)
    adapter = _ReportingAdapter(content="compact summary", tokens_in=55, tokens_out=20)
    monkeypatch.setattr(memory, "_get_adapter", lambda: adapter)

    await memory.maybe_compact("c-m")
    rows = await _rows(memdb)
    assert len(rows) == 1
    r = rows[0]
    assert (r.scope, r.conversation_id) == ("memory", "c-m")
    assert (r.tokens_in, r.tokens_out, r.tokens_total) == (55, 20, 75)


# ---------------------------------------------------------------------------
# Capture point: titler
# ---------------------------------------------------------------------------

async def test_titler_writes_titler_row(memdb, monkeypatch):
    import server.services.llm_factory as llm_factory
    from server.services import titler

    async def fake_build_adapter(role):
        return _ReportingAdapter(content="A Short Title", tokens_in=20, tokens_out=6)
    monkeypatch.setattr(llm_factory, "build_adapter", fake_build_adapter)

    title = await titler.generate_title("帮我研究一下电动车市场", conversation_id="c-t")
    assert title == "A Short Title"
    rows = await _rows(memdb)
    assert len(rows) == 1
    r = rows[0]
    assert (r.scope, r.conversation_id) == ("titler", "c-t")
    assert (r.tokens_in, r.tokens_out, r.tokens_total) == (20, 6, 26)


# ---------------------------------------------------------------------------
# Capture point: direct spawn chat (ws/chat.py)
# ---------------------------------------------------------------------------

def test_direct_chat_writes_direct_chat_row(tmp_path, monkeypatch, portal):
    import server.ws.chat as chat_module
    from server.orchestrator import dispatcher, spawn_loop

    async def _seed(maker):
        async with maker() as s:
            s.add(Spawn(name="beauty-guru", domain_category="content",
                        system_prompt="You are a beauty expert."))
            await s.commit()

    async def _fake_build_spawn_system(spawn, *, retrieval_query, current_turn,
                                       attached_context=None, system_prompt_override=None):
        return spawn.system_prompt or "helper", []
    monkeypatch.setattr(dispatcher, "build_spawn_system", _fake_build_spawn_system)
    monkeypatch.setattr(chat_module, "build_spawn_system", _fake_build_spawn_system,
                        raising=False)

    async def _fake_run(*, spawn_id, system, user_content, history, current_turn,
                        emit, on_chunk, allow_escalation):
        usage_sink.report_detail(tokens_in=88, tokens_out=33,
                                 model="claude-x", provider="anthropic")
        usage_sink.report(121)
        on_chunk("reply")
        return {"final": "reply", "escalation": None, "tool_trace": []}
    monkeypatch.setattr(spawn_loop, "run", _fake_run)

    client = build_ws_client(portal, tmp_path, monkeypatch, _seed, db_name="chat.db")
    with client.websocket_connect("/ws/chat/1") as ws:
        assert ws.receive_json()["type"] == "history"
        ws.send_json({"type": "user_message", "content": "hi"})
        frame = ws.receive_json()
        while frame["type"] != "stream_end":
            frame = ws.receive_json()

    async def _read():
        async with client.db_maker() as db:
            return list((await db.execute(select(UsageLedger))).scalars().all())
    rows = client.portal.call(_read)
    assert len(rows) == 1
    r = rows[0]
    assert (r.scope, r.conversation_id) == ("direct_chat", "spawn-1")
    assert (r.tokens_in, r.tokens_out, r.tokens_total) == (88, 33, 121)
