"""A remote connection that asks the user to sign in at its install test: not failed, and not working. It stays
installed and switched off, says it needs sign-in, and switches on at its first listing after the sign-in, which is
also where its tools are pinned (CAP5a)."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from mcp import types

from server.db.models import CapabilitySource, MCPServer
from server.mcp import discovery, oauth_flow, session
from server.mcp.supervisor import SIGN_IN_LINE, StartResult, supervisor
from server.services import capability_flow, capability_install, capability_list

REMOTE = {"id": "registry:com.example/notes@1.0.0", "kind": "mcp", "name": "notes", "summary": "Notes",
          "source": "registry", "source_url": "https://mcp.example.com/mcp", "repo": None, "version": "1.0.0",
          "runtime": "remote", "package": None, "remote": {"url": "https://mcp.example.com/mcp"}, "not_here": None,
          "path": None, "stars": None, "pushed_days": None, "needs": {"keys": [], "network": True},
          "license": {"spdx": "MIT", "read_from": "LICENSE@v1.0.0", "verdict": "usable"}}
REJECTED_KEY = ("authorization failed (HTTP 401): the server rejected the configured headers — re-check the "
                "token/key on this server")
WAITING = {"ok": False, "stage": "sign_in", "needs_sign_in": True, "detail": SIGN_IN_LINE, "at": "2026-11-07T00:00:00Z"}


@pytest.fixture
def remote_install(execution_db, monkeypatch):
    """`capability_install.install` for a remote server: a row switched off, with its capability source."""
    async def install(c, *, folders, keys, prepared=None):
        async with execution_db() as db:
            server = MCPServer(label="notes", transport="http", command="", args=[], url="https://mcp.example.com/mcp",
                               status="registered", state="off", host_allowed=False)
            db.add(server)
            await db.flush()
            row = CapabilitySource(id="src1", kind="mcp", name="notes", candidate_id=c["id"], runtime="remote",
                                   needs={}, grants={}, state="installed", mcp_server_id=server.id,
                                   created_at=datetime.utcnow(), installed_at=datetime.utcnow())
            db.add(row)
            await db.commit()
            return row
    monkeypatch.setattr(capability_install, "install", install)


def _answer(monkeypatch, result):
    async def restart(server_id):
        return result
    monkeypatch.setattr(supervisor, "restart", restart)


async def test_a_server_asking_for_sign_in_stays_installed_and_off(execution_db, monkeypatch, remote_install):
    _answer(monkeypatch, StartResult("needs_auth", last_error=SIGN_IN_LINE))
    out = await capability_flow.install_mcp(REMOTE, folders=[], keys={})
    assert out["state"] == "needs_sign_in" and out["source_id"] == "src1"
    async with execution_db() as db:
        row = await db.get(CapabilitySource, "src1")
        assert row.state == "installed" and row.error is None
        assert row.test["needs_sign_in"] is True and row.test["ok"] is False and row.test["stage"] == "sign_in"
        server = await db.get(MCPServer, row.mcp_server_id)
        assert server.host_allowed is False and server.state == "off"     # nothing runs until the sign-in


async def test_a_real_start_keeps_the_line_the_authorize_button_reads(execution_db, monkeypatch):
    """Through the supervisor's own classification, with only the listing stubbed: the page shows Authorize when the
    server's `last_error` names authorization, and that line has to outlive the switch-off."""
    await _source_with(execution_db, {})

    async def wants_a_browser(server, cursor=None):
        raise oauth_flow.NeedsInteractiveAuth("wants a browser")
    monkeypatch.setattr(session.manager, "list_tools", wants_a_browser)
    test = await capability_flow.test_mcp("src1")
    assert test["needs_sign_in"] is True
    async with execution_db() as db:
        server = await db.get(MCPServer, 1)
        assert server.state == "off" and server.host_allowed is False and server.last_error == SIGN_IN_LINE


async def test_a_rejected_key_is_still_a_failed_test(execution_db, monkeypatch, remote_install):
    """A browser can't fix a key the server refuses, so that isn't a wait for sign-in."""
    _answer(monkeypatch, StartResult("needs_auth", last_error=REJECTED_KEY))
    out = await capability_flow.install_mcp(REMOTE, folders=[], keys={"Authorization": "Bearer wrong"})
    assert out["state"] == "failed" and out["stage"] == "test"
    async with execution_db() as db:
        row = await db.get(CapabilitySource, "src1")
        assert row.state == "failed" and "needs_sign_in" not in row.test


