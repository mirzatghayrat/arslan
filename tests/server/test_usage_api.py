"""S3-M3 Task 5: usage on terminal frames + aggregation endpoints.

Contract under test:
  - `GET /conversations/{id}/usage` aggregates live runs (scope="spawn") + usage_ledger
    rows for ONE conversation: honest USD (only known-price, non-estimated items are
    summed; `usd_partial` flags that some tokens carry no USD), `estimated_any`
    propagation, per-scope breakdown.
  - `GET /usage/summary?range=24h|7d|30d` groups runs+ledger by provider x model x scope
    with range filtering, a daily token series, and the honest `not_covered` footnote
    (call sites that don't feed the ledger yet — mirrors spec §S3-D).
  - The answer path's stream_end frame carries the same usage payload the dispatch
    stream_end got: {tokens_in, tokens_out, tokens_total, estimated, usd|None}.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from arslan.llm import usage_sink
from server.db.models import Base, Run, UsageLedger

AUTH = {"Authorization": "Bearer test-token"}

# Price anchors (arslan/llm/prices.py): claude-sonnet-5 = (3, 15) USD/MTok,
# claude-haiku-4-5 = (1, 5). "mystery-*" matches no prefix → unpriceable.
SONNET = "claude-sonnet-5-20260101"
HAIKU = "claude-haiku-4-5-20260101"


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "test-token")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "usage.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'usage.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await engine.dispose()


def _run(cid: str, *, model=None, provider=None, tin=None, tout=None, estimated=False,
         task_tokens=0, kind="live", created_at=None) -> Run:
    return Run(conversation_id=cid, user_message="m", status="recorded", kind=kind,
               model=model, provider=provider, tokens_in=tin, tokens_out=tout,
               tokens_estimated=estimated, task_tokens=task_tokens,
               created_at=created_at or datetime.utcnow())


def _ledger(cid, *, scope, model=None, provider=None, tin=None, tout=None,
            total=0, estimated=False, ts=None) -> UsageLedger:
    return UsageLedger(conversation_id=cid, scope=scope, model=model, provider=provider,
                       tokens_in=tin, tokens_out=tout, tokens_total=total,
                       tokens_estimated=estimated, ts=ts or datetime.utcnow())


# ---------------------------------------------------------------------------
# GET /conversations/{id}/usage
# ---------------------------------------------------------------------------

async def test_conversation_usage_requires_auth(client):
    r = await client.get("/api/v1/conversations/c/usage")
    assert r.status_code in (401, 403)


async def test_conversation_usage_aggregates_runs_and_ledger(client):
    cid = "conv-u"
    async with db_session.AsyncSessionLocal() as db:
        # priced real run: 0.1 MTok in * $3 + 0.01 MTok out * $15 = $0.45
        db.add(_run(cid, model=SONNET, provider="anthropic",
                    tin=100_000, tout=10_000, task_tokens=110_000))
        # unknown-price run → tokens counted, unpriceable
        db.add(_run(cid, model="mystery-9000", provider="openai",
                    tin=60, tout=40, task_tokens=100))
        # estimated run → tokens counted, never priced
        db.add(_run(cid, model=SONNET, provider="anthropic",
                    estimated=True, task_tokens=500))
        # replay run: NEVER counted
        db.add(_run(cid, model=SONNET, provider="anthropic",
                    tin=1, tout=1, task_tokens=999_999, kind="replay"))
        # other conversation: excluded
        db.add(_run("other", model=SONNET, provider="anthropic",
                    tin=10, tout=10, task_tokens=20))
        # ledger: priced router row = 0.001*1 + 0.0001*5 = $0.0015
        db.add(_ledger(cid, scope="router", model=HAIKU, provider="anthropic",
                       tin=1000, tout=100, total=1100))
        # ledger: estimated judge row (no model attribution)
        db.add(_ledger(cid, scope="judge", total=300, estimated=True))
        db.add(_ledger("other", scope="router", model=HAIKU, provider="anthropic",
                       tin=5, tout=5, total=10))
        await db.commit()

    r = await client.get(f"/api/v1/conversations/{cid}/usage", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["tokens_total"] == 110_000 + 100 + 500 + 1100 + 300
    assert body["usd_total"] == pytest.approx(0.45 + 0.0015)
    assert body["usd_partial"] is True   # mystery run + estimated rows carry no USD
    assert body["estimated_any"] is True
    scopes = {s["scope"]: s for s in body["by_scope"]}
    assert set(scopes) == {"spawn", "router", "judge"}
    assert scopes["spawn"]["tokens_total"] == 110_600
    assert scopes["spawn"]["usd"] == pytest.approx(0.45)
    assert scopes["router"]["tokens_total"] == 1100
    assert scopes["router"]["usd"] == pytest.approx(0.0015)
    assert scopes["judge"]["tokens_total"] == 300
    assert scopes["judge"]["usd"] is None


async def test_conversation_usage_nothing_priceable_is_null_not_zero(client):
    cid = "conv-unpriced"
    async with db_session.AsyncSessionLocal() as db:
        db.add(_run(cid, model="mystery-9000", provider="openai",
                    tin=60, tout=40, task_tokens=100))
        await db.commit()
    r = await client.get(f"/api/v1/conversations/{cid}/usage", headers=AUTH)
    body = r.json()
    assert body["tokens_total"] == 100
    assert body["usd_total"] is None     # nothing priceable → null, NOT 0.0
    assert body["usd_partial"] is True
    assert body["estimated_any"] is False  # unknown price ≠ estimated tokens


async def test_conversation_usage_clean_priced_conversation(client):
    cid = "conv-clean"
    async with db_session.AsyncSessionLocal() as db:
        db.add(_run(cid, model=SONNET, provider="anthropic",
                    tin=1000, tout=500, task_tokens=1500))
        await db.commit()
    r = await client.get(f"/api/v1/conversations/{cid}/usage", headers=AUTH)
    body = r.json()
    assert body["usd_total"] == pytest.approx(1000 / 1e6 * 3 + 500 / 1e6 * 15)
    assert body["usd_partial"] is False
    assert body["estimated_any"] is False


async def test_conversation_usage_empty_conversation(client):
    r = await client.get("/api/v1/conversations/conv-none/usage", headers=AUTH)
    body = r.json()
    assert body == {"tokens_total": 0, "usd_total": None, "usd_partial": False,
                    "estimated_any": False, "by_scope": []}


# ---------------------------------------------------------------------------
# GET /usage/summary
# ---------------------------------------------------------------------------

async def _seed_summary(now: datetime) -> None:
    async with db_session.AsyncSessionLocal() as db:
        db.add(_run("c1", model=SONNET, provider="anthropic", tin=1000, tout=100,
                    task_tokens=1100, created_at=now - timedelta(hours=2)))
        db.add(_run("c2", model=SONNET, provider="anthropic", tin=2000, tout=200,
                    task_tokens=2200, created_at=now - timedelta(days=3)))
        db.add(_run("c3", model="mystery-9000", provider="openai", tin=30, tout=20,
                    task_tokens=50, created_at=now - timedelta(days=20)))
        db.add(_run("c4", model=SONNET, provider="anthropic", tin=9, tout=9,
                    task_tokens=18, kind="replay", created_at=now - timedelta(hours=1)))
        db.add(_ledger("c1", scope="router", model=HAIKU, provider="anthropic",
                       tin=500, tout=50, total=550, ts=now - timedelta(hours=1)))
        db.add(_ledger("c2", scope="judge", model=HAIKU, provider="anthropic",
                       total=300, estimated=True, ts=now - timedelta(days=3)))
        await db.commit()


async def test_usage_summary_requires_auth(client):
    r = await client.get("/api/v1/usage/summary")
    assert r.status_code in (401, 403)


async def test_usage_summary_rejects_bad_range(client):
    r = await client.get("/api/v1/usage/summary", params={"range": "1y"}, headers=AUTH)
    assert r.status_code == 422


async def test_usage_summary_24h_window(client):
    await _seed_summary(datetime.utcnow())
    r = await client.get("/api/v1/usage/summary", params={"range": "24h"}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    rows = {(x["provider"], x["model"], x["scope"]): x for x in body["rows"]}
    assert set(rows) == {("anthropic", SONNET, "spawn"), ("anthropic", HAIKU, "router")}
    spawn = rows[("anthropic", SONNET, "spawn")]
    assert spawn["tokens_total"] == 1100
    assert spawn["usd"] == pytest.approx(1000 / 1e6 * 3 + 100 / 1e6 * 15)
    assert spawn["estimated_any"] is False
    router = rows[("anthropic", HAIKU, "router")]
    assert router["tokens_total"] == 550
    assert router["usd"] == pytest.approx(500 / 1e6 * 1 + 50 / 1e6 * 5)
    # daily series covers exactly the in-window tokens, dates ascending
    assert sum(p["tokens_total"] for p in body["daily"]) == 1100 + 550
    dates = [p["date"] for p in body["daily"]]
    assert dates == sorted(dates)


async def test_usage_summary_7d_and_30d_windows(client):
    await _seed_summary(datetime.utcnow())
    r7 = (await client.get("/api/v1/usage/summary", params={"range": "7d"},
                           headers=AUTH)).json()
    rows7 = {(x["provider"], x["model"], x["scope"]): x for x in r7["rows"]}
    assert set(rows7) == {("anthropic", SONNET, "spawn"),
                          ("anthropic", HAIKU, "router"),
                          ("anthropic", HAIKU, "judge")}
    spawn7 = rows7[("anthropic", SONNET, "spawn")]
    assert spawn7["tokens_total"] == 3300     # both sonnet runs
    assert spawn7["usd"] == pytest.approx(3000 / 1e6 * 3 + 300 / 1e6 * 15)
    judge7 = rows7[("anthropic", HAIKU, "judge")]
    assert judge7["tokens_total"] == 300
    assert judge7["usd"] is None              # estimated → never priced
    assert judge7["estimated_any"] is True
    assert sum(p["tokens_total"] for p in r7["daily"]) == 3300 + 550 + 300

    r30 = (await client.get("/api/v1/usage/summary", params={"range": "30d"},
                            headers=AUTH)).json()
    rows30 = {(x["provider"], x["model"], x["scope"]): x for x in r30["rows"]}
    assert len(rows30) == 4                   # + the 20-day-old mystery run
    mystery = rows30[("openai", "mystery-9000", "spawn")]
    assert mystery["tokens_total"] == 50
    assert mystery["usd"] is None             # unknown price
    assert mystery["estimated_any"] is False


async def test_usage_summary_not_covered_footnote(client):
    """Honesty footnote: the hardcoded list of LLM call sites that do NOT feed the
    ledger yet — must mirror spec §S3-D's 未计入清单 annotation."""
    r = await client.get("/api/v1/usage/summary", headers=AUTH)
    body = r.json()
    nc = body["not_covered"]
    assert "_route_announcement" in nc
    assert "distill_service" in nc
    assert "compare_judge" in nc
    assert "sandbox_service" in nc
    assert len(nc) == 19


