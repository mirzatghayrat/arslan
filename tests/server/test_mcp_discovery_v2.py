"""Discovery follows the server (0.1.61 §B1, §B4)."""
import asyncio
from types import SimpleNamespace

import pytest
from mcp import types
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from server.db import session as db_session
from server.db.models import MCPServer, Tool, Toolset
from server.mcp import discovery, session


@pytest.fixture
async def db(execution_db):
    async with execution_db() as s:
        s.add(MCPServer(id=1, label="fs", command="x", args=[], status="registered"))
        s.add(MCPServer(id=2, label="other", command="y", args=[], status="registered"))
        s.add(Toolset(key="mcp_2", name="other", description="d", tier="orchestrator",
                      status="registered"))
        await s.flush()                 # foreign keys are on: the toolset row must exist first
        s.add(Tool(key="mcp_2__keep", toolset_key="mcp_2", description="keep", tier="orchestrator",
                   status="registered", input_schema={}, external_name="keep"))
        await s.commit()
    return execution_db


def _tool(name, **hints):
    return types.Tool(name=name, inputSchema={"type": "object"},
                      annotations=types.ToolAnnotations(**hints) if hints else None)


def _serve(monkeypatch, *listings):
    """Each connect gets the next listing; a listing is a list of pages (lists of tools)."""
    calls, queue, current = [], list(listings), {}

    async def fake_list(server, cursor=None):
        calls.append(cursor)
        if cursor is None:
            current["pages"], current["i"] = queue.pop(0), 0
        i = current["i"]
        current["i"] = i + 1
        pages = current["pages"]
        return SimpleNamespace(tools=pages[i], nextCursor=f"p{i + 1}" if i + 1 < len(pages) else None)
    monkeypatch.setattr(session.manager, "list_tools", fake_list)
    return calls


async def _names(maker, ts="mcp_1"):
    async with maker() as s:
        rows = (await s.execute(select(Tool).where(Tool.toolset_key == ts))).scalars().all()
    return sorted(t.external_name for t in rows)


async def test_a_vanished_tool_is_pruned_and_other_servers_are_untouched(db, monkeypatch):
    _serve(monkeypatch, [[_tool("a"), _tool("b")]], [[_tool("a")]])
    await discovery.connect_and_discover(1)
    await discovery.connect_and_discover(1)
    assert await _names(db) == ["a"] and await _names(db, "mcp_2") == ["keep"]


async def test_an_empty_listing_never_wipes_the_tools(db, monkeypatch):
    _serve(monkeypatch, [[_tool("a")]], [[]])
    await discovery.connect_and_discover(1)
    await discovery.connect_and_discover(1)
    assert await _names(db) == ["a"]


async def test_a_wired_tool_keeps_its_wiring_when_listed_again(db, monkeypatch):
    _serve(monkeypatch, [[_tool("read_file")]], [[_tool("read_file")]])
    await discovery.connect_and_discover(1)
    async with db() as s:
        row = await s.get(Tool, "mcp_1__read_file")
        row.tier, row.status = "safe", "wired"
        await s.commit()
    await discovery.connect_and_discover(1)
    async with db() as s:
        row = await s.get(Tool, "mcp_1__read_file")
    assert (row.tier, row.status) == ("safe", "wired")


async def test_every_page_is_followed(db, monkeypatch):
    calls = _serve(monkeypatch, [[_tool("a")], [_tool("b")], [_tool("c")]])
    out = await discovery.connect_and_discover(1)
    assert calls == [None, "p1", "p2"] and sorted(t["name"] for t in out) == ["a", "b", "c"]


async def test_pagination_stops_at_twenty_pages_and_then_prunes_nothing(db, monkeypatch):
    _serve(monkeypatch, [[_tool("old")]])
    await discovery.connect_and_discover(1)

    async def endless(server, cursor=None):
        n = int(cursor or 0)
        return SimpleNamespace(tools=[_tool(f"t{n}")], nextCursor=str(n + 1))
    monkeypatch.setattr(session.manager, "list_tools", endless)
    await discovery.connect_and_discover(1)
    names = await _names(db)
    assert "old" in names and len(names) == discovery.MAX_PAGES + 1


async def test_hints_are_stored_as_declared(db, monkeypatch):
    odd = SimpleNamespace(name="c", description="c", inputSchema={},
                          annotations={"destructiveHint": "yes", "openWorldHint": False})
    _serve(monkeypatch, [[_tool("a", readOnlyHint=True, title="  Read A  "), _tool("b"), odd]])
    await discovery.connect_and_discover(1)
    async with db() as s:
        a, b, c = [await s.get(Tool, f"mcp_1__{n}") for n in "abc"]
    assert a.annotations == {"readOnlyHint": True, "title": "Read A"}
    assert b.annotations is None
    assert c.annotations == {"openWorldHint": False}          # a non-boolean hint is dropped


async def test_no_database_session_is_open_while_listing(db, monkeypatch):
    active = {"n": 0}
    real = db_session.AsyncSessionLocal

    class _Counted:
        def __init__(self):
            self.inner = real()

        async def __aenter__(self):
            active["n"] += 1
            return await self.inner.__aenter__()

        async def __aexit__(self, *a):
            active["n"] -= 1
            return await self.inner.__aexit__(*a)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", _Counted)

    async def listing(server, cursor=None):
        assert active["n"] == 0, "a database session is open across a tools/list await"
        return SimpleNamespace(tools=[_tool("a")], nextCursor=None)
    monkeypatch.setattr(session.manager, "list_tools", listing)
    await discovery.connect_and_discover(1)


