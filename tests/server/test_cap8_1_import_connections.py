"""CAP8-1: the MCP servers the user already configured in Claude Code and Codex, brought in by the user's click.

Driven through the two routes, on fake files under a scratch HOME (an autouse fixture: no test reads a real file).
The install tests run real from the route down: the pin, the lock, the install, the scan, the supervisor, the session
and a real process. Stand-ins: the network, the npm and uv steps, where Arslan's runtime comes from, and the seatbelt
wrap (macOS only, and a Python program needs its own interpreter readable), which records what it was asked.
"""
import asyncio
import json
import logging
import os
import pathlib
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

import server.main  # noqa: F401 — production's logging setup, which what's asserted of the logs goes through
from server import auth, crypto
from server.api.capabilities import router
from server.db.models import Base, CapabilitySource, MCPServer
from server.mcp import session
from server.mcp import supervisor as supervisor_module
from server.registry import executors
from server.services import (capability_allowlist, capability_flow, capability_install, capability_list,
                             capability_runtime, capability_sandbox, capability_scan)

RealClient = httpx.AsyncClient
URL = "/api/v1/capability-import"
#: A fake key: every test asserts it stays out of what it must stay out of.
FAKE = "fake-key-value-never-shown-0427"
SERVER = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"
#: A locked package's program: it notes what it was started with, then answers as the fake server does.
PROGRAM = (f"import json, os, runpy, sys\n"
           f"with open(os.path.join(os.path.dirname(__file__), 'started_with.json'), 'w') as out:\n"
           f"    json.dump({{'env': dict(os.environ), 'argv': sys.argv[1:]}}, out)\n"
           f"print('started as', sys.argv[1:], file=sys.stderr, flush=True)\n"
           f"runpy.run_path({str(SERVER)!r}, run_name='__main__')\n")
REMOTE = "https://mcp.example.test/mcp"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """The scratch home every test reads from. `Path.home()` follows $HOME."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "data"))
    assert Path.home() == folder
    return folder


@pytest.fixture
async def api(execution_db, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with RealClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                          headers={"Authorization": "Bearer synthetic-token"}) as client:
        yield client


def _claude(home, servers, **other):
    (home / ".claude.json").write_text(json.dumps({"mcpServers": servers, **other}))


def _codex(home, text):
    (home / ".codex").mkdir(exist_ok=True)
    (home / ".codex" / "config.toml").write_text(text)


async def _scan(api) -> dict:
    response = await api.get(URL)
    assert response.status_code == 200, response.text
    return response.json()


def _row(scan: dict, row_id: str) -> dict:
    return next(row for row in scan["servers"] if row["id"] == row_id)


async def _add(api, scan: dict, *ids: str, keys: dict | None = None) -> dict:
    body = {"servers": [{"id": i, "digest": _row(scan, i)["digest"], "keys": (keys or {}).get(i, {})} for i in ids]}
    response = await api.post(URL, json=body)
    assert response.status_code == 200, response.text
    return {result["id"]: result for result in response.json()["results"]}


async def _rows(execution_db, model) -> list:
    async with execution_db() as db:
        return list((await db.execute(select(model))).scalars().all())


async def _nothing_stored_holds(execution_db, *values: str) -> None:
    """Every row of every table, the ledger's among them, read as text."""
    async with execution_db() as db:
        for table in Base.metadata.sorted_tables:
            text = repr((await db.execute(select(table))).all())
            for value in values:
                assert value not in text, f"{table.name} holds it"


# ── what the sheet lists ─────────────────────────────────────────────────────────────────────────────────────────

CODEX = """
model = "not-a-server"

[mcp_servers.docs]
command = "npx"
args = ["docs-server@2.0.0"]
env_vars = ["DOCS_TOKEN", { name = "DOCS_OTHER", source = "remote" }]

[mcp_servers.api]
url = "https://api.example.test/mcp"
bearer_token_env_var = "API_TOKEN"
http_headers = { "X-Team" = "core" }
env_http_headers = { "X-Key" = "API_KEY" }

[mcp_servers.tools]
command = "uvx"
args = ["tools-server"]
env = { TOOLS_TOKEN = "fake-key-value-never-shown-0427" }
"""


async def test_the_sheet_lists_each_kind_from_both_tools_with_what_each_shows(api, home):
    _claude(home, {"notes": {"command": "npx", "args": ["-y", "notes-server"], "env": {"NOTES_TOKEN": FAKE, "MODE": "x"}},
                   "typed": {"type": "stdio", "command": "uvx", "args": ["files-server"]},
                   "vendor": {"type": "http", "url": f"{REMOTE}?team=core",
                              "headers": {"Authorization": "Bearer ${VENDOR_TOKEN}", "X-Team": "core"}},
                   "alias": {"type": "streamable-http", "url": "http://localhost:3100/mcp"},
                   "mine": {"command": "/opt/tools/mine", "args": ["--serve"], "env": {"MINE_TOKEN": FAKE}}})
    _codex(home, CODEX)
    scan = await _scan(api)
    assert scan["tools"] == [{"tool": "claude_code", "state": "read", "count": 5},
                             {"tool": "codex", "state": "read", "count": 3}]

    notes = _row(scan, "claude_code:notes")
    assert (notes["kind"], notes["command"], notes["arguments"]) == ("package", "npx", ["-y", "notes-server"])
    assert (notes["keys"], notes["asks"], notes["network"], notes["tick"]) == (2, [], True, True)
    assert _row(scan, "claude_code:typed")["kind"] == "package"
    assert _row(scan, "claude_code:typed")["network"] is False          # CAP4's rule: no key, no network

    vendor = _row(scan, "claude_code:vendor")
    assert (vendor["kind"], vendor["address"]) == ("remote", "https://mcp.example.test")
    assert (vendor["keys"], vendor["asks"], vendor["network"]) == (1, ["VENDOR_TOKEN"], True)
    assert _row(scan, "claude_code:alias")["address"] == "http://localhost:3100"

    mine = _row(scan, "claude_code:mine")
    assert (mine["kind"], mine["command"], mine["arguments"]) == ("program", "/opt/tools/mine", ["--serve"])
    assert (mine["refused"], mine["tick"], mine["keys"]) == ("custom_program", False, 1)

    assert _row(scan, "codex:docs")["asks"] == ["DOCS_OTHER", "DOCS_TOKEN"]
    assert _row(scan, "codex:docs")["keys"] == 0
    api_row = _row(scan, "codex:api")
    assert (api_row["kind"], api_row["address"]) == ("remote", "https://api.example.test")
    assert (api_row["keys"], api_row["asks"]) == (1, ["API_KEY", "API_TOKEN"])
    assert _row(scan, "codex:tools")["keys"] == 1
    assert FAKE not in json.dumps(scan)