def _serve(monkeypatch, *listings):
    queue = list(listings)

    async def fake_list(server, cursor=None):
        return SimpleNamespace(tools=queue.pop(0), nextCursor=None)
    monkeypatch.setattr(session.manager, "list_tools", fake_list)


def _tool(name="read"):
    return types.Tool(name=name, description="reads a note",
                      inputSchema={"type": "object", "properties": {"id": {"type": "string"}}})


async def _source_with(execution_db, test, *, state="off", status="registered", last_error=None):
    created = datetime.utcnow() - timedelta(minutes=1)
    async with execution_db() as db:
        db.add(MCPServer(id=1, label="notes", transport="http", command="", args=[], url="https://mcp.example.com/mcp",
                         status=status, state=state, host_allowed=False, last_error=last_error, created_at=created))
        await db.flush()
        db.add(CapabilitySource(id="src1", kind="mcp", name="notes", candidate_id="c", runtime="remote", needs={},
                                grants={}, state="installed", mcp_server_id=1, test=test,
                                created_at=datetime.utcnow(), installed_at=datetime.utcnow()))
        await db.commit()


async def _row():
    return next(r for r in await capability_list._mcp_rows() if r["key"] == "mcp:1")


async def _read(execution_db):
    async with execution_db() as db:
        return (await db.get(CapabilitySource, "src1")).test, (await db.get(MCPServer, 1)).host_allowed


async def test_the_first_listing_after_sign_in_pins_and_switches_on(execution_db, monkeypatch):
    await _source_with(execution_db, dict(WAITING))
    _serve(monkeypatch, [_tool()])
    await discovery.connect_and_discover(1)
    test, allowed = await _read(execution_db)
    assert allowed is True
    assert test["ok"] is True and test["tools"] == ["read"] and list(test["tools_pin"]) == ["read"]
    assert not {"needs_sign_in", "stage", "detail"} & set(test)


async def test_a_first_listing_with_no_sign_in_waiting_leaves_the_switch_alone(execution_db, monkeypatch):
    """A source from before the pin (CAP5a's upgrade) that the user switched off stays off when it next connects."""
    await _source_with(execution_db, {"ok": True, "tools": ["read"]})
    _serve(monkeypatch, [_tool()])
    await discovery.connect_and_discover(1)
    test, allowed = await _read(execution_db)
    assert allowed is False and list(test["tools_pin"]) == ["read"]


async def test_an_empty_listing_after_sign_in_keeps_waiting(execution_db, monkeypatch):
    """A connection has to list a tool to pass, as at the install test."""
    await _source_with(execution_db, dict(WAITING))
    _serve(monkeypatch, [])
    await discovery.connect_and_discover(1)
    test, allowed = await _read(execution_db)
    assert allowed is False and test["needs_sign_in"] is True and "tools_pin" not in test


@pytest.mark.parametrize("state, status", [("needs_auth", "error"), ("off", "error"), ("off", "registered")])
async def test_the_row_says_it_needs_sign_in_also_after_a_restart(execution_db, state, status):
    """A restart writes `off` over `needs_auth`, so the row reads the source's record, not the server's state."""
    await _source_with(execution_db, dict(WAITING), state=state, status=status, last_error=SIGN_IN_LINE)
    row = await _row()
    assert row["state"] == "setup" and row["reason"] == "needs_sign_in" and row["fix"]
    assert row["origin"] == "installed" and row["deletable"] is True


async def test_a_new_server_with_a_freed_number_is_not_read_as_waiting(execution_db):
    """mcp_servers.id has no AUTOINCREMENT, so a server added later can get the number of one deleted by hand."""
    await _source_with(execution_db, dict(WAITING), status="connected")
    async with execution_db() as db:
        (await db.get(MCPServer, 1)).created_at = datetime.utcnow() + timedelta(minutes=1)
        await db.commit()
    row = await _row()
    assert row["reason"] != "needs_sign_in" and row["origin"] == "manual"


async def test_after_the_sign_in_the_row_is_an_ordinary_connection(execution_db, monkeypatch):
    await _source_with(execution_db, dict(WAITING))
    _serve(monkeypatch, [_tool()])
    await discovery.connect_and_discover(1)
    assert (await _row())["reason"] != "needs_sign_in"
