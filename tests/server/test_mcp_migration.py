import anyio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession


def test_migration_0010_creates_mcp_servers_and_external_name(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'m.db'}")

    async def _run():
        from server.db.models import Base
        from server.db.migrations.versions._0010_mcp_servers import upgrade_sync
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(upgrade_sync)            # idempotent on top of create_all
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
            cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("tools")})
        return tables, cols

    tables, cols = anyio.run(_run)
    assert "mcp_servers" in tables
    assert "external_name" in cols          # added to existing tools table


def test_mcpserver_model_roundtrips(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'m2.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _run():
        from server.db.models import Base, MCPServer
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            s.add(MCPServer(label="fs", command="npx", args=["-y", "server-filesystem"], env="enc", status="registered"))
            await s.commit()
        async with maker() as s:
            from sqlalchemy import select
            row = (await s.execute(select(MCPServer))).scalar_one()
            return row.label, row.command, row.args, row.status

    label, command, args, status = anyio.run(_run)
    assert (label, command, args, status) == ("fs", "npx", ["-y", "server-filesystem"], "registered")