async def test_it_reads_only_the_user_scope_and_the_codex_table(api, home):
    _claude(home, {"notes": {"command": "npx", "args": ["notes-server"]}},
            projects={"/some/project": {"mcpServers": {"local-one": {"command": "npx", "args": ["local-server"]}}}},
            oauthAccount={"emailAddress": "someone@example.test"}, primaryApiKey=FAKE)
    (home / ".mcp.json").write_text(json.dumps({"mcpServers": {"project-one": {"command": "npx", "args": ["p"]}}}))
    _codex(home, "[mcp]\nsomething = 1\n[profile.other.mcp_servers.nested]\ncommand = 'npx'\n")
    scan = await _scan(api)
    assert [row["id"] for row in scan["servers"]] == ["claude_code:notes"]
    assert FAKE not in json.dumps(scan) and "someone@example.test" not in json.dumps(scan)


async def test_a_missing_file_reads_as_nothing_and_says_so(api, home):
    _codex(home, "[mcp_servers.docs]\ncommand = 'npx'\nargs = ['docs-server']\n")
    scan = await _scan(api)
    assert scan["tools"][0] == {"tool": "claude_code", "state": "missing", "count": 0}
    assert [row["id"] for row in scan["servers"]] == ["codex:docs"]


@pytest.mark.parametrize("claude, codex", [
    ('{"mcpServers": {"x": {"env": {"T": "%s"}}}' % FAKE, 'key = "%s"\n[broken' % FAKE),   # cut short, quoting a key
    ('["%s"]' % FAKE, 'mcp_servers = "%s"\n' % FAKE),                                       # the wrong shape
    ('{"mcpServers": "%s"}' % FAKE, 'mcp_servers = ["%s"]\n' % FAKE)])
async def test_a_malformed_file_reads_as_nothing_says_so_and_never_quotes_itself(api, home, caplog, claude, codex):
    caplog.set_level(logging.DEBUG)
    (home / ".claude.json").write_text(claude)
    _codex(home, codex)
    scan = await _scan(api)
    assert scan == {"tools": [{"tool": "claude_code", "state": "malformed", "count": 0},
                              {"tool": "codex", "state": "malformed", "count": 0}], "servers": []}
    assert FAKE not in json.dumps(scan) and FAKE not in caplog.text


async def test_one_bad_entry_is_listed_as_unreadable_and_the_others_stay(api, home):
    _claude(home, {"text": "not a table", "no-command": {"args": ["x"]}, "notes": {"command": "npx", "args": ["n"]},
                   "bad-args": {"command": "npx", "args": "n"}, "bad-env": {"command": "npx", "args": ["n"], "env": ["T"]},
                   "number": {"command": "npx", "args": ["n"], "env": {"PORT": 8080}},
                   "url-no-type": {"url": REMOTE}, "bad-url": {"type": "http", "url": "ftp://x.example.test/"}})
    _codex(home, "[mcp_servers.neither]\nstartup_timeout_sec = 5\n[mcp_servers.names]\ncommand = 'npx'\nargs = ['n']\n"
                 "env_vars = 'NOT_A_LIST'\n[mcp_servers.nameless]\ncommand = 'npx'\nargs = ['n']\n"
                 "env_vars = [{ source = 'remote' }]\n")
    scan = await _scan(api)
    for row_id in ("text", "no-command", "bad-args", "bad-env", "number", "url-no-type", "bad-url"):
        assert _row(scan, f"claude_code:{row_id}")["refused"] == "unreadable", row_id
        assert _row(scan, f"claude_code:{row_id}")["tick"] is False, row_id
    assert _row(scan, "codex:neither")["refused"] == "unreadable"
    assert _row(scan, "codex:names")["refused"] == "unreadable"
    assert _row(scan, "codex:nameless")["refused"] == "unreadable"
    assert _row(scan, "claude_code:notes")["refused"] is None


# ── keys ─────────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_the_scan_says_how_many_keys_and_shows_none(api, home, caplog):
    caplog.set_level(logging.DEBUG)
    _claude(home, {
        "env": {"command": "npx", "args": ["n"], "env": {"A_TOKEN": FAKE}},
        "header": {"type": "http", "url": REMOTE, "headers": {"Authorization": f"Bearer {FAKE}", "X-Other": FAKE}},
        "query": {"type": "http", "url": f"{REMOTE}?token={FAKE}"},
        "user": {"type": "http", "url": f"https://me:{FAKE}@mcp.example.test/mcp"},
        "flag": {"command": "npx", "args": ["n", f"--api-key={FAKE}"]},
        "next": {"command": "npx", "args": ["n", "--token", FAKE]},
        "program": {"command": "/opt/tools/mine", "args": [f"--password={FAKE}"], "env": {"X": FAKE}},
        "sse": {"type": "sse", "url": f"{REMOTE}?token={FAKE}", "headers": {"X-Key": FAKE}},
        "broken": {"type": "http", "url": f"{REMOTE}?token={FAKE}", "headers": {"Host": FAKE}}})
    _codex(home, f'[mcp_servers.secret]\nurl = "{REMOTE}"\nhttp_headers = {{ "X-Key" = "{FAKE}" }}\n'
                 f'[mcp_servers.secret.oauth]\nclient_id = "public-id"\nclient_secret = "{FAKE}"\n')
    scan = await _scan(api)
    assert FAKE not in json.dumps(scan) and FAKE not in caplog.text
    counts = {row["id"].split(":")[1]: row["keys"] for row in scan["servers"]}
    assert counts["env"] == 1 and counts["header"] == 2 and counts["query"] == 1 and counts["user"] == 1
    assert counts["flag"] == 1 and counts["next"] == 1 and counts["program"] == 2 and counts["secret"] == 1
    # A mask, not the value, where the sheet shows the line.
    assert _row(scan, "claude_code:flag")["arguments"] == ["n", "--api-key=●●●●"]
    assert _row(scan, "claude_code:program")["arguments"] == ["--password=●●●●"]


