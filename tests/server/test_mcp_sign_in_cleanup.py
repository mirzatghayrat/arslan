"""Removing an MCP server removes its stored sign-in, on every path that removes one."""
import asyncio
from datetime import datetime

import httpx
import pytest
from mcp.client.streamable_http import streamablehttp_client as real_streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import select

from server.db.migrations.versions import _0090_mcp_sign_in_cleanup as m0090
from server.db.models import CapabilitySource, MCPServer, Setting
from server.mcp import oauth_flow, session
from server.mcp import supervisor as sm
from server.mcp.supervisor import supervisor
from server.services import capability_install, capability_list, mcp_service

URL = "https://mcp.example.test/mcp"
OTHER_URL = "https://other.example.test/mcp"


@pytest.fixture
async def db(execution_db, tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sm, "FIRST_START_GAPS_S", (0.0, 0.0, 0.0))
    monkeypatch.setattr(capability_install, "capabilities_root", lambda: tmp_path / "capabilities")
    monkeypatch.setattr(capability_install, "to_trash", lambda path, prefix="x": None)
    yield execution_db
    await session.manager.aclose_all()


async def _server(db, server_id, url=URL):
    async with db() as s:
        s.add(MCPServer(id=server_id, label=f"server {server_id}", transport="http", command="", args=[], url=url,
                        status="connected", state="off", host_allowed=False))
        await s.commit()


async def _signed_in(server_id):
    storage = oauth_flow.EncryptedTokenStorage(server_id)
    await storage.set_tokens(OAuthToken(access_token="-".join(["stored", "access", str(server_id)]),
                                        refresh_token="-".join(["stored", "refresh", str(server_id)])))
    await storage.set_client_info(OAuthClientInformationFull(client_id=f"client-{server_id}",
                                                             redirect_uris=["http://127.0.0.1:1/callback"]))


async def _keys(db):
    async with db() as s:
        return {k for k in (await s.execute(select(Setting.key))).scalars() if k.startswith("mcp_oauth_")}


async def _remove_by_hand(db):
    await mcp_service.delete_server(1)


async def _remove_a_listed_one(db):
    await capability_list.remove("mcp:1")


async def _remove_an_installed_one(db):
    async with db() as s:
        s.add(CapabilitySource(id="src1", kind="mcp", name="server 1", candidate_id="c", runtime="remote", needs={},
                               grants={}, state="installed", mcp_server_id=1, created_at=datetime.utcnow(),
                               installed_at=datetime.utcnow()))
        await s.commit()
    await capability_install.remove("src1")


@pytest.mark.parametrize("remove", [_remove_by_hand, _remove_a_listed_one, _remove_an_installed_one])
async def test_every_way_of_removing_a_server_removes_its_sign_in(db, remove):
    await _server(db, 1)
    await _server(db, 2, OTHER_URL)
    await _signed_in(1)
    await _signed_in(2)
    await remove(db)
    assert await _keys(db) == {"mcp_oauth_tokens_2", "mcp_oauth_client_2"}
    assert await oauth_flow.has_tokens(1) is False and await oauth_flow.has_tokens(2) is True


async def test_a_new_server_starts_with_no_sign_in_on_the_wire(db, monkeypatch):
    """Through the real transport: what the next server under a freed number sends."""
    await _server(db, 1)
    await _signed_in(1)
    await mcp_service.delete_server(1)
    await _server(db, 1, OTHER_URL)
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(401 if request.method == "POST" else 405, request=request)

    def factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=headers, timeout=timeout, auth=auth,
                                 follow_redirects=True)

    def client(url, headers=None, auth=None, **kw):
        return real_streamablehttp_client(url, headers=headers, auth=auth, httpx_client_factory=factory, **kw)
    monkeypatch.setattr(session, "streamablehttp_client", client)
    await supervisor.restart(1)
    assert seen and all(url == OTHER_URL and authorization is None for url, authorization in seen)


async def test_a_sign_in_finishing_after_the_remove_stores_nothing(db):
    """A browser flow outlives the button that started it, and a refresh can outlive its session."""
    await _server(db, 1)
    storage = oauth_flow.EncryptedTokenStorage(1)
    await mcp_service.delete_server(1)
    await storage.set_tokens(OAuthToken(access_token="-".join(["late", "access"])))
    await storage.set_client_info(OAuthClientInformationFull(client_id="late",
                                                             redirect_uris=["http://127.0.0.1:1/callback"]))
    assert await _keys(db) == set()


async def test_a_sign_in_finishing_during_the_remove_leaves_nothing(db):
    """The write and the remove at the same moment: whichever runs first, no key outlives the server."""
    for _ in range(40):
        await _server(db, 1)
        storage = oauth_flow.EncryptedTokenStorage(1)
        await asyncio.gather(storage.set_tokens(OAuthToken(access_token="-".join(["racing", "access"]))),
                             mcp_service.delete_server(1))
        assert await _keys(db) == set()


async def test_a_second_write_replaces_the_first(db):
    await _server(db, 1)
    storage = oauth_flow.EncryptedTokenStorage(1)
    await storage.set_tokens(OAuthToken(access_token="-".join(["first", "access"])))
    await storage.set_tokens(OAuthToken(access_token="-".join(["second", "access"])))
    assert (await storage.get_tokens()).access_token == "-".join(["second", "access"])
    assert await _keys(db) == {"mcp_oauth_tokens_1"}


async def test_a_live_server_keeps_and_can_read_its_sign_in(db):
    await _server(db, 1)
    await _signed_in(1)
    storage = oauth_flow.EncryptedTokenStorage(1)
    assert (await storage.get_tokens()).access_token == "-".join(["stored", "access", "1"])
    assert (await storage.get_client_info()).client_id == "client-1"


# ── what earlier versions left behind ─────────────────────────────────────────

async def test_the_migration_removes_only_sign_ins_with_no_server(db):
    await _server(db, 1)
    await _signed_in(1)
    async with db() as s:
        s.add_all([Setting(key="mcp_oauth_tokens_7", value="x"), Setting(key="mcp_oauth_client_7", value="x"),
                   Setting(key="mcp_oauth_tokens_notanumber", value="keep"), Setting(key="mcp_oauth_tokens_5x", value="keep"),
                   Setting(key="some_other_setting", value="keep")])
        await s.commit()
    async with db.kw["bind"].begin() as connection:
        await connection.run_sync(m0090.upgrade_sync)
        await connection.run_sync(m0090.upgrade_sync)      # a re-run changes nothing
    async with db() as s:
        left = set((await s.execute(select(Setting.key))).scalars())
    assert {"mcp_oauth_tokens_1", "mcp_oauth_client_1", "mcp_oauth_tokens_notanumber", "mcp_oauth_tokens_5x",
            "some_other_setting"} <= left
    assert not {"mcp_oauth_tokens_7", "mcp_oauth_client_7"} & left


async def test_the_migration_is_quiet_with_no_tables(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(m0090.upgrade_sync)
    await engine.dispose()
