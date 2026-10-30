"""SEC1 (docs/plans/0164/CAPX-followups.md), the server half: a secret typed into a connection's address or
command arguments can move into an encrypted store. The stored address or argument then holds a `${NAME}`
placeholder, filled in when the connection starts (`runtime_dict`); the value is never stored in the clear,
never shown, and masked in every error. Nothing is moved without being asked (the UI's click is SEC1b)."""
import pytest

from server.db import session as db_session
from server.db.models import MCPServer
from server.services import connection_secrets as cs

URL = "https://mcp.notes.example/sse?token=tok_example_42&view=full"
KEY = "ak_" + "9f8e7d6c5b4a3210" + "fedcba98"           # fake; built at run time so no scanner reads it as one
ARGS = ["-y", "@acme/notes-mcp", "--api-key", KEY, "--port", "8080", "MODE=fast"]


def test_secret_looking_parts_are_found_and_nothing_else():
    found = cs.find("https://me:hunter2pass@mcp.example/x?token=tok_example_42&view=full&page=2",
                    ARGS + ["=".join(("SECRET" + "_KEY", "abc123" + "def456")), "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZg"])
    assert [(p["where"], p.get("at"), p.get("index"), p.get("key")) for p in found] == [
        ("url", "password", None, None), ("url", "query", None, "token"), ("arg", None, 3, "api-key"),
        ("arg", None, 7, "secret_key"), ("arg", None, 8, None)]
    assert not cs.find("https://mcp.example/sse?view=full&page=2", ["-y", "@acme/notes-mcp", "--port", "8080"])


def test_a_secret_word_is_matched_as_a_word_not_a_substring():
    """#536 review 5: `--max-tokens 1000` and eight more ordinary arguments were flagged."""
    ordinary = ["--max-tokens", "1000", "--token-limit", "50", "--keyboard", "us", "--session", "abc123",
                "--auth", "oauth", "TOKENS=5", "--keys-dir", "/tmp/k", "--monkey", "banana", "--api-key", "${NOTES_KEY}"]
    assert cs.find("https://mcp.example/sse?max_tokens=10&keyboard=us&auth=oauth", ordinary) == []
    for key in ("api_key", "apiKey", "X-Api-Key", "accessToken", "client-secret", "PRIVATE_KEY", "pwd", "sig"):
        assert cs.find(None, [f"--{key}", "v4lu3-not-a-word"]), key


def test_mcp_remote_urls_headers_user_names_and_paths_are_found():
    """#536 review 5: missed before."""
    args = ["-y", "mcp-remote", "https://mcp.example/sse?token=tok_example_42", "--header", "Authorization: Bearer " + KEY,
            "--header=X-Api-Key: " + KEY, "--header", "Authorization:${AUTH_HEADER}"]
    found = [(p["where"], p.get("index"), p.get("at"), p.get("key")) for p in cs.find(None, args)]
    assert found == [("arg", 2, "query", "token"), ("arg", 4, "header", "authorization"), ("arg", 5, "header", "x-api-key")]
    assert [p.get("at") for p in cs.find("https://" + KEY + "@git.example/x", [])] == ["user"]
    assert [p.get("at") for p in cs.find("https://actions.example/mcp/" + KEY + "/sse", [])] == ["path"]
    url, moved, values = cs.move(None, args, {"where": "arg", "index": 4, "at": "header", "key": "authorization"},
                                 "NOTES_AUTH", {})
    assert moved[4] == "Authorization: Bearer ${NOTES_AUTH}" and values == {"NOTES_AUTH": KEY}
    url, moved, values = cs.move(url, moved, {"where": "arg", "index": 2, "at": "query", "key": "token"}, "NOTES_TOKEN",
                                 values)
    assert cs.fill(url, moved, values) == (None, args)


@pytest.mark.parametrize("url", [
    "https://me%40corp:p%40ss%2Bw0rd@mcp.example/x?token=ab%2Bcd%26ef&view=a+b",
    "http://user:hunter2pass@[::1]:8080/mcp?token=tok_example_42",
    "http://user:hunter2pass@mcp.example:8o80/mcp",                               # a bad port
    "https://mcp.example/sse?token=tok_example_42&token=tok_example_43#frag",
])
def test_fill_gives_back_the_address_byte_for_byte_and_nothing_raises(url):
    """#536 review 2 and 3: percent-encoding, `%40` in a user name and IPv6 brackets were rewritten, and a bad
    port made `shown` raise."""
    parts = cs.find(url, [])
    assert parts
    moved, values = url, {}
    for n, part in enumerate(parts):
        moved, _, values = cs.move(moved, [], part, f"S{n}", values)
    assert cs.find(moved, []) == [] and cs.fill(moved, [], values) == (url, [])
    shown_url, _ = cs.shown(url, [])
    assert "●●●●" in shown_url and not set(values.values()) & set(shown_url.replace("●●●●", " ").split())