async def test_the_digest_cannot_be_tried_against_a_guess_at_the_key(api, home):
    """Two processes' digests of one file differ, so a digest says nothing about what it covers."""
    from server.services import connection_import
    _claude(home, {"notes": {"command": "npx", "args": ["n"], "env": {"T": FAKE}}})
    first = _row(await _scan(api), "claude_code:notes")["digest"]
    assert first == _row(await _scan(api), "claude_code:notes")["digest"]
    connection_import._DIGEST_KEY = b"another process"
    try:
        assert first != _row(await _scan(api), "claude_code:notes")["digest"]
    finally:
        connection_import._DIGEST_KEY = connection_import.secrets.token_bytes(32)


@pytest.mark.parametrize("env, code", [
    ({"T": "${A:-default}"}, "cannot_pin"), ({"T": "before-${A}"}, "cannot_pin"), ({"T": "${A}${B}"}, "cannot_pin"),
    ({"NODE_OPTIONS": "--require /tmp/x.js"}, "unsafe_setting"), ({"DYLD_INSERT_LIBRARIES": "/tmp/x"}, "unsafe_setting"),
    ({"PATH": "/tmp"}, "unsafe_setting"), ({"HTTPS_PROXY": "http://x.example.test"}, "unsafe_setting"),
    ({"npm_config_registry": "https://x.example.test"}, "unsafe_setting"), ({"BAD NAME": "x"}, "unreadable")])
async def test_a_setting_it_cannot_take_refuses_that_package_and_nothing_is_installed(api, home, execution_db, env, code):
    _claude(home, {"notes": {"command": "npx", "args": ["n"], "env": env}})
    scan = await _scan(api)
    assert (_row(scan, "claude_code:notes")["refused"], _row(scan, "claude_code:notes")["tick"]) == (code, False)
    assert (await _add(api, scan, "claude_code:notes"))["claude_code:notes"]["state"] == "refused"
    assert await _rows(execution_db, MCPServer) == [] and await _rows(execution_db, CapabilitySource) == []


@pytest.mark.parametrize("spec, code", [
    ({"type": "http", "url": REMOTE, "headers": {"Host": "evil.example.test"}}, "unsafe_setting"),
    ({"type": "http", "url": REMOTE, "headers": {"X-Forwarded-Host": "evil.example.test"}}, "unsafe_setting"),
    ({"type": "http", "url": REMOTE, "headers": {"Authorization": "${A} ${B}"}}, "cannot_pin"),
    ({"type": "http", "url": "https://${HOST}/mcp"}, "cannot_pin"),
    ({"type": "http", "url": REMOTE, "headersHelper": "/opt/print-headers"}, "runs_a_helper"),
    ({"type": "sse", "url": REMOTE}, "transport"), ({"type": "ws", "url": "wss://mcp.example.test/ws"}, "transport"),
    ({"type": "sdk"}, "transport"),
    ({"command": "npx", "args": ["n", "${A}"]}, "cannot_pin"), ({"command": "npx", "args": ["--from", "x", "y"]}, "cannot_pin"),
    ({"command": "npx", "args": []}, "cannot_pin"), ({"command": "npx", "args": ["n​"]}, "unreadable")])
async def test_a_line_it_cannot_take_is_refused_and_nothing_is_installed(api, home, execution_db, spec, code):
    _claude(home, {"one": spec})
    scan = await _scan(api)
    assert _row(scan, "claude_code:one")["refused"] == code
    result = (await _add(api, scan, "claude_code:one"))["claude_code:one"]
    assert (result["state"], result["code"]) == ("refused", code)
    assert await _rows(execution_db, MCPServer) == []


async def test_a_codex_helper_is_refused_as_claude_codes_is(api, home):
    _codex(home, f'[mcp_servers.helped]\nurl = "{REMOTE}"\nhttp_headers_helper = "/opt/print-headers"\n')
    assert _row(await _scan(api), "codex:helped")["refused"] == "runs_a_helper"


# ── the address the sheet shows is the one the connection opens ──────────────────────────────────────────────────

@pytest.mark.parametrize("url, shown", [
    ("https://me:pw@mcp.example.test/mcp", "https://mcp.example.test"),
    ("https://mcp.example.test\\@evil.example.test/mcp", "https://evil.example.test"),
    ("HTTPS://MCP.Example.Test:8443/mcp?x=1", "https://mcp.example.test:8443"),
    ("https://münchen.example.test/mcp", "https://xn--mnchen-3ya.example.test"),
    ("http://[::1]:8080/mcp", "http://[::1]:8080")])
async def test_the_address_shown_is_what_httpx_will_open(api, home, url, shown):
    _claude(home, {"one": {"type": "http", "url": url}})
    row = _row(await _scan(api), "claude_code:one")
    assert (row["kind"], row["address"]) == ("remote", shown)
    assert httpx.URL(url).netloc.decode() == shown.split("://")[1]


# ── custom programs: the user's decision, still open ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command", ["/opt/tools/mine", "python3", "node", "docker", "/usr/local/bin/npx", "NPX", "bunx"])
async def test_a_custom_program_is_listed_with_its_command_and_add_refuses_it(api, home, execution_db, command):
    _claude(home, {"mine": {"command": command, "args": ["--serve"], "env": {"T": FAKE}}})
    scan = await _scan(api)
    row = _row(scan, "claude_code:mine")
    assert (row["kind"], row["command"], row["refused"], row["tick"]) == ("program", command, "custom_program", False)
    result = (await _add(api, scan, "claude_code:mine"))["claude_code:mine"]
    assert (result["state"], result["code"]) == ("refused", "custom_program")
    assert await _rows(execution_db, MCPServer) == [] and await _rows(execution_db, CapabilitySource) == []


