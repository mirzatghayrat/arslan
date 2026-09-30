"""Task 3: propose_connect_mcp frame builder + the card-build orchestrator branch.

env_keys carries credential NAMES + metadata ONLY (never values) — the frontend's
password field is where a value is ever entered. A known connector emits the confirm
card; an unknown one gets an honest redirect to Settings, never a wall.
"""
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


def test_to_frame_preserves_requires_path_and_path_placeholder():
    """_to_frame is on the LIVE primary send path (emit -> _drain -> ws.send_json).
    A propose_connect_mcp event dict for Filesystem must survive the rebuild through
    _to_frame with requires_path/path_placeholder intact — dropping them means the
    browser renders a card with no path input and the connect silently fails
    (Filesystem/Git launch without their required path)."""
    from server.ws.arslan import _to_frame

    ev = {
        "type": "propose_connect_mcp",
        "call_id": "c3", "key": "filesystem", "label": "Filesystem", "transport": "stdio",
        "command": "npx", "argv": ["-y", "@modelcontextprotocol/server-filesystem"],
        "url": None, "env_keys": [], "prerequisites": "",
        "requires_path": True, "path_placeholder": "/absolute/path/to/expose",
    }
    frame = _to_frame(ev)
    assert frame == protocol.propose_connect_mcp(
        call_id="c3", key="filesystem", label="Filesystem", transport="stdio",
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


# 0.1.48: the card is offered by the agent calling `suggest_connector`, not by a
# pre-turn router verdict.

async def _turn(monkeypatch, name, *, live=True):
    from server.orchestrator import arslan, tool_loop
    from server.services import turn_facts
    from tests.server.test_arslan_loop import _LLMResp, _NativeAdapter, _tc

    async def _no_facts(conv, msg):
        return []

    async def _confirm(*a, **k):
        return True

    monkeypatch.setattr(turn_facts, "extract", _no_facts)
    seen = []

    class _Adapter(_NativeAdapter):
        async def chat(self, system, user, history=None, tools=None, temperature=0.7):
            seen.append(user)
            return await super().chat(system, user, history, tools, temperature)

    adapter = _Adapter([_LLMResp(tool_calls=[_tc("suggest_connector", {"name": name})]),
                        _LLMResp(content="done")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    events = []
    await arslan.handle_user_message("c1", f"connect my {name}", events.append,
                                     confirm_command=_confirm if live else None)
    return events, seen


async def test_a_known_connector_paints_the_card_and_connects_nothing(maker, monkeypatch):
    events, _ = await _turn(monkeypatch, "GitHub")
    [card] = [e for e in events if e["type"] == "propose_connect_mcp"]
    assert card["key"] == "github" and card["env_keys"][0]["name"] == "GITHUB_PERSONAL_ACCESS_TOKEN"
    assert all("value" not in e for e in card["env_keys"])


async def test_filesystem_card_asks_for_a_path(maker, monkeypatch):
    events, _ = await _turn(monkeypatch, "Filesystem")
    [card] = [e for e in events if e["type"] == "propose_connect_mcp"]
    assert card["requires_path"] is True


async def test_an_unknown_connector_tells_the_agent_what_exists_instead_of_a_canned_reply(maker, monkeypatch):
    events, seen = await _turn(monkeypatch, "Apple Reminders")
    assert not [e for e in events if e["type"] == "propose_connect_mcp"]
    tool_result = str(seen[-1])
    assert "no built-in connector" in tool_result and "GitHub" in tool_result   # the real list
    text = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
    assert "don't have a preset" not in text and text == "done"