def test_a_moved_password_is_exactly_the_text_between_the_colon_and_the_at():
    url, _, values = cs.move("https://me%40corp:p%40ss@mcp.example/x", [], {"where": "url", "at": "password"}, "P", {})
    assert (url, values) == ("https://me%40corp:${P}@mcp.example/x", {"P": "p%40ss"})


def test_a_part_names_itself_from_the_connection_and_its_key():
    assert cs.suggest_name("Notes", {"where": "url", "at": "query", "key": "token"}) == "NOTES_TOKEN"
    assert cs.suggest_name("My \u202enotes!", {"where": "arg", "index": 3, "key": "api-key"}) == "MY_NOTES_API_KEY"
    assert cs.suggest_name("", {"where": "url", "at": "password"}) == "CONNECTION_PASSWORD"
    assert cs.suggest_name("Git", {"where": "url", "at": "user"}) == "GIT_USER"


def test_a_move_leaves_a_placeholder_and_fill_puts_the_value_back():
    url, args, values = cs.move(URL, ARGS, {"where": "url", "at": "query", "key": "token"}, "NOTES_TOKEN", {})
    assert url == "https://mcp.notes.example/sse?token=${NOTES_TOKEN}&view=full" and values == {"NOTES_TOKEN": "tok_example_42"}
    with pytest.raises(cs.NothingToMove, match="taken"):
        cs.move(url, args, {"where": "arg", "index": 3, "key": "api-key"}, "NOTES_TOKEN", values)  # a name in use
    url, args, values = cs.move(url, args, {"where": "arg", "index": 3, "key": "api-key"}, "NOTES_KEY", values)
    assert args[3] == "${NOTES_KEY}" and KEY not in str((url, args))
    assert cs.fill(url, args, values) == (URL, ARGS)
    assert cs.fill("https://x/${UNKNOWN}?a=${NOTES_TOKEN}", [], values) == ("https://x/${UNKNOWN}?a=tok_example_42", [])
    assert cs.fill("${A}", [], {"A": "${B}", "B": "x"}) == ("${B}", [])                 # a value is not filled again
    assert cs.missing("https://x/${UNKNOWN}?a=${NOTES_TOKEN}", ["${OTHER}"], values) == ["OTHER", "UNKNOWN"]
    with pytest.raises(cs.NothingToMove):
        cs.move(url, args, {"where": "url", "at": "query", "key": "token"}, "NOTES_TOKEN2", values)  # already moved
    with pytest.raises(cs.NothingToMove):
        cs.move(url, args, {"where": "url", "at": "query", "key": "view"}, "VIEW", values)          # not a secret


def test_the_shown_address_and_arguments_never_hold_a_secret():
    shown_url, shown_args = cs.shown("https://me:hunter2pass@mcp.example/x?token=tok_example_42&view=full", ARGS)
    assert "hunter2pass" not in shown_url and "tok_example_42" not in shown_url and "view=full" in shown_url
    assert KEY not in shown_args and "8080" in shown_args and "@acme/notes-mcp" in shown_args


async def test_a_stored_connection_moves_its_secret_and_still_starts_with_it(execution_db):
    """The stored row holds the placeholder and ciphertext only; what the session manager gets holds the value,
    and the masking that keeps it out of every error knows it."""
    from server.mcp.discovery import runtime_dict
    from server.mcp.supervisor import mask_for
    from server.services import mcp_service
    added = await mcp_service.add_server("Notes", "npx", ARGS, {}, transport="stdio")
    async with execution_db() as db:
        srv = await db.get(MCPServer, added["id"])
        srv.url = URL
        await db.commit()
    [row] = [row for row in await mcp_service.list_servers() if row["id"] == added["id"]]
    parts = row["secret_parts"]
    assert [(p["where"], p.get("at"), p.get("index"), p["name"]) for p in parts] == [
        ("url", "query", None, "NOTES_TOKEN"), ("arg", None, 3, "NOTES_API_KEY")]
    assert "●●●●" in row["url_shown"] and "tok_example_42" not in row["url_shown"] and KEY not in row["args_shown"]
    for part in parts:
        await mcp_service.move_secret(added["id"], part, part["name"])
    async with execution_db() as db:
        srv = await db.get(MCPServer, added["id"])
        stored = (srv.url, list(srv.args), srv.secrets)
    assert "tok_example_42" not in str(stored) and KEY not in str(stored)
    assert stored[0].endswith("token=${NOTES_TOKEN}&view=full") and stored[1][3] == "${NOTES_API_KEY}"
    runtime = runtime_dict(srv)
    assert (runtime["url"], runtime["args"]) == (URL, ARGS)
    assert "tok_example_42" not in mask_for(runtime, "401 at " + URL)
    assert KEY not in mask_for(runtime, "bad key ak_9f8e7d6c5b4a3210fedcba98")
    [view] = [row for row in await mcp_service.list_servers() if row["id"] == added["id"]]
    assert view["secret_parts"] == [] and view["secrets_missing"] == [] and "tok_example_42" not in str(view)