# ── a server the file has turned off, and tool limits ───────────────────────────────────────────────────────────

async def test_a_server_off_in_codex_is_listed_unticked_and_a_tick_still_takes_it(api, home):
    _codex(home, f'[mcp_servers.off]\nurl = "{REMOTE}"\nenabled = false\n[mcp_servers.on]\nurl = "https://b.example.test/m"\n')
    scan = await _scan(api)
    assert (_row(scan, "codex:off")["on_there"], _row(scan, "codex:off")["tick"]) == (False, False)
    assert (_row(scan, "codex:on")["on_there"], _row(scan, "codex:on")["tick"]) == (True, True)
    assert _row(scan, "codex:off")["refused"] is None


async def test_tool_limits_that_do_not_come_along_are_said_and_start_unticked(api, home):
    _codex(home, f'[mcp_servers.limited]\nurl = "{REMOTE}"\ndisabled_tools = ["danger"]\n'
                 f'[mcp_servers.narrow]\nurl = "https://b.example.test/m"\nenabled_tools = ["one"]\n'
                 f'[mcp_servers.plain]\nurl = "https://c.example.test/m"\n')
    scan = await _scan(api)
    for row_id, limited in (("limited", True), ("narrow", True), ("plain", False)):
        row = _row(scan, f"codex:{row_id}")
        assert (row["tool_limits"], row["tick"]) == (limited, not limited), row_id


# ── what's already here ──────────────────────────────────────────────────────────────────────────────────────────

async def test_a_server_already_here_is_marked_and_add_skips_it(api, home, execution_db):
    async with execution_db() as db:
        db.add(MCPServer(id=1, label="by hand", transport="http", command="", args=[], url=f"{REMOTE}/", state="off"))
        db.add(MCPServer(id=2, label="pinned by hand", transport="stdio", command="npx", args=["-y", "hand-server@1.0.0"],
                         state="off"))
        db.add(MCPServer(id=3, label="installed", transport="stdio", command="/data/venv/bin/x", args=[], state="off"))
        db.add(CapabilitySource(id="s3", kind="mcp", name="installed", candidate_id="registry:x@1", runtime="uv",
                                candidate={"package": {"identifier": "installed-server", "version": "3.0.0"}},
                                needs={}, grants={}, state="installed", mcp_server_id=3, created_at=datetime.utcnow()))
        db.add(MCPServer(id=4, label="mine", transport="stdio", command="/opt/tools/mine", args=["--serve"], state="off"))
        # Gone from here: a removed source and a failed install hold no server, so they can be brought in again.
        db.add(CapabilitySource(id="s4", kind="mcp", name="removed", candidate_id="registry:y@1", runtime="node",
                                candidate={"package": {"identifier": "removed-server", "version": "1.0.0"}},
                                needs={}, grants={}, state="removed", created_at=datetime.utcnow()))
        db.add(CapabilitySource(id="s5", kind="mcp", name="failed", candidate_id="registry:z@1", runtime="node",
                                candidate={"package": {"identifier": "failed-server", "version": "1.0.0"}},
                                needs={}, grants={}, state="failed", created_at=datetime.utcnow()))
        await db.commit()
    _claude(home, {"url": {"type": "http", "url": REMOTE}, "hand": {"command": "npx", "args": ["hand-server"]},
                   "installed": {"command": "uvx", "args": ["installed-server@2.0.0"]},
                   "mine": {"command": "/opt/tools/mine", "args": ["--serve"]},
                   "removed": {"command": "npx", "args": ["removed-server"]},
                   "failed": {"command": "npx", "args": ["failed-server"]},
                   "other-arguments": {"command": "npx", "args": ["hand-server", "/another/folder"]}})
    scan = await _scan(api)
    for row_id in ("url", "hand", "installed", "mine"):
        assert (_row(scan, f"claude_code:{row_id}")["here"], _row(scan, f"claude_code:{row_id}")["tick"]) == (True, False), row_id
    for row_id in ("removed", "failed", "other-arguments"):
        assert (_row(scan, f"claude_code:{row_id}")["here"], _row(scan, f"claude_code:{row_id}")["tick"]) == (False, True), row_id
    assert (await _add(api, scan, "claude_code:url"))["claude_code:url"]["state"] == "here"
    assert len(await _rows(execution_db, MCPServer)) == 4


async def test_a_secret_in_the_address_does_not_hide_that_it_is_the_same_server(api, home, execution_db):
    async with execution_db() as db:
        db.add(MCPServer(id=1, label="moved", transport="http", command="", args=[], url=f"{REMOTE}?token=${{MOVED_TOKEN}}",
                         state="off"))
        await db.commit()
    _claude(home, {"same": {"type": "http", "url": f"{REMOTE}?token={FAKE}"},
                   "other": {"type": "http", "url": f"{REMOTE}?team=core"}})
    scan = await _scan(api)
    assert _row(scan, "claude_code:same")["here"] is True
    assert _row(scan, "claude_code:other")["here"] is False


async def test_the_same_server_in_both_tools_says_so_and_starts_unticked_once(api, home):
    _claude(home, {"notes": {"command": "npx", "args": ["-y", "notes-server"]}})
    _codex(home, "[mcp_servers.notes]\ncommand = 'npx'\nargs = ['notes-server@1.0.0']\n")
    scan = await _scan(api)
    assert (_row(scan, "claude_code:notes")["same_as"], _row(scan, "claude_code:notes")["tick"]) == (None, True)
    assert (_row(scan, "codex:notes")["same_as"], _row(scan, "codex:notes")["tick"]) == ("claude_code:notes", False)


# ── what the sheet showed is what's added ────────────────────────────────────────────────────────────────────────