# ---------------------------------------------------------------------------
# Answer-path terminal frame carries usage
# ---------------------------------------------------------------------------

@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session
    await engine.dispose()


async def test_answer_stream_end_carries_usage(memdb, monkeypatch):
    """_handle_answer_body emits the turn's stream_end while _handle_answer's
    ledger scope is still open — the frame must carry the collected usage,
    priced when the model is known and the tokens are real."""
    from server.orchestrator import arslan, tool_loop

    async def fake_run_native(*, system, user_content, history, emit, on_chunk,
                              resolve_tools, allow_escalation, confirm_command=None,
                              conversation_id=None):
        usage_sink.report_detail(tokens_in=1000, tokens_out=500,
                                 model=SONNET, provider="anthropic")
        usage_sink.report(1500)
        on_chunk("hi")
        return {"final": "hello there", "tool_trace": [{"tool": "web_search"}]}

    monkeypatch.setattr(tool_loop, "run_native", fake_run_native)
    events: list[dict] = []
    out = await arslan._handle_answer("c-frame", "你好", events.append)
    assert out == "hello there"
    ends = [e for e in events if e["type"] == "stream_end"]
    assert len(ends) == 1
    usage = ends[0]["usage"]
    assert usage["tokens_in"] == 1000
    assert usage["tokens_out"] == 500
    assert usage["tokens_total"] == 1500
    assert usage["estimated"] is False
    assert usage["usd"] == pytest.approx(1000 / 1e6 * 3 + 500 / 1e6 * 15)


