"""Task 3: mcp_connect_followup frame builder + mcp_service.tier_counts (DB-authoritative,
mirrors registry.service.assert_assignable's ">=1 safe+wired tool" toolset gate) + the
confirm_connect_mcp WS verb end-to-end.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, MCPServer, Tool, Toolset
from server.ws import protocol
from tests.server.conftest import build_ws_client


def test_followup_reports_tier_split_and_ready_when_assignable():
    f = protocol.mcp_connect_followup(server_id=3, tool_count=4, safe_count=3,
                                      restricted_count=1, assignable=True)
    assert f["type"] == "mcp_connect_followup"
    assert f["assignable"] is True and f["safe_count"] == 3 and f["restricted_count"] == 1


def test_followup_all_restricted_is_not_ready():
    f = protocol.mcp_connect_followup(server_id=3, tool_count=2, safe_count=0,
                                      restricted_count=2, assignable=False)
    assert f["assignable"] is False and f["safe_count"] == 0


# ── mcp_service.tier_counts: DB-authoritative, matches assert_assignable's predicate ──


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'tc.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def _seed_server(m) -> int:
    async with m() as s:
        srv = MCPServer(label="github", command="npx", args=[], transport="stdio",
                        status="connected")
        s.add(srv)
        await s.commit()
        await s.refresh(srv)
        return srv.id


async def test_tier_counts_mixed_tiers(maker):
    from server.services import mcp_service
    sid = await _seed_server(maker)
    async with maker() as s:
        s.add(Toolset(key=f"mcp_{sid}", name="github", description="MCP server: npx",
                      tier="safe", status="registered"))
        s.add(Tool(key=f"mcp_{sid}__list_issues", toolset_key=f"mcp_{sid}",
                   description="list issues", tier="safe", status="wired",
                   input_schema={}, external_name="list_issues"))
        s.add(Tool(key=f"mcp_{sid}__create_pr", toolset_key=f"mcp_{sid}",
                   description="create a PR", tier="safe", status="wired",
                   input_schema={}, external_name="create_pr"))
        s.add(Tool(key=f"mcp_{sid}__delete_repo", toolset_key=f"mcp_{sid}",
                   description="delete a repo", tier="orchestrator", status="registered",
                   input_schema={}, external_name="delete_repo"))
        await s.commit()

    counts = await mcp_service.tier_counts(sid)
    assert counts == {"tool_count": 3, "safe_count": 2, "restricted_count": 1,
                      "assignable": True}


async def test_tier_counts_all_restricted_not_assignable(maker):
    """A safe+REGISTERED (not wired) tool does not count toward safe_count — mirrors
    assert_assignable's has_wired subquery, which requires status=='wired' exactly
    (server/registry/service.py:377-384), not the broader is_assignable() status set."""
    from server.services import mcp_service
    sid = await _seed_server(maker)
    async with maker() as s:
        s.add(Toolset(key=f"mcp_{sid}", name="github", description="MCP server: npx",
                      tier="safe", status="registered"))
        s.add(Tool(key=f"mcp_{sid}__delete_repo", toolset_key=f"mcp_{sid}",
                   description="delete a repo", tier="orchestrator", status="registered",
                   input_schema={}, external_name="delete_repo"))
        s.add(Tool(key=f"mcp_{sid}__not_yet_wired", toolset_key=f"mcp_{sid}",
                   description="not yet wired", tier="safe", status="registered",
                   input_schema={}, external_name="not_yet_wired"))
        await s.commit()

    counts = await mcp_service.tier_counts(sid)
    assert counts == {"tool_count": 2, "safe_count": 0, "restricted_count": 2,
                      "assignable": False}


async def test_tier_counts_no_tools_yet(maker):
    from server.services import mcp_service
    sid = await _seed_server(maker)
    counts = await mcp_service.tier_counts(sid)
    assert counts == {"tool_count": 0, "safe_count": 0, "restricted_count": 0,
                      "assignable": False}


# ── confirm_connect_mcp WS verb: end-to-end, counts computed from the DB ───────────


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    async def _seed(maker):
        async with maker() as s:
            srv = MCPServer(id=9, label="github", command="npx", args=[], transport="stdio",
                            status="connected")
            s.add(srv)
            s.add(Toolset(key="mcp_9", name="github", description="MCP server: npx",
                          tier="safe", status="registered"))
            s.add(Tool(key="mcp_9__list_issues", toolset_key="mcp_9",
                       description="list issues", tier="safe", status="wired",
                       input_schema={}, external_name="list_issues"))
            s.add(Tool(key="mcp_9__delete_repo", toolset_key="mcp_9",
                       description="delete a repo", tier="orchestrator", status="registered",
                       input_schema={}, external_name="delete_repo"))
            await s.commit()

    return build_ws_client(portal, tmp_path, monkeypatch, _seed, db_name="mcpconfirm.db")


def test_confirm_connect_mcp_emits_db_authoritative_followup(app_client):
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "confirm_connect_mcp", "server_id": 9})
        followup = ws.receive_json()
        assert followup["type"] == "mcp_connect_followup"
        assert followup["server_id"] == 9
        assert followup["tool_count"] == 2
        assert followup["safe_count"] == 1
        assert followup["restricted_count"] == 1
        assert followup["assignable"] is True


def test_confirm_connect_mcp_counts_are_from_db_not_client(app_client):
    """The client sending a bogus/absent tool_count must not influence the result —
    the follow-up is recomputed from the DB every time (honesty requirement)."""
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "confirm_connect_mcp", "server_id": 9, "tool_count": 999})
        followup = ws.receive_json()
        assert followup["tool_count"] == 2   # DB truth, not the client-supplied 999