async def test_a_file_that_changed_since_the_scan_adds_nothing(api, home, execution_db):
    _claude(home, {"vendor": {"type": "http", "url": REMOTE}, "keyed": {"type": "http", "url": REMOTE + "2", "headers": {"X": "a"}}})
    scan = await _scan(api)
    _claude(home, {"vendor": {"type": "http", "url": "https://evil.example.test/mcp"},
                   "keyed": {"type": "http", "url": REMOTE + "2", "headers": {"X": "b"}}})
    results = await _add(api, scan, "claude_code:vendor", "claude_code:keyed")
    assert results["claude_code:vendor"]["state"] == "changed" and results["claude_code:keyed"]["state"] == "changed"
    assert await _rows(execution_db, MCPServer) == []


async def test_a_server_gone_from_the_file_or_never_there_adds_nothing(api, home, execution_db):
    _claude(home, {"vendor": {"type": "http", "url": REMOTE}})
    scan = await _scan(api)
    _claude(home, {})
    assert (await _add(api, scan, "claude_code:vendor"))["claude_code:vendor"]["state"] == "gone"
    response = await api.post(URL, json={"servers": [{"id": "codex:never", "digest": "x"}]})
    assert response.json()["results"] == [{"id": "codex:never", "state": "gone"}]
    assert await _rows(execution_db, MCPServer) == []


async def test_a_digest_of_any_text_only_reads_as_changed(api, home):
    _claude(home, {"vendor": {"type": "http", "url": REMOTE}})
    response = await api.post(URL, json={"servers": [{"id": "claude_code:vendor", "digest": "not ascii: é"}]})
    assert response.json()["results"] == [{"id": "claude_code:vendor", "state": "changed"}]


async def test_a_key_the_line_asks_for_must_be_given(api, home, execution_db):
    _claude(home, {"vendor": {"type": "http", "url": REMOTE, "headers": {"Authorization": "Bearer ${VENDOR_TOKEN}"}}})
    scan = await _scan(api)
    for keys in ({}, {"OTHER": "x"}, {"VENDOR_TOKEN": "   "}):
        result = (await _add(api, scan, "claude_code:vendor", keys={"claude_code:vendor": keys}))["claude_code:vendor"]
        assert (result["state"], result["keys"]) == ("needs_keys", ["VENDOR_TOKEN"])
    assert await _rows(execution_db, MCPServer) == []


# ── only the user's click ────────────────────────────────────────────────────────────────────────────────────────

async def test_both_routes_sit_behind_the_same_auth_as_their_neighbours(api, home, execution_db):
    _claude(home, {"notes": {"command": "npx", "args": ["n"]}})
    async with RealClient(transport=api._transport, base_url="http://test") as anonymous:
        assert (await anonymous.get(URL)).status_code == 401
        assert (await anonymous.post(URL, json={"servers": []})).status_code == 401
        assert (await anonymous.get("/api/v1/capability-allowlist")).status_code == 401
    assert (await api.get(URL)).status_code == 200


def test_no_model_tool_reaches_this_only_the_route_does():
    """Nothing but the route imports the module, so no tool, job or prompt can call it or read what it reads; and
    nothing else in the server names the two files."""
    server = pathlib.Path(capability_flow.__file__).parents[1]
    importers, readers = [], []
    for path in server.rglob("*.py"):
        text = path.read_text()
        relative = str(path.relative_to(server))
        if relative != "services/connection_import.py":
            if re.search(r"\bconnection_import\b", text):
                importers.append(relative)
            if re.search(r"\.claude\.json|\.codex\b(?!-)", text):
                readers.append(relative)
    assert importers == ["api/capabilities.py"]
    assert readers == []


# ── the install, real from the route down ───────────────────────────────────────────────────────────────────────

class _World:
    """npm, PyPI and a remote, offline; nothing else answers."""

    def __init__(self, data):
        self.data, self.remote, self.sign_in, self.fail_lock, self.remote_status = data, [], False, None, None

    def __call__(self, request):
        host = request.url.host
        if host == "registry.npmjs.org":
            return httpx.Response(200, json={"latest": "1.2.3"})
        if host == "pypi.org":
            return httpx.Response(200, json={"info": {"version": "1.2.3"}})
        if host == "mcp.example.test":
            return self._remote(request)
        raise httpx.ConnectError(f"no such host here: {host}")

    def _remote(self, request):
        self.remote.append(request)
        if request.method != "POST":
            return httpx.Response(405)
        if self.sign_in:
            challenge = 'Bearer resource_metadata="https://mcp.example.test/.well-known/oauth-protected-resource/mcp"'
            return httpx.Response(401, headers={"WWW-Authenticate": challenge})
        if self.remote_status:
            return httpx.Response(self.remote_status)
        message = json.loads(request.content)
        if "id" not in message:
            return httpx.Response(202)
        result = ({"protocolVersion": message["params"]["protocolVersion"], "capabilities": {"tools": {}},
                   "serverInfo": {"name": "vendor", "version": "1"}} if message["method"] == "initialize"
                  else {"tools": [{"name": "search", "description": "searches", "inputSchema": {"type": "object"}}]})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    async def step(self, argv, *, cwd, env):
        """npm and uv, offline: the lock names what was asked for, and the install writes it."""
        tool, words = Path(argv[0]).name, argv[1:]
        if tool == "npm" and words[0] == "install":
            name, version = words[1].rsplit("@", 1)
            if name == self.fail_lock:
                raise capability_install.InstallFailure("step_failed", name)
            (cwd / "package-lock.json").write_text(json.dumps({"packages": {"": {"name": "arslan-capability"},
                f"node_modules/{name}": {"version": version, "integrity": "sha512-" + "A" * 86,
                                         "resolved": f"{capability_install.NPM_REGISTRY}{name}/-/x-{version}.tgz"}}}))
        elif tool == "npm":
            for path in json.loads((cwd / "package-lock.json").read_text())["packages"]:
                if path:
                    (cwd / path).mkdir(parents=True)
                    (cwd / path / "package.json").write_text(json.dumps({"bin": "bin.js"}))
                    (cwd / path / "bin.js").write_text(PROGRAM)
        elif words[:2] == ["pip", "compile"]:
            line = (cwd / "requirements.in").read_text().strip()
            (cwd / "requirements.lock").write_text(f"{line} \\\n    --hash=sha256:{'0' * 64}\n")
        elif words[0] == "venv":
            (cwd / "venv" / "bin").mkdir(parents=True)
        elif words[:2] == ["pip", "install"]:
            name, version = (cwd / "requirements.lock").read_text().split(" ")[0].split("==")
            dist = cwd / "venv" / "lib" / "python3.12" / "site-packages" / f"{name}-{version}.dist-info"
            dist.mkdir(parents=True)
            (dist / "entry_points.txt").write_text(f"[console_scripts]\n{name} = x:main\n")
            (cwd / "program.py").write_text(PROGRAM)
            script = cwd / "venv" / "bin" / name
            script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{cwd / "program.py"}" "$@"\n')
            script.chmod(0o755)
        return ""

    def prepared(self):
        folder = self.data / "capabilities" / ".prepared"
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    def package_started_with(self, source_id, package):
        return json.loads((self.data / "capabilities" / source_id / "node_modules" / package / "started_with.json").read_text())