async def test_a_move_of_a_part_that_is_not_there_changes_nothing(execution_db):
    from server.services import mcp_service
    added = await mcp_service.add_server("Notes", "", [], {}, transport="http", url="https://mcp.notes.example/sse")
    with pytest.raises(cs.NothingToMove):
        await mcp_service.move_secret(added["id"], {"where": "url", "at": "query", "key": "token"}, "NOTES_TOKEN")
    async with execution_db() as db:
        srv = await db.get(MCPServer, added["id"])
    assert (srv.url, srv.secrets) == ("https://mcp.notes.example/sse", None)


async def test_migration_0081_adds_the_column_to_an_older_database_and_a_second_run_changes_nothing(tmp_path):
    """A new install has the column from the model; an upgrade gets it from 0081 (a database from before it)."""
    import sqlalchemy as sa

    from server.db.migrations import runner
    from server.db.migrations.versions import _0081_connection_secrets as m0081
    from server.services import storage_boot
    db = tmp_path / "s.db"

    async def boot():
        engine = db_session.build_engine(f"sqlite+aiosqlite:///{db}")
        try:
            await storage_boot.initialize(engine)
        finally:
            await engine.dispose()

    def columns(conn):
        return {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_servers)")}
    await boot()
    sync = sa.create_engine(f"sqlite:///{db}")
    try:
        with sync.begin() as conn:                                    # as a v0.1.63 database was
            conn.exec_driver_sql("ALTER TABLE mcp_servers DROP COLUMN secrets")
            conn.exec_driver_sql("DELETE FROM schema_version WHERE version = '0081'")
            assert "secrets" not in columns(conn)
        await boot()
        with sync.begin() as conn:
            assert "secrets" in columns(conn) and "0081" in runner.current_versions(conn)
            m0081.upgrade_sync(conn)                                 # a second run
            assert "secrets" in columns(conn)
    finally:
        sync.dispose()


