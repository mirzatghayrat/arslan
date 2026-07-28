import datetime as dt

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ConversationEvent, Run
from server.services import recap_service


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'recap.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

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
    os.environ.setdefault("ARSLAN_SECRET_KEY", "dev")
    from server.main import create_app
    app = create_app()
    from tests.route_introspection import iter_route_paths
    paths = iter_route_paths(app)
    assert "/api/v1/conversations/{conversation_id}/recap" in paths