@pytest.fixture
async def world(execution_db, tmp_path, monkeypatch):
    data = tmp_path / "data"
    here = _World(data)
    monkeypatch.setattr(capability_allowlist, "_IDS", {})

    class Offline(RealClient):
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)
            super().__init__(*args, transport=httpx.MockTransport(here), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", Offline)
    monkeypatch.setattr(capability_install, "_run", here.step)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for name in ("node", "uv"):
        (runtime / name).write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        (runtime / name).chmod(0o755)

    async def ensure(name):
        return runtime / name
    monkeypatch.setattr(capability_runtime, "ensure", ensure)
    here.wrapped = []

    def wrap(command, args, env, sandbox):
        here.wrapped.append(sandbox)
        return command, args, env, sandbox["root"]
    monkeypatch.setattr(capability_sandbox, "wrap", wrap)
    running = supervisor_module.Supervisor()
    running.maker = execution_db
    running.start(run_loops=False)
    monkeypatch.setattr(supervisor_module, "supervisor", running)
    yield here
    await asyncio.wait_for(running.stop(), 10)
    await asyncio.wait_for(session.manager.aclose_all(), 10)


async def _server_of(execution_db, result) -> tuple[CapabilitySource, MCPServer]:
    async with execution_db() as db:
        source = await db.get(CapabilitySource, result["source_id"])
        return source, await db.get(MCPServer, source.mcp_server_id)


@pytest.mark.real_mcp
async def test_a_package_goes_the_cap4_way_locked_sandboxed_and_on_with_its_keys_encrypted(api, home, execution_db, world, caplog):
    caplog.set_level(logging.DEBUG)
    _claude(home, {"notes": {"command": "npx", "args": ["-y", "notes-server", "--serve"],
                             "env": {"NOTES_TOKEN": FAKE, "MODE": "fast", "ASKED_TOKEN": "${MY_TOKEN}"}}})
    scan = await _scan(api)
    typed = "typed-value-for-this-test"
    result = (await _add(api, scan, "claude_code:notes",
                         keys={"claude_code:notes": {"MY_TOKEN": f" {typed}\n", "NOT_ASKED": "dropped-value"}}))["claude_code:notes"]
    assert result["state"] == "on", result
    assert result["tools"] == 1

    source, server = await _server_of(execution_db, result)
    assert (source.kind, source.state, source.runtime) == ("mcp", "installed", "node")
    assert source.candidate_id == "import:claude_code:notes"
    assert source.version == "1.2.3"                                       # pinned: the file named no version
    assert source.lock_sha256                                              # and locked
    assert source.test["tools_pin"] and source.test["ok"] is True          # the tool pin, from the test's listing
    assert source.scan["level"] == "clean"
    assert server.host_allowed is True
    assert server.sandbox["network"] is True and server.sandbox["root"].endswith(source.id)
    assert world.wrapped and world.wrapped[-1]["root"] == server.sandbox["root"]
    assert world.prepared() == []

    started = world.package_started_with(source.id, "notes-server")
    assert started["argv"] == ["--serve"]
    assert started["env"]["NOTES_TOKEN"] == FAKE and started["env"]["MODE"] == "fast"
    assert started["env"]["ASKED_TOKEN"] == typed and "NOT_ASKED" not in started["env"]
    assert json.loads(crypto.decrypt(server.env)) == {"NOTES_TOKEN": FAKE, "MODE": "fast", "ASKED_TOKEN": typed}

    await _nothing_stored_holds(execution_db, FAKE, typed)
    assert FAKE not in caplog.text and typed not in caplog.text
    assert FAKE not in json.dumps(result)
    assert (await _scan(api))["servers"][0]["here"] is True


@pytest.mark.real_mcp
async def test_uvx_goes_the_same_way(api, home, execution_db, world):
    _codex(home, f'[mcp_servers.tools]\ncommand = "uvx"\nargs = ["tools-server"]\nenv = {{ TOOLS_TOKEN = "{FAKE}" }}\n')
    result = (await _add(api, await _scan(api), "codex:tools"))["codex:tools"]
    assert result["state"] == "on", result
    source, server = await _server_of(execution_db, result)
    assert (source.runtime, source.version) == ("uv", "1.2.3")
    assert source.lock_sha256 and server.command.endswith("venv/bin/tools-server")
    assert json.loads(crypto.decrypt(server.env)) == {"TOOLS_TOKEN": FAKE}
    assert world.wrapped[-1]["root"].endswith(source.id)
    await _nothing_stored_holds(execution_db, FAKE)


@pytest.mark.real_mcp
async def test_a_package_with_no_key_gets_no_network(api, home, execution_db, world):
    _claude(home, {"notes": {"command": "npx", "args": ["notes-server"]}})
    scan = await _scan(api)
    result = (await _add(api, scan, "claude_code:notes"))["claude_code:notes"]
    _, server = await _server_of(execution_db, result)
    assert _row(scan, "claude_code:notes")["network"] is False and server.sandbox["network"] is False


@pytest.mark.real_mcp
async def test_a_key_in_the_arguments_is_stored_encrypted_and_still_reaches_the_program(api, home, execution_db, world, caplog):
    caplog.set_level(logging.DEBUG)
    _claude(home, {"notes": {"command": "npx", "args": ["notes-server", f"--api-key={FAKE}", "--token", FAKE + "2",
                                                        f"--token={FAKE}3"]}})
    scan = await _scan(api)
    assert _row(scan, "claude_code:notes")["network"] is True
    result = (await _add(api, scan, "claude_code:notes"))["claude_code:notes"]
    assert result["state"] == "on", result
    source, server = await _server_of(execution_db, result)
    assert FAKE not in json.dumps(server.args) and FAKE not in json.dumps(source.candidate)
    assert all("${" in a for a in server.args[-4:] if a != "--token")
    assert set(json.loads(crypto.decrypt(server.secrets)).values()) == {FAKE, FAKE + "2", FAKE + "3"}
    assert world.package_started_with(source.id, "notes-server")["argv"] == [f"--api-key={FAKE}", "--token", FAKE + "2",
                                                                             f"--token={FAKE}3"]
    assert server.sandbox["network"] is True
    await _nothing_stored_holds(execution_db, FAKE)
    assert FAKE not in caplog.text


@pytest.mark.real_mcp
async def test_a_remote_is_added_as_written_off_the_one_click_list_with_its_keys_encrypted(api, home, execution_db, world, caplog):
    """`api_key=`, not `token=`: `server.main`'s record factory redacts that one word, whichever logger writes it."""
    caplog.set_level(logging.DEBUG)
    assert capability_allowlist.listed_remote(REMOTE, await capability_allowlist.current()) is not None
    _claude(home, {"vendor": {"type": "http", "url": f"{REMOTE}?team=core&api_key={FAKE}",
                              "headers": {"Authorization": "Bearer ${VENDOR_TOKEN}", "X-Team": FAKE + "2"}}})
    scan = await _scan(api)
    typed = "typed-value-for-this-test"
    result = (await _add(api, scan, "claude_code:vendor", keys={"claude_code:vendor": {"VENDOR_TOKEN": typed}}))["claude_code:vendor"]
    assert result["state"] == "on", result
    source, server = await _server_of(execution_db, result)
    assert source.runtime == "remote" and server.host_allowed is True and source.test["tools_pin"]
    assert FAKE not in server.url and "${" in server.url and FAKE not in json.dumps(source.candidate)
    assert list(json.loads(crypto.decrypt(server.secrets)).values()) == [FAKE]
    assert json.loads(crypto.decrypt(server.env)) == {"Authorization": f"Bearer {typed}", "X-Team": FAKE + "2"}
    sent = world.remote[0]
    assert str(sent.url) == f"{REMOTE}?team=core&api_key={FAKE}"
    assert sent.headers["authorization"] == f"Bearer {typed}" and sent.headers["x-team"] == FAKE + "2"
    await _nothing_stored_holds(execution_db, FAKE, typed)
    assert FAKE not in caplog.text and typed not in caplog.text


@pytest.mark.real_mcp
@pytest.mark.parametrize("url", [f"{REMOTE}?api_key={FAKE}", f"{REMOTE}/{FAKE}Aa0123456789"])
async def test_a_remote_that_answers_with_an_error_leaks_the_key_in_its_address_nowhere(api, home, execution_db, world, caplog, url):
    """httpx writes the whole URL into a status error. What a failed test stores and returns is Arslan's own line."""
    caplog.set_level(logging.DEBUG)
    world.remote_status = 500
    _claude(home, {"vendor": {"type": "http", "url": url, "headers": {"X-Key": FAKE + "2"}}})
    result = (await _add(api, await _scan(api), "claude_code:vendor"))["claude_code:vendor"]
    assert result["state"] == "failed", result
    assert "500" in result["detail"]        # it failed where the address could have been quoted
    assert FAKE not in json.dumps(result)
    await _nothing_stored_holds(execution_db, FAKE)
    assert FAKE not in caplog.text


@pytest.mark.real_mcp
async def test_codex_remote_keys_become_the_headers_codex_would_send(api, home, execution_db, world):
    _codex(home, f'[mcp_servers.api]\nurl = "{REMOTE}"\nbearer_token_env_var = "API_TOKEN"\n'
                 f'http_headers = {{ "X-Team" = "core" }}\nenv_http_headers = {{ "X-Key" = "API_KEY" }}\n')
    result = (await _add(api, await _scan(api), "codex:api",
                         keys={"codex:api": {"API_TOKEN": "the-token", "API_KEY": "the-key"}}))["codex:api"]
    assert result["state"] == "on", result
    sent = world.remote[0].headers
    assert (sent["authorization"], sent["x-key"], sent["x-team"]) == ("Bearer the-token", "the-key", "core")


@pytest.mark.real_mcp
async def test_a_remote_waiting_for_sign_in_says_so_and_stays_off(api, home, execution_db, world):
    world.sign_in = True
    _claude(home, {"vendor": {"type": "http", "url": REMOTE}})
    result = (await _add(api, await _scan(api), "claude_code:vendor"))["claude_code:vendor"]
    assert result["state"] == "needs_sign_in", result
    source, server = await _server_of(execution_db, result)
    assert source.state == "installed" and source.test["needs_sign_in"] is True
    assert server.host_allowed is False and server.state == "off"


@pytest.mark.real_mcp
async def test_only_what_is_ticked_is_added(api, home, execution_db, world):
    _claude(home, {"ticked": {"type": "http", "url": REMOTE}, "unticked": {"type": "http", "url": f"{REMOTE}2", "headers": {"X": FAKE}}})
    results = await _add(api, await _scan(api), "claude_code:ticked")
    assert list(results) == ["claude_code:ticked"]
    assert [server.url for server in await _rows(execution_db, MCPServer)] == [REMOTE]


@pytest.mark.real_mcp
async def test_one_failure_does_not_stop_the_others_and_each_reports_its_own(api, home, execution_db, world, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    world.fail_lock = "locks-badly"
    _claude(home, {"first": {"command": "npx", "args": ["first-server"]},
                   "crashes": {"command": "npx", "args": ["crash-server", "crash_with_stderr"]},
                   "no-lock": {"command": "npx", "args": ["locks-badly"]},
                   "throws": {"command": "npx", "args": ["throws-server"]},
                   "explodes": {"command": "npx", "args": ["explodes-server"]},
                   "program": {"command": "/opt/tools/mine"},
                   "last": {"type": "http", "url": REMOTE}})
    real_prepare = capability_install.prepare

    async def prepare(candidate):
        if candidate["name"] == "throws":
            raise RuntimeError(f"nobody planned for this {FAKE}")
        return await real_prepare(candidate)
    monkeypatch.setattr(capability_install, "prepare", prepare)
    real_install = capability_flow.install_mcp

    async def install_mcp(candidate, **kwargs):                # after the lock, so its staging folder has to go
        if candidate["name"] == "explodes":
            raise RuntimeError(f"nobody planned for this either {FAKE}")
        return await real_install(candidate, **kwargs)
    monkeypatch.setattr(capability_flow, "install_mcp", install_mcp)
    scan = await _scan(api)
    results = await _add(api, scan, *[row["id"] for row in scan["servers"]])
    states = {row_id.split(":")[1]: result["state"] for row_id, result in results.items()}
    assert states == {"first": "on", "crashes": "failed", "no-lock": "failed", "throws": "failed", "explodes": "failed",
                      "program": "refused", "last": "on"}
    assert results["claude_code:crashes"]["stage"] == "test"
    assert results["claude_code:no-lock"]["code"] == "step_failed"
    assert FAKE not in json.dumps(results) and FAKE not in caplog.text
    assert world.prepared() == []


@pytest.mark.real_mcp
@pytest.mark.parametrize("spec", [
    {"args": ["talks-server", "echo_then_crash"], "env": {"FAKE_SECRET": FAKE}},        # its env, which it prints
    {"args": ["talks-server", "echo_then_crash", f"--api-key={FAKE}"]}])                # its line, which it prints
async def test_a_program_printing_its_key_at_a_failed_start_leaks_it_nowhere(api, home, execution_db, world, caplog, spec):
    caplog.set_level(logging.DEBUG)
    _claude(home, {"talks": {"command": "npx", **spec}})
    result = (await _add(api, await _scan(api), "claude_code:talks"))["claude_code:talks"]
    assert result["state"] == "failed", result
    assert "started as" in result["detail"] and FAKE not in json.dumps(result)
    await _nothing_stored_holds(execution_db, FAKE)
    assert FAKE not in caplog.text


@pytest.mark.real_mcp
async def test_a_blocked_scan_keeps_nothing(api, home, execution_db, world, monkeypatch):
    monkeypatch.setattr(capability_scan, "scan_install",
                        lambda root: {"level": "blocked", "findings": [{"rule": "keychain_read", "level": "high"}]})
    _claude(home, {"notes": {"command": "npx", "args": ["notes-server"], "env": {"T": FAKE}}})
    result = (await _add(api, await _scan(api), "claude_code:notes"))["claude_code:notes"]
    assert result["state"] == "blocked"
    assert await _rows(execution_db, MCPServer) == []
    assert (await _scan(api))["servers"][0]["here"] is False


@pytest.mark.real_mcp
async def test_two_clicks_at_once_add_one_server(api, home, execution_db, world):
    _claude(home, {"vendor": {"type": "http", "url": REMOTE}})
    scan = await _scan(api)
    first, second = await asyncio.gather(_add(api, scan, "claude_code:vendor"), _add(api, scan, "claude_code:vendor"))
    assert sorted((first["claude_code:vendor"]["state"], second["claude_code:vendor"]["state"])) == ["here", "on"]
    assert len(await _rows(execution_db, MCPServer)) == 1


@pytest.mark.real_mcp
async def test_ticking_the_same_server_from_both_tools_adds_it_once(api, home, execution_db, world):
    _claude(home, {"vendor": {"type": "http", "url": REMOTE}})
    _codex(home, f'[mcp_servers.vendor]\nurl = "{REMOTE}"\n')
    results = await _add(api, await _scan(api), "claude_code:vendor", "codex:vendor")
    assert (results["claude_code:vendor"]["state"], results["codex:vendor"]["state"]) == ("on", "here")
    assert len(await _rows(execution_db, MCPServer)) == 1


@pytest.mark.real_mcp
async def test_neither_file_is_written_by_a_scan_or_an_add_or_a_removal(api, home, execution_db, world):
    _claude(home, {"vendor": {"type": "http", "url": REMOTE}}, other="kept")
    _codex(home, f'[mcp_servers.more]\nurl = "{REMOTE}2"\n')
    paths = [home / ".claude.json", home / ".codex" / "config.toml"]
    before = [(p.read_bytes(), os.stat(p).st_mtime_ns) for p in paths]
    result = (await _add(api, await _scan(api), "claude_code:vendor"))["claude_code:vendor"]
    assert result["state"] == "on", result
    await capability_install.remove(result["source_id"])
    assert (await _scan(api))["servers"][0]["here"] is False       # removal leaves it here to import again
    assert [(p.read_bytes(), os.stat(p).st_mtime_ns) for p in paths] == before


@pytest.mark.real_mcp
async def test_what_the_model_and_the_page_read_after_an_import_hold_no_key(api, home, execution_db, world, monkeypatch):
    monkeypatch.setattr(executors, "AsyncSessionLocal", execution_db)
    _claude(home, {"vendor": {"type": "http", "url": f"{REMOTE}?token={FAKE}", "headers": {"X-Key": FAKE + "2"}},
                   "notes": {"command": "npx", "args": ["notes-server", f"--api-key={FAKE}"], "env": {"T": FAKE + "3"}}})
    scan = await _scan(api)
    results = await _add(api, scan, "claude_code:vendor", "claude_code:notes")
    assert all(result["state"] == "on" for result in results.values()), results
    told = await executors.ListMyCapabilitiesExecutor().execute({})
    assert {"vendor", "notes"} <= {server["label"] for server in told["mcp"]}
    assert FAKE not in json.dumps(told, default=str)
    assert FAKE not in json.dumps(await capability_list._mcp_rows(), default=str)
    assert FAKE not in (await api.get("/api/v1/capability-sources")).text
    await _nothing_stored_holds(execution_db, FAKE)
