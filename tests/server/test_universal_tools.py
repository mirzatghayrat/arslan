from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


async def test_arslan_host_tools_include_render_chart(monkeypatch):
    from server.orchestrator import arslan
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    tools = await arslan._callable_tools()
    assert {"web_search", "web_extract", "render_chart"} <= {t["key"] for t in tools}
