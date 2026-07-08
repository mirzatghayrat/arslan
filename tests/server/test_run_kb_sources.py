import anyio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from server.db.models import Base
from server.db.migrations.versions._0023_run_kb_sources import upgrade_sync


def test_0023_adds_column(tmp_path):
    async def _run():
        e = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'k.db'}")
        async with e.begin() as c:
            await c.run_sync(Base.metadata.create_all)
            await c.run_sync(upgrade_sync)
            cols = await c.run_sync(lambda x: {col["name"] for col in inspect(x).get_columns("runs")})
        await e.dispose()
        return cols
    assert "injected_kb_sources" in anyio.run(_run)


def test_run_trace_prompt_carries_kb_sources():
    from server.orchestrator import run_trace
    with run_trace.collecting():
        run_trace.record_prompt(system_prompt="SYS", injected_kb=None, injected_kb_sources=["条款.pdf", "https://x"])
        assert run_trace.prompt()["injected_kb_sources"] == ["条款.pdf", "https://x"]
