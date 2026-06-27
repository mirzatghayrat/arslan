import anyio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine


def test_migration_0011_adds_columns(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'m11.db'}")

    async def _run():
        from server.db.models import Base
        from server.db.migrations.versions._0011_mcp_http_host import upgrade_sync
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(upgrade_sync)
        async with engine.connect() as conn:
            tool_cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("tools")})
            srv_cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("mcp_servers")})
        return tool_cols, srv_cols

    tool_cols, srv_cols = anyio.run(_run)
    assert "host_enabled" in tool_cols
    assert "url" in srv_cols


def test_host_enabled_defaults_false(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'m11b.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _run():
        from server.db.models import Base, Tool, Toolset
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            s.add(Toolset(key="mcp_1", name="x", description="d", tier="orchestrator", status="registered"))
            s.add(Tool(key="mcp_1__t", toolset_key="mcp_1", description="d", tier="orchestrator",
                       status="registered", input_schema={}, external_name="t"))
            await s.commit()
        async with maker() as s:
            from sqlalchemy import select
            t = (await s.execute(select(Tool).where(Tool.key == "mcp_1__t"))).scalar_one()
            return t.host_enabled
    assert anyio.run(_run) in (False, 0, None)   # default falsey