# ---------------------------------------------------------------------------
# Review I2: _usage_frame prices per (model, provider) bucket, never the
# primary bucket's rate applied to summed tokens.
# ---------------------------------------------------------------------------

def _frame_from(report_calls: list[dict]) -> dict:
    from server.orchestrator import arslan

    with usage_sink.collecting():
        for call in report_calls:
            usage_sink.report_detail(**call)
            usage_sink.report((call["tokens_in"] or 0) + (call["tokens_out"] or 0))
        return arslan._usage_frame(usage_sink.detail())


async def test_usage_frame_multi_model_usd_is_sum_of_per_bucket_prices():
    frame = _frame_from([
        {"tokens_in": 1000, "tokens_out": 500, "model": SONNET, "provider": "anthropic"},
        {"tokens_in": 2000, "tokens_out": 100, "model": HAIKU, "provider": "anthropic"},
    ])
    per_bucket = (1000 / 1e6 * 3 + 500 / 1e6 * 15) + (2000 / 1e6 * 1 + 100 / 1e6 * 5)
    assert frame["usd"] == pytest.approx(per_bucket)
    # NOT the old bug: primary bucket's (haiku) rate applied to the summed tokens.
    primary_rate_on_totals = 3000 / 1e6 * 1 + 600 / 1e6 * 5
    assert frame["usd"] != pytest.approx(primary_rate_on_totals)
    assert (frame["tokens_in"], frame["tokens_out"]) == (3000, 600)  # honest sums
    assert frame["estimated"] is False


