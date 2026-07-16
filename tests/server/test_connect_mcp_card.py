"""Task 3: propose_connect_mcp frame builder + the card-build orchestrator branch.

env_keys carries credential NAMES + metadata ONLY (never values) — the frontend's
password field is where a value is ever entered. A known connector emits the confirm
card; an unknown one gets an honest redirect to Settings, never a wall.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.ws import protocol


def test_propose_connect_mcp_carries_env_names_not_values():
    frame = protocol.propose_connect_mcp(
        call_id="c1", key="github", label="GitHub", transport="stdio",
        command="npx", argv=["-y", "@modelcontextprotocol/server-github"], url=None,
        env_keys=[{"name": "GITHUB_PERSONAL_ACCESS_TOKEN",
                   "description": "A GitHub PAT.", "get_it_url": "https://github.com/settings/tokens",
                   "paid": False}],
        prerequisites="Needs a GitHub personal access token.")
    assert frame["type"] == "propose_connect_mcp"
    # Names + metadata present; NO value field anywhere.
    assert frame["env_keys"][0]["name"] == "GITHUB_PERSONAL_ACCESS_TOKEN"
    assert "value" not in {k for e in frame["env_keys"] for k in e}   # schema has no value key
    # requires_path/path_placeholder default off for a credential-only connector.
    assert frame["requires_path"] is False
    assert frame["path_placeholder"] is None


def test_propose_connect_mcp_carries_requires_path_for_local_path_connectors():
    """Filesystem/Git need a local path (non-secret) — the card must know to collect
    it in a plain text field, not a password field."""
    frame = protocol.propose_connect_mcp(
        call_id="c2", key="filesystem", label="Filesystem", transport="stdio",
        command="npx", argv=["-y", "@modelcontextprotocol/server-filesystem"], url=None,
        env_keys=[], prerequisites="",
        requires_path=True, path_placeholder="/absolute/path/to/expose")
    assert frame["requires_path"] is True
    assert frame["path_placeholder"] == "/absolute/path/to/expose"


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'card.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_suggest_connect_mcp_known_connector_emits_propose_card(maker, monkeypatch):
    """Router action dispatch: a NAMED, catalogued connector emits propose_connect_mcp
    (mirrors how test_suggest_create_equipped.py drives handle_user_message with a
    fake RouterResult + a captured emit)."""
    from server.orchestrator import arslan, router

    async def _fake_route(conv, msg):
        return router.RouterResult(action="suggest_connect_mcp", connector_query="github")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    events = []
    await arslan.handle_user_message("main", "connect my github", lambda ev: events.append(ev))

    card = next(e for e in events if e["type"] == "propose_connect_mcp")
    assert card["key"] == "github"
    assert card["transport"] == "stdio"
    assert card["env_keys"][0]["name"] == "GITHUB_PERSONAL_ACCESS_TOKEN"
    assert "value" not in {k for e in card["env_keys"] for k in e}
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in card["prerequisites"]
    assert card["requires_path"] is False


@pytest.mark.asyncio
async def test_suggest_connect_mcp_filesystem_card_carries_requires_path(maker, monkeypatch):
    """The card-build branch reads requires_path/path_placeholder off the catalog
    connector (Filesystem needs a local path, no credential) — regression guard for
    the requires_path wiring added alongside the ConnectMcpCard apply chain."""
    from server.orchestrator import arslan, router

    async def _fake_route(conv, msg):
        return router.RouterResult(action="suggest_connect_mcp", connector_query="filesystem")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    events = []
    await arslan.handle_user_message("main", "connect my filesystem", lambda ev: events.append(ev))

    card = next(e for e in events if e["type"] == "propose_connect_mcp")
    assert card["key"] == "filesystem"
    assert card["requires_path"] is True
    assert card["path_placeholder"] == "/absolute/path/to/expose"


@pytest.mark.asyncio
async def test_suggest_connect_mcp_unknown_connector_is_honest_redirect_not_a_card(
    maker, monkeypatch
):
    """No preset for the query → a plain text answer pointing at Settings, NOT a wall
    and NOT a propose_connect_mcp frame (arbitrary connectors are v2)."""
    from server.orchestrator import arslan, router

    async def _fake_route(conv, msg):
        return router.RouterResult(action="suggest_connect_mcp", connector_query="zzz-nope")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    events = []
    await arslan.handle_user_message("main", "connect my zzz-nope", lambda ev: events.append(ev))

    assert not any(e["type"] == "propose_connect_mcp" for e in events)
    text = "".join(e.get("content", "") for e in events if e.get("type") == "stream_chunk")
    assert "zzz-nope" in text
    assert "Settings" in text