async def test_the_route_moves_a_secret_and_refuses_what_is_not_there(execution_db, monkeypatch):
    import httpx
    from fastapi import FastAPI

    from server import auth
    from server.api.mcp import router
    from server.services import mcp_service
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-mcp-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    added = await mcp_service.add_server("Notes", "", [], {}, transport="http", url=URL)
    body = {"part": {"where": "url", "at": "query", "key": "token"}, "name": "NOTES_TOKEN"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-mcp-token"}) as client:
        moved = await client.post(f"/api/v1/mcp/servers/{added['id']}/secrets", json=body)
        assert moved.status_code == 200 and "tok_example_42" not in moved.text and moved.json()["secret_parts"] == []
        again = await client.post(f"/api/v1/mcp/servers/{added['id']}/secrets", json=body)
        assert again.status_code == 409
        missing = await client.post("/api/v1/mcp/servers/999/secrets", json=body)
        assert missing.status_code == 404
        listed = await client.get("/api/v1/mcp/servers")
        assert "tok_example_42" not in listed.text
        odd = await client.post(f"/api/v1/mcp/servers/{added['id']}/secrets",
                                json={"part": {"where": "url", "key": {"a": 1}}, "name": "X"})
        assert odd.status_code == 422                                        # #536 review §12: was a 500


async def test_a_connection_with_a_bad_port_is_added_and_listed(execution_db):
    """#536 review 2, the red case: the row was saved, then the add answered 500 and every list after it failed;
    finding never blocks (the user's D3)."""
    from server.services import mcp_service
    added = await mcp_service.add_server("Odd", "", [], {}, transport="http", url="http://user:hunter2pass@mcp.example:8o80/mcp")
    [row] = [row for row in await mcp_service.list_servers() if row["id"] == added["id"]]
    assert [p.get("at") for p in row["secret_parts"]] == ["password"] and "hunter2pass" not in row["url_shown"]


async def test_two_moves_at_once_keep_both_values(execution_db, monkeypatch):
    """#536 review 4: under forced interleaving both answered 200 and one placeholder had no stored value."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession

    from server.mcp.discovery import runtime_dict
    from server.services import mcp_service
    added = await mcp_service.add_server("Notes", "npx", ARGS, {}, transport="stdio")
    async with execution_db() as db:
        (await db.get(MCPServer, added["id"])).url = URL
        await db.commit()
    real_commit = AsyncSession.commit

    async def slow_commit(self):
        await asyncio.sleep(0.05)                                       # the other move reads meanwhile
        return await real_commit(self)
    monkeypatch.setattr(AsyncSession, "commit", slow_commit)
    restarts = []

    async def restart(server_id):
        restarts.append(server_id)
    monkeypatch.setattr(mcp_service, "restart_after_edit", restart)
    await asyncio.gather(
        mcp_service.move_secret(added["id"], {"where": "url", "at": "query", "key": "token"}, "NOTES_TOKEN"),
        mcp_service.move_secret(added["id"], {"where": "arg", "index": 3, "key": "api-key"}, "NOTES_KEY"))
    async with execution_db() as db:
        srv = await db.get(MCPServer, added["id"])
    runtime = runtime_dict(srv)
    assert (runtime["url"], runtime["args"]) == (URL, ARGS) and set(runtime["secrets"]) == {"NOTES_TOKEN", "NOTES_KEY"}
    assert restarts == [added["id"]] * 2                                 # each move restarts the connection


async def test_a_placeholder_with_no_stored_value_is_named(execution_db):
    from server.services import mcp_service
    added = await mcp_service.add_server("Notes", "", [], {}, transport="http", url="https://mcp.example/sse?token=${NOTES_TOKEN}")
    [row] = [row for row in await mcp_service.list_servers() if row["id"] == added["id"]]
    assert row["secrets_missing"] == ["NOTES_TOKEN"] and row["secret_parts"] == []


def test_moved_secrets_are_rewrapped_checked_and_read_at_boot(tmp_path):
    """#536 review 1: the rewrap re-encrypted `env` only, while the preflight said "compatible"; boot's inventory
    assumed one column per table."""
    import base64
    import sqlite3

    from server.crypto_material import keyring
    from server.services import crypto_boot, recovery_preflight, recovery_rewrap
    old, new, salt = "synthetic-backup-only", "synthetic-installation-only", bytes(range(16))
    active, candidate = tmp_path / "active", tmp_path / "candidate"
    active.mkdir()
    candidate.mkdir()
    (active / "arslan.db").write_bytes(b"original")
    env = keyring(old, salt).encrypt(b"env-value").decode()
    moved = keyring(old, salt).encrypt(b'{"NOTES_TOKEN": "tok_example_42"}').decode()
    with sqlite3.connect(candidate / "arslan.db") as db:
        db.executescript("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);"
                         "CREATE TABLE mcp_servers (id INTEGER PRIMARY KEY, env TEXT, secrets TEXT);")
        db.execute("INSERT INTO settings VALUES ('crypto_salt_b64', ?)", (base64.b64encode(salt).decode(),))
        db.execute("INSERT INTO mcp_servers VALUES (1, ?, ?)", (env, moved))
    assert recovery_preflight.check(candidate / "arslan.db", old) == {"status": "compatible", "checked": 2, "unreadable": 0}
    assert recovery_rewrap.rewrap_candidate(active, candidate, old, new)["credentials"] == 2
    with sqlite3.connect(candidate / "arslan.db") as db:
        env_after, moved_after = db.execute("SELECT env, secrets FROM mcp_servers").fetchone()

        class Connection:
            def exec_driver_sql(self, sql, parameters=()):
                return db.execute(sql, parameters)
        found = {(table, column) for table, column, *_ in crypto_boot._stored_ciphertext(Connection())}
    assert keyring(new, salt).decrypt(moved_after.encode()) == b'{"NOTES_TOKEN": "tok_example_42"}'
    assert keyring(new, salt).decrypt(env_after.encode()) == b"env-value"
    assert found == {("mcp_servers", "env"), ("mcp_servers", "secrets")}


def test_a_moved_value_is_masked_as_written_and_decoded():
    """A value moves as written (`p%40ss%2Bw0rd`); a server's error may echo it decoded (`p@ss+w0rd`)."""
    from server.mcp.supervisor import mask_for
    runtime = {"id": 1, "env": {}, "url": None, "args": ["--token=${P}"], "secrets": {"P": "p%40ss%2Bw0rd"}}
    masked = mask_for(runtime, "login failed for me with p@ss+w0rd (sent p%40ss%2Bw0rd)")
    assert "p@ss+w0rd" not in masked and "p%40ss%2Bw0rd" not in masked


def test_the_masking_fallback_keeps_the_moved_values():
    """A malformed address makes `secret_forms` raise; the supervisor's fallback still masks a moved value."""
    from server.mcp.supervisor import mask_for
    runtime = {"id": 1, "env": {}, "url": "http://[::1/mcp", "secrets": {"T": "tok_example_42"}}
    assert "tok_example_42" not in mask_for(runtime, "401: tok_example_42 was refused")
