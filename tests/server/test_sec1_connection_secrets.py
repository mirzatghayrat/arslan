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
    assert [(p["where"], p.get("index", p.get("key"))) for p in found] == [
        ("password", None), ("query", "token"), ("arg", 3), ("arg", 7), ("arg", 8)]
    assert not cs.find("https://mcp.example/sse?view=full&page=2", ["-y", "@acme/notes-mcp", "--port", "8080"])


def test_a_part_names_itself_from_the_connection_and_its_key():
    assert cs.suggest_name("Notes", {"where": "query", "key": "token"}) == "NOTES_TOKEN"
    assert cs.suggest_name("My \u202enotes!", {"where": "arg", "index": 3, "key": "api-key"}) == "MY_NOTES_API_KEY"
    assert cs.suggest_name("", {"where": "password"}) == "CONNECTION_PASSWORD"


def test_a_move_leaves_a_placeholder_and_fill_puts_the_value_back():
    url, args, values = cs.move(URL, ARGS, {"where": "query", "key": "token"}, "NOTES_TOKEN", {})
    assert url == "https://mcp.notes.example/sse?token=${NOTES_TOKEN}&view=full" and values == {"NOTES_TOKEN": "tok_example_42"}
    url, args, values = cs.move(url, args, {"where": "arg", "index": 3}, "NOTES_KEY", values)
    assert args[3] == "${NOTES_KEY}" and KEY not in str((url, args))
    assert cs.fill(url, args, values) == (URL, ARGS)
    assert cs.fill("https://x/${UNKNOWN}?a=${NOTES_TOKEN}", [], values) == ("https://x/${UNKNOWN}?a=tok_example_42", [])
    with pytest.raises(cs.NothingToMove):
        cs.move(url, args, {"where": "query", "key": "token"}, "NOTES_TOKEN", values)        # already moved
    with pytest.raises(cs.NothingToMove):
        cs.move(url, args, {"where": "query", "key": "view"}, "VIEW", values)               # not a secret


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
    parts = (await mcp_service.get_server(added["id"]))["secret_parts"]
    assert [(p["where"], p.get("index", p.get("key")), p["name"]) for p in parts] == [
        ("query", "token", "NOTES_TOKEN"), ("arg", 3, "NOTES_API_KEY")]
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
    view = await mcp_service.get_server(added["id"])
    assert view["secret_parts"] == [] and "tok_example_42" not in str(view)


async def test_a_move_of_a_part_that_is_not_there_changes_nothing(execution_db):
    from server.services import mcp_service
    added = await mcp_service.add_server("Notes", "", [], {}, transport="http", url="https://mcp.notes.example/sse")
    with pytest.raises(cs.NothingToMove):
        await mcp_service.move_secret(added["id"], {"where": "query", "key": "token"}, "NOTES_TOKEN")
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
    body = {"part": {"where": "query", "key": "token"}, "name": "NOTES_TOKEN"}
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
