"""0.1.55 §14: the Capabilities switches say exactly what the model is offered."""
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base

from server import auth
from server.api.capabilities import router
from server.services import capability_list, settings_service

# Every tool a switchable built-in row stands for, whatever its state.
SWITCHED_TOOLS = {
    "terminal": {"run_command"},
    "lan": {"scan_local_network"},
    "ssh": {"ssh_probe", "ssh_run", "list_nodes", "enroll_node"},
}


@pytest_asyncio.fixture
async def execution_db(tmp_path, monkeypatch):
    """The whole schema (settings, skills, MCP servers), not only the memory tables."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'capabilities.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    from server.registry import executors
    monkeypatch.setattr(executors, "AsyncSessionLocal", maker)   # imported by name there
    yield maker
    await engine.dispose()


@pytest.fixture
async def api(execution_db, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-capabilities-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-capabilities-token"}) as client:
        yield client


async def _set(execution_db, **values):
    async with execution_db() as db:
        await settings_service.update_settings(db, {k: v for k, v in values.items()})


async def _reads_home_folders(execution_db) -> bool:
    """Whether the Desktop/Documents/Downloads are readable, as the file tools resolve it."""
    from server.services.workspace_paths import green_roots, read_roots
    async with execution_db() as db:
        roots = read_roots(await settings_service.workspace_dir(db),
                           default_read=await settings_service.default_read_enabled(db))
    return set(green_roots()) <= set(roots)


async def _offered() -> set[str]:
    from server.orchestrator import arslan
    return {tool["key"] for tool in await arslan._arslan_tools()}


@pytest.mark.parametrize("values", [
    {"default_read_enabled": "true", "orchestrator_shell_enabled": "true", "lan_discovery_enabled": "false", "ssh_enabled": "false"},
    {"default_read_enabled": "false", "orchestrator_shell_enabled": "false", "lan_discovery_enabled": "true", "ssh_enabled": "true"},
])
async def test_every_row_matches_what_the_model_is_offered(execution_db, values):
    await _set(execution_db, **values)
    rows = {row["key"]: row for row in await capability_list.capabilities()}
    offered = await _offered()
    for row in rows.values():
        # Whatever a row claims, those tools are really offered…
        assert set(row["tools"]) <= offered, row["key"]
    for key, tools in SWITCHED_TOOLS.items():
        # …and a row that is off offers none of its tools; one that is on offers all.
        if rows[key]["state"] == "off":
            assert not tools & offered, key
        else:
            assert rows[key]["state"] == "on" and tools <= offered, key
    assert (rows["files"]["state"] == "on") == await _reads_home_folders(execution_db)
    assert rows["terminal"]["state"] == ("on" if values["orchestrator_shell_enabled"] == "true" else "off")
    assert rows["ssh"]["state"] == ("on" if values["ssh_enabled"] == "true" else "off")


async def test_files_off_stops_reading_home_folders_but_says_the_own_folder_stays(api, execution_db, tmp_path):
    await _set(execution_db, workspace_dir=str(tmp_path))
    assert (await api.put("/api/v1/capabilities/files", json={"on": False})).json()["state"] == "off"
    files = next(r for r in await capability_list.capabilities() if r["key"] == "files")
    assert files["detail"] == "own_folder_only" and files["switch"] == "setting"
    assert not await _reads_home_folders(execution_db)
    assert "read_file" in await _offered()          # still there, for the own folder only
    assert (await api.put("/api/v1/capabilities/files", json={"on": True})).json()["state"] == "on"
    assert await _reads_home_folders(execution_db)


async def test_web_without_a_key_is_one_step_away_and_says_where(execution_db):
    await _set(execution_db, search_provider="tavily")
    web = next(r for r in await capability_list.capabilities() if r["key"] == "web")
    assert web["state"] == "setup" and web["reason"] == "no-key" and web["fix"] == "open_settings:connections"
    # The tool itself stays offered and answers why, so the model can tell the user.
    from server.registry.executors import WebSearchExecutor
    result = await WebSearchExecutor().execute({"query": "anything"})
    assert result["ok"] is False and "no API key" in result["error"]


async def test_switching_a_setting_row_changes_the_offer(api, execution_db):
    await _set(execution_db, orchestrator_shell_enabled="true")
    assert "run_command" in await _offered()
    response = await api.put("/api/v1/capabilities/terminal", json={"on": False})
    assert response.status_code == 200 and response.json()["state"] == "off"
    assert "run_command" not in await _offered()
    await api.put("/api/v1/capabilities/terminal", json={"on": True})
    assert "run_command" in await _offered()


@pytest.mark.parametrize("key", sorted(SWITCHED_TOOLS))
async def test_each_setting_switch_moves_its_own_row_and_its_own_tools(api, execution_db, key):
    for on in (True, False, True):
        assert (await api.put(f"/api/v1/capabilities/{key}", json={"on": on})).json()["state"] == ("on" if on else "off")
        offered = await _offered()
        assert (SWITCHED_TOOLS[key] <= offered) if on else not (SWITCHED_TOOLS[key] & offered), (key, on)


async def test_a_skill_switched_off_leaves_the_index_and_cannot_be_read(api, execution_db):
    from server.db.models import SkillPack
    from server.orchestrator import arslan
    from server.registry.executors import ReadSkillExecutor
    async with execution_db() as db:
        db.add(SkillPack(key="tidy-notes", name="Tidy notes", category="writing", description="Tidy a note",
                         tier="safe", status="registered", body="# Tidy\nSteps."))
        await db.commit()
    assert "tidy-notes" in await arslan._skill_index()
    row = next(r for r in (await api.get("/api/v1/capabilities")).json() if r["key"] == "skill:tidy-notes")
    assert row["state"] == "on" and row["group"] == "methods"
    assert (await api.put("/api/v1/capabilities/skill:tidy-notes", json={"on": False})).json()["state"] == "off"
    assert "tidy-notes" not in await arslan._skill_index()
    result = await ReadSkillExecutor().execute({"key": "tidy-notes"})
    assert result["ok"] is False and "switched off" in result["error"]
    await api.put("/api/v1/capabilities/skill:tidy-notes", json={"on": True})
    assert (await ReadSkillExecutor().execute({"key": "tidy-notes"}))["ok"] is True


async def test_mcp_rows_follow_host_consent_and_name_a_missing_runtime(api, execution_db, monkeypatch):
    from server.db.models import MCPServer
    async with execution_db() as db:
        db.add_all([
            MCPServer(id=1, label="Docs", transport="http", command="", url="https://example.test/mcp",
                      status="connected", host_allowed=True),
            MCPServer(id=2, label="Files", transport="stdio", command="definitely-not-a-real-runtime-xyz",
                      args=[], status="registered"),
            MCPServer(id=3, label="Broken", transport="http", command="", url="https://example.test/b",
                      status="error", last_error="401 unauthorized"),
        ])
        await db.commit()
    rows = {r["key"]: r for r in (await api.get("/api/v1/capabilities")).json()}
    assert rows["mcp:1"]["state"] == "on" and rows["mcp:1"]["name"] == "Docs"
    assert rows["mcp:2"]["state"] == "na" and rows["mcp:2"]["reason"] == "runtime_missing"
    assert rows["mcp:2"]["detail"] == "definitely-not-a-real-runtime-xyz"
    assert rows["mcp:3"]["state"] == "setup" and rows["mcp:3"]["reason"] == "mcp_error"
    assert "401" in rows["mcp:3"]["detail"]
    assert (await api.put("/api/v1/capabilities/mcp:1", json={"on": False})).json()["state"] == "off"
    async with execution_db() as db:
        assert (await db.get(MCPServer, 1)).host_allowed is False


async def test_hands_switch_writes_the_hands_setting(api, monkeypatch):
    from server.services import hands_service
    seen = []
    monkeypatch.setattr(hands_service, "update_settings", lambda **kw: seen.append(kw))
    assert (await api.put("/api/v1/capabilities/hands", json={"on": False})).status_code == 200
    assert seen == [{"enabled": False}]


async def test_rows_that_have_no_switch_refuse_one(api):
    for key in ("charts", "web", "schedule", "mcp:999", "skill:nope", "anything"):
        response = await api.put(f"/api/v1/capabilities/{key}", json={"on": False})
        assert response.status_code == 409, key
    assert (await api.get("/api/v1/capabilities", headers={"Authorization": "Bearer wrong"})).status_code == 401


async def test_groups_are_the_four_the_page_draws(api):
    rows = (await api.get("/api/v1/capabilities")).json()
    assert {r["group"] for r in rows} <= set(capability_list.GROUPS)
    assert {r["state"] for r in rows} <= {"on", "off", "setup", "na"}