async def test_usage_frame_any_unpriceable_bucket_blanks_usd():
    frame = _frame_from([
        {"tokens_in": 1000, "tokens_out": 500, "model": SONNET, "provider": "anthropic"},
        {"tokens_in": 10, "tokens_out": 10, "model": "mystery-9000", "provider": "openai"},
    ])
    assert frame["usd"] is None          # unknown ≠ free — never a partial sum
    assert (frame["tokens_in"], frame["tokens_out"]) == (1010, 510)
    assert frame["estimated"] is False


async def test_usage_frame_bucket_provider_reaches_pricing():
    # deepseek-r1 is $0 ONLY as a local ollama call (review I1) — the frame must
    # thread each bucket's provider into prices.usd.
    ollama = _frame_from([
        {"tokens_in": 100, "tokens_out": 50, "model": "deepseek-r1:14b",
         "provider": "ollama"},
    ])
    assert ollama["usd"] == 0.0
    hosted = _frame_from([
        {"tokens_in": 100, "tokens_out": 50, "model": "deepseek-r1", "provider": "qwen"},
    ])
    assert hosted["usd"] is None


async def test_answer_stream_end_usage_estimated_no_usd(memdb, monkeypatch):
    """Estimated tokens are never priced: usd stays None (key present) and
    estimated=True even for a known-price model."""
    from server.orchestrator import arslan, tool_loop

    async def fake_run_native(*, system, user_content, history, emit, on_chunk,
                              resolve_tools, allow_escalation, confirm_command=None,
                              conversation_id=None):
        usage_sink.report(800)   # estimate path: total only, both-None detail
        usage_sink.report_detail(tokens_in=None, tokens_out=None,
                                 model=SONNET, provider="anthropic")
        return {"final": "done", "tool_trace": [{"tool": "web_search"}]}

    monkeypatch.setattr(tool_loop, "run_native", fake_run_native)
    events: list[dict] = []
    await arslan._handle_answer("c-frame-est", "hi", events.append)
    usage = [e for e in events if e["type"] == "stream_end"][0]["usage"]
    assert usage["tokens_in"] is None
    assert usage["tokens_out"] is None
    assert usage["tokens_total"] == 800
    assert usage["estimated"] is True
    assert usage["usd"] is None
