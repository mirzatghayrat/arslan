"""C3a: catalog rows with no executor are retired at boot (card C3).

- `session_search`, `skills_management` (skills_list, skill_view, skill_manage) and `task_planning` (todo)
  are whole toolsets whose tools no executor runs. They join RETIRED_TOOLSET_KEYS, the mechanism that has
  retired 22 toolsets before.
- `patch` is one row inside `file_operations`, which stays. RETIRED_TOOLS names it with its toolset, so
  only that row goes: a `patch` row anywhere else is not the seeder's and is left alone (the lesson of D7).
"""
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Tool, Toolset
from server.registry import seed_catalog, seeder

DEAD_TOOLSETS = {"session_search": ["session_search"],
                 "skills_management": ["skills_list", "skill_view", "skill_manage"],
                 "task_planning": ["todo"]}


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def _toolset(key):
    return Toolset(key=key, name=key, description="old seed", tier="safe", status="registered")


def _tool(key, toolset_key):
    return Tool(key=key, toolset_key=toolset_key, description="old", tier="safe", status="registered",
                input_schema={})


async def test_boot_deletes_the_dead_rows_and_nothing_else(maker):
    async with maker() as s:
        for ts, tools in DEAD_TOOLSETS.items():
            s.add(_toolset(ts))
            s.add_all(_tool(t, ts) for t in tools)
        s.add(_toolset("file_operations"))
        s.add_all(_tool(t, "file_operations") for t in ("read_file", "write_file", "patch"))
        s.add(_toolset("mcp_x"))
        s.add(_tool("mcp_x__patch", "mcp_x"))
        await s.commit()

    await seeder.seed_registry()
    await seeder.seed_registry()            # idempotent

    async with maker() as s:
        toolsets = {t.key for t in (await s.execute(select(Toolset))).scalars()}
        tools = {t.key for t in (await s.execute(select(Tool))).scalars()}
    assert not set(DEAD_TOOLSETS) & toolsets
    assert not {t for ts in DEAD_TOOLSETS.values() for t in ts} & tools
    assert "patch" not in tools
    assert {"file_operations", "mcp_x"} <= toolsets
    assert {"read_file", "write_file", "mcp_x__patch"} <= tools


async def test_a_patch_row_that_is_not_the_seeders_is_kept(maker):
    async with maker() as s:
        s.add(_toolset("mcp_y"))
        s.add(_tool("patch", "mcp_y"))
        await s.commit()

    await seeder.seed_registry()

    async with maker() as s:
        row = await s.get(Tool, "patch")
    assert row is not None and row.toolset_key == "mcp_y"


def test_the_catalog_no_longer_offers_them():
    keys = {ts["key"] for ts in seed_catalog.TOOLSETS}
    assert not set(DEAD_TOOLSETS) & keys
    file_ops = next(ts for ts in seed_catalog.TOOLSETS if ts["key"] == "file_operations")
    assert "patch" not in {t[0] for t in file_ops["tools"]} and "patch" not in file_ops["description"]
    assert set(DEAD_TOOLSETS) <= set(seeder.RETIRED_TOOLSET_KEYS)