async def test_two_listings_at_once_write_the_union_without_a_conflict(db, monkeypatch):
    async def slow(server, cursor=None):
        await asyncio.sleep(0.01)
        return SimpleNamespace(tools=[_tool("a"), _tool("b")], nextCursor=None)
    monkeypatch.setattr(session.manager, "list_tools", slow)
    await asyncio.gather(discovery.connect_and_discover(1), discovery.connect_and_discover(1))
    assert await _names(db) == ["a", "b"]


async def test_relist_never_opens_a_session(db, monkeypatch):
    async def must_not_list(server, cursor=None):
        raise AssertionError("relist opened a session")
    monkeypatch.setattr(session.manager, "list_tools", must_not_list)
    assert await discovery.relist(1) is None


async def test_relist_lists_on_the_live_session(db, monkeypatch):
    _serve(monkeypatch, [[_tool("a"), _tool("b")]])
    monkeypatch.setitem(session.manager._sessions, 1, ("live", None))
    out = await discovery.relist(1)
    assert sorted(t["name"] for t in out) == ["a", "b"] and await _names(db) == ["a", "b"]


async def test_the_budget_reaches_the_session_manager(db, monkeypatch):
    seen = []

    async def listing(server, cursor=None):
        seen.append(server.get("start_budget_s"))
        return SimpleNamespace(tools=[_tool("a")], nextCursor=None)
    monkeypatch.setattr(session.manager, "list_tools", listing)
    await discovery.connect_and_discover(1, start_budget_s=120.0)
    assert seen == [120.0]


async def test_an_unknown_server_is_server_gone(db):
    with pytest.raises(discovery.ServerGone):
        await discovery.connect_and_discover(999)
    assert issubclass(discovery.ServerGone, ValueError)        # the API still answers 404


async def test_an_open_that_was_overtaken_is_not_recorded_as_an_error(db, monkeypatch):
    """Carry 2a: a drop or forget during the open supersedes it (NotStarted). The open was
    overtaken, not failed: no status="error", no "has no live session", no tool written."""
    opening, release = asyncio.Event(), asyncio.Event()

    async def closed():
        return None

    async def slow_open(server):
        opening.set()
        await release.wait()
        return SimpleNamespace(), SimpleNamespace(aclose=closed)
    monkeypatch.setattr(session.manager, "_open_session", slow_open)
    task = asyncio.create_task(discovery.connect_and_discover(1))
    await asyncio.wait_for(opening.wait(), 5)
    await session.manager.drop(1)                 # supersedes the open that is still running
    release.set()
    with pytest.raises(session.NotStarted):
        await task
    async with db() as s:
        srv = await s.get(MCPServer, 1)
    assert srv.status == "registered" and srv.last_error is None
    assert await _names(db) == [] and session.manager.cached(1) is None


async def test_a_real_failure_is_still_recorded_next_to_the_overtaken_case(db, monkeypatch):
    async def boom(server, cursor=None):
        raise RuntimeError("cannot launch npx")
    monkeypatch.setattr(session.manager, "list_tools", boom)
    with pytest.raises(RuntimeError):
        await discovery.connect_and_discover(1)
    async with db() as s:
        srv = await s.get(MCPServer, 1)
    assert srv.status == "error" and "npx" in srv.last_error


async def test_a_tool_listed_again_is_updated_in_place(db, monkeypatch):
    first = types.Tool(name="a", description="old", inputSchema={"type": "object"},
                       annotations=types.ToolAnnotations(readOnlyHint=True))
    second = types.Tool(name="a", description="new",
                        inputSchema={"type": "object", "properties": {"p": {"type": "string"}}})
    _serve(monkeypatch, [[first]], [[second]])
    await discovery.connect_and_discover(1)
    await discovery.connect_and_discover(1)
    async with db() as s:
        row = await s.get(Tool, "mcp_1__a")
    assert row.description == "new" and "p" in row.input_schema["properties"]
    assert row.annotations is None                    # the hint is gone from the server's listing


def _watch_writes(monkeypatch):
    """Wrap the write so the test sees how many run at once; each takes a moment."""
    real, seen = discovery._write_once, {"now": 0, "most": 0, "calls": 0}

    async def watched(*args, **kwargs):
        seen["calls"] += 1
        seen["now"] += 1
        seen["most"] = max(seen["most"], seen["now"])
        try:
            await asyncio.sleep(0.02)
            return await real(*args, **kwargs)
        finally:
            seen["now"] -= 1
    monkeypatch.setattr(discovery, "_write_once", watched)
    return seen


async def test_one_servers_writes_never_overlap_but_two_servers_may(db, monkeypatch):
    seen = _watch_writes(monkeypatch)

    async def listing(server, cursor=None):
        return SimpleNamespace(tools=[_tool("a")], nextCursor=None)
    monkeypatch.setattr(session.manager, "list_tools", listing)
    await asyncio.gather(*(discovery.connect_and_discover(1) for _ in range(3)))
    assert seen["calls"] == 3 and seen["most"] == 1
    await asyncio.gather(discovery.connect_and_discover(1), discovery.connect_and_discover(2))
    assert seen["most"] == 2                       # the lock is per server, not global


async def test_a_conflicting_insert_is_retried_once_and_then_raised(db, monkeypatch):
    real, calls = discovery._write_once, []

    async def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
        return await real(*args, **kwargs)
    monkeypatch.setattr(discovery, "_write_once", flaky)
    _serve(monkeypatch, [[_tool("a")]])
    await discovery.connect_and_discover(1)
    assert len(calls) == 2 and await _names(db) == ["a"]

    calls.clear()

    async def always(*args, **kwargs):
        calls.append(1)
        raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
    monkeypatch.setattr(discovery, "_write_once", always)
    _serve(monkeypatch, [[_tool("a")]])
    with pytest.raises(IntegrityError):
        await discovery.connect_and_discover(1)
    assert len(calls) == 2                         # one retry, no more
