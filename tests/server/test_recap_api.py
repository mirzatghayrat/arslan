import datetime as dt

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ConversationEvent, Run
from server.services import recap_service


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'recap.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_recap_merges_runs_and_events(maker):
    now = dt.datetime.utcnow()
    async with db_session.AsyncSessionLocal() as db:
        db.add(Run(conversation_id="c", spawn_name="Deck", status="scored", overall_score=9.0,
                   total_ms=6500, user_message="出 deck", created_at=now - dt.timedelta(minutes=2)))
        db.add(ConversationEvent(conversation_id="c", kind="memory", ref=None,
                                 summary="领域兴趣:半导体", created_at=now - dt.timedelta(minutes=1)))
        db.add(ConversationEvent(conversation_id="other", kind="memory", summary="别的会话"))
        await db.commit()

    body = await recap_service.get_recap("c")
    kinds = [i["kind"] for i in body["items"]]
    assert "run" in kinds and "memory" in kinds
    assert body["summary"]["run_count"] == 1
    assert body["summary"]["growth_count"] == 1        # 'other' conversation excluded
    assert body["summary"]["avg_score"] == 9.0
    # newest first: the memory event (-1min) comes before the run (-2min)
    assert body["items"][0]["kind"] == "memory"


@pytest.mark.asyncio
async def test_recap_empty(maker):
    body = await recap_service.get_recap("nope")
    assert body["items"] == []
    assert body["summary"] == {"run_count": 0, "avg_score": None, "growth_count": 0}


def test_recap_endpoint_registered():
    import os
    import sys
    os.environ.setdefault("ARSLAN_SECRET_KEY", "dev")
    import server.api.conversations as conv_mod
    from server.main import create_app
    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    if "/api/v1/conversations/{conversation_id}/recap" not in paths:  # DIAGNOSTIC (temp)
        try:
            import fastapi
            import fastapi.routing
            from server.api import health as health_mod
            fastapi_in_globals = create_app.__globals__["FastAPI"]
            probe = fastapi_in_globals(title="probe")
            before = len(probe.routes)
            probe.include_router(conv_mod.router, prefix="/probe")
            after = len(probe.routes)
            conv_route_cls = type(conv_mod.router.routes[0])
            print(f"\n[recap-diag] app.routes={len(app.routes)} "
                  f"include_router={type(app.include_router)}", file=sys.stderr)
            print(f"[recap-diag] fastapi.__file__={fastapi.__file__} "
                  f"ver={getattr(fastapi, '__version__', '?')}", file=sys.stderr)
            print(f"[recap-diag] FastAPI(create_app globals) id={id(fastapi_in_globals)} "
                  f"is fastapi.FastAPI={fastapi_in_globals is fastapi.FastAPI} "
                  f"app class id={id(type(app))}", file=sys.stderr)
            print(f"[recap-diag] health.router routes={len(health_mod.router.routes)} "
                  f"conv.router routes={len(conv_mod.router.routes)}", file=sys.stderr)
            print(f"[recap-diag] LIVE probe include_router {before}->{after} | "
                  f"conv route cls={conv_route_cls.__module__}.{conv_route_cls.__qualname__} "
                  f"id={id(conv_route_cls)} | app APIRoute id={id(fastapi.routing.APIRoute)} "
                  f"same={conv_route_cls is fastapi.routing.APIRoute}", file=sys.stderr)
            print(f"[recap-diag] all app paths={sorted(str(p) for p in paths)}", file=sys.stderr)
            import importlib
            import server.main as _main_mod
            importlib.reload(_main_mod)
            app2 = _main_mod.create_app()
            p2 = {r.path for r in app2.routes if hasattr(r, "path")}
            print(f"[recap-diag] after reload(server.main): app2.routes={len(app2.routes)} "
                  f"recap_present={'/api/v1/conversations/{conversation_id}/recap' in p2}",
                  file=sys.stderr)
        except Exception as _diag_exc:  # noqa: BLE001 — diagnostics must not mask the assert
            print(f"[recap-diag] diag error: {_diag_exc!r}", file=sys.stderr)
    assert "/api/v1/conversations/{conversation_id}/recap" in paths
