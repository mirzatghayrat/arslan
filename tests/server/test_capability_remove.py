"""CAP3a-1 (v0.1.64): each Capabilities row says its section (built-in / skills / connections), where it came
from, whether it can be deleted and when it was last used; `DELETE /capabilities/{key}` deletes only what
Arslan installed or wrote or the user added by hand, and refuses the rest on the server, not only by hiding
the button (the CAP card: the delete button is security surface)."""
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from server import auth, config
from server.api.capabilities import router
from server.db.models import CapabilitySource, MCPServer, Run, RunStep, SkillPack


@pytest.fixture
async def api(execution_db, monkeypatch, tmp_path):
    from server.registry import executors
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-capabilities-token")
    monkeypatch.setattr(executors, "AsyncSessionLocal", execution_db)      # imported by name there
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "data").mkdir()
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-capabilities-token"}) as client:
        yield client


def _pack(key: str, category: str, **extra) -> SkillPack:
    return SkillPack(key=key, name=key, category=category, description="d", tier="safe", status="registered",
                     body="## Trigger\nx", **extra)


async def _seed(execution_db, tmp_path) -> None:
    """A built-in skill, one of each kind the user has, a hand-added and an installed connection."""
    (tmp_path / "data" / "skill_scripts" / "csv-tidy").mkdir(parents=True)
    (tmp_path / "data" / "skill_scripts" / "csv-tidy" / "run.py").write_text("print('hi')\n")
    (tmp_path / "data" / "capabilities" / "m1").mkdir(parents=True)
    async with execution_db() as db:
        db.add_all([
            _pack("designed-html-report", "creative"),                   # planted by the seeder
            _pack("csv-tidy", "imported"),                               # pasted a link (skill_import)
            _pack("xlsx", "productivity", source_id="sk1"),              # installed from a card
            _pack("weekly-report", "authored"),                          # the save card
            _pack("page-notes", "authored-outside"),                     # the save card, after a page
            _pack("gh-acme-notes", "general"),                           # Discover, before CAP1a
            CapabilitySource(id="sk1", kind="skill", name="xlsx", candidate_id="c", needs={}, grants={},
                             state="installed", skill_key="xlsx", created_at=datetime(2026, 10, 1)),
            MCPServer(id=1, label="github", command="", url="https://mcp.example.test/", transport="http", host_allowed=True,
                      status="registered"),
            MCPServer(id=2, label="excel", command="npx", transport="stdio", host_allowed=False, state="off",
                      status="registered", sandbox={"folders": []}),
            CapabilitySource(id="m1", kind="mcp", name="excel", candidate_id="c", needs={}, grants={},
                             state="installed", mcp_server_id=2, created_at=datetime(2026, 10, 1)),
        ])
        await db.commit()


async def _rows(api) -> dict[str, dict]:
    response = await api.get("/api/v1/capabilities")
    assert response.status_code == 200
    return {row["key"]: row for row in response.json()}


async def test_each_row_says_its_section_its_origin_and_whether_it_can_be_deleted(api, execution_db, tmp_path):
    await _seed(execution_db, tmp_path)
    rows = await _rows(api)
    seen = {key: (rows[key]["section"], rows[key]["origin"], rows[key]["deletable"]) for key in (
        "terminal", "files", "skill:designed-html-report", "skill:csv-tidy", "skill:xlsx", "skill:weekly-report",
        "skill:page-notes", "skill:gh-acme-notes", "mcp:1", "mcp:2")}
    assert seen == {
        "terminal": ("builtin", "builtin", False),
        "files": ("builtin", "builtin", False),
        "skill:designed-html-report": ("skills", "builtin", False),
        "skill:csv-tidy": ("skills", "installed", True),
        "skill:xlsx": ("skills", "installed", True),
        "skill:weekly-report": ("skills", "authored", True),
        "skill:page-notes": ("skills", "authored", True),
        "skill:gh-acme-notes": ("skills", "installed", True),
        "mcp:1": ("connections", "manual", True),
        "mcp:2": ("connections", "installed", True),
    }
    assert {row["section"] for row in rows.values()} <= {"builtin", "skills", "connections"}


async def test_the_server_refuses_to_delete_whatever_a_row_says_cannot_be_deleted(api, execution_db, tmp_path):
    """Every row the page shows without a delete button is refused by the server too, and stays."""
    await _seed(execution_db, tmp_path)
    kept = [key for key, row in (await _rows(api)).items() if not row["deletable"]]
    assert {"terminal", "files", "skill:designed-html-report"} <= set(kept)          # not vacuous
    for key in kept:
        response = await api.delete(f"/api/v1/capabilities/{key}")
        assert (response.status_code, response.json()["detail"]) == (409, {"code": "not_removable"}), key
    assert set(kept) <= set(await _rows(api))
    async with execution_db() as db:
        assert await db.get(SkillPack, "designed-html-report") is not None


@pytest.mark.parametrize("key", ["csv-tidy", "weekly-report", "page-notes", "gh-acme-notes"])
async def test_a_skill_the_user_has_is_deleted_and_its_files_go_to_the_trash(api, execution_db, tmp_path, key):
    await _seed(execution_db, tmp_path)
    response = await api.delete(f"/api/v1/capabilities/skill:{key}")
    assert (response.status_code, response.json()) == (200, {"ok": True})
    async with execution_db() as db:
        assert await db.get(SkillPack, key) is None
    assert f"skill:{key}" not in await _rows(api)
    if key == "csv-tidy":
        assert not (tmp_path / "data" / "skill_scripts" / "csv-tidy").exists()
        assert (tmp_path / "home" / ".Trash" / "Arslan capability csv-tidy" / "run.py").is_file()


async def test_an_installed_skill_is_deleted_and_its_source_marked_removed(api, execution_db, tmp_path):
    await _seed(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capabilities/skill:xlsx")).status_code == 200
    async with execution_db() as db:
        assert await db.get(SkillPack, "xlsx") is None
        assert (await db.get(CapabilitySource, "sk1")).state == "removed"


async def test_a_connection_added_by_hand_is_deleted(api, execution_db, tmp_path):
    await _seed(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capabilities/mcp:1")).status_code == 200
    async with execution_db() as db:
        assert await db.get(MCPServer, 1) is None
        assert await db.get(MCPServer, 2) is not None


async def test_an_installed_connection_is_removed_with_its_folder(api, execution_db, tmp_path):
    await _seed(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capabilities/mcp:2")).status_code == 200
    async with execution_db() as db:
        assert await db.get(MCPServer, 2) is None
        assert (await db.get(CapabilitySource, "m1")).state == "removed"
    assert (tmp_path / "home" / ".Trash" / "Arslan capability m1").is_dir()


@pytest.mark.parametrize("key", ["skill:nope", "mcp:99"])
async def test_deleting_what_is_not_there_is_not_found(api, execution_db, tmp_path, key):
    await _seed(execution_db, tmp_path)
    response = await api.delete(f"/api/v1/capabilities/{key}")
    assert (response.status_code, response.json()["detail"]) == (404, {"code": "not_found"})


@pytest.mark.parametrize("key", ["mcp:abc", "nonsense", "skill:"])
async def test_a_key_that_names_nothing_deletable_is_refused(api, execution_db, tmp_path, key):
    await _seed(execution_db, tmp_path)
    response = await api.delete(f"/api/v1/capabilities/{key}")
    assert (response.status_code, response.json()["detail"]) == (409, {"code": "not_removable"})


async def _steps(execution_db, *calls) -> None:
    async with execution_db() as db:
        run = Run(conversation_id="c1", user_message="x", started_at=datetime(2026, 10, 1))
        db.add(run)
        await db.flush()
        for seq, (tool, when, args) in enumerate(calls):
            db.add(RunStep(run_id=run.id, seq=seq, kind="tool_call", ref={"tool": tool, "ok": True},
                           detail={"args_summary": args, "summary": ""}, started_at=when, ended_at=when))
        db.add(RunStep(run_id=run.id, seq=99, kind="route", ref={"tool": "run_command"}, detail={},
                       started_at=datetime(2026, 10, 29)))                       # not a tool call
        await db.commit()


async def test_last_used_comes_from_the_run_records(api, execution_db, tmp_path):
    """The CAP card: from the existing run records, no new column; nothing found reads as never used."""
    await _seed(execution_db, tmp_path)
    await _steps(
        execution_db,
        ("run_command", datetime(2026, 10, 20, 9), '{"command": "ls"}'),
        ("run_command", datetime(2026, 10, 25, 9), '{"command": "pwd"}'),
        ("read_skill", datetime(2026, 10, 26, 9), '{"section": "Steps", "key": "weekly-report"}'),
        ("read_skill", datetime(2026, 10, 27, 9), '{"key": "weekly-report-2"}'),       # another skill
        ("mcp_1__search_issues", datetime(2026, 10, 27, 9), "{}"),
        ("mcp_11__other", datetime(2026, 10, 28, 9), "{}"),                         # server 11, not 1
    )
    rows = await _rows(api)
    assert rows["terminal"]["last_used"] == "2026-10-25T09:00:00Z"
    assert rows["skill:weekly-report"]["last_used"] == "2026-10-26T09:00:00Z"
    assert rows["mcp:1"]["last_used"] == "2026-10-27T09:00:00Z"
    assert rows["mcp:2"]["last_used"] is None and rows["skill:csv-tidy"]["last_used"] is None


async def test_a_switched_off_row_still_says_when_it_was_last_used(api, execution_db, tmp_path):
    """Its tools leave the row while it is off; when it was last used does not."""
    await _seed(execution_db, tmp_path)
    await _steps(execution_db, ("run_command", datetime(2026, 10, 25, 9), '{"command": "ls"}'))
    assert (await api.put("/api/v1/capabilities/terminal", json={"on": False})).status_code == 200
    terminal = (await _rows(api))["terminal"]
    assert terminal["state"] == "off" and terminal["tools"] == [] and terminal["last_used"] == "2026-10-25T09:00:00Z"


async def test_installed_rows_carry_their_source_and_others_none(api, execution_db, tmp_path):
    """CAP3a-2: the details sheet opens an installed capability's dossier by its source."""
    await _seed(execution_db, tmp_path)
    rows = await _rows(api)
    assert (rows["skill:xlsx"]["source_id"], rows["mcp:2"]["source_id"]) == ("sk1", "m1")
    assert {rows[key]["source_id"] for key in ("skill:csv-tidy", "skill:weekly-report", "mcp:1", "terminal")} == {None}
    assert not {"group", "source"} & set(rows["terminal"])                     # the old fields are gone


async def test_the_professional_methods_sit_with_the_skills_built_in_with_their_version(api, execution_db, tmp_path):
    """CAP3a-2 (the CAP card, with SUB): methods are skills on the page; not switched or deleted here; last used
    is the newest helper a task ran with one."""
    from server.services import professional_methods
    await _seed(execution_db, tmp_path)
    async with execution_db() as db:
        await professional_methods.revise(db, "research", 1, "Research, my way", "Cite every claim.")
        await db.commit()
    await _used_method(execution_db, "research", datetime(2026, 10, 27, 9))
    rows = await _rows(api)
    methods = {key: row for key, row in rows.items() if key.startswith("method:")}
    assert set(methods) == {f"method:{key}" for key in professional_methods.DEFAULTS}
    research = methods["method:research"]
    assert (research["section"], research["origin"], research["deletable"], research["switch"], research["state"]) \
        == ("skills", "builtin", False, None, "on")
    assert (research["revision"], research["name"], research["last_used"]) == (2, "Research, my way", "2026-10-27T09:00:00Z")
    unrevised = next(row for key, row in methods.items() if key != "method:research")
    assert (unrevised["revision"], unrevised["name"], unrevised["last_used"]) == (1, None, None)
    response = await api.delete("/api/v1/capabilities/method:research")
    assert (response.status_code, response.json()["detail"]) == (409, {"code": "not_removable"})


async def _used_method(execution_db, key: str, when: datetime) -> None:
    """A helper a task ran with the method. Only its method and time matter here, so the task and attempt it
    points at are not made (foreign keys off for this one write)."""
    from server.db.worker_models import TaskWorker
    async with execution_db() as db:
        await (await db.connection()).exec_driver_sql("PRAGMA foreign_keys=OFF")
        db.add(TaskWorker(id="w1", task_id="t1", attempt_id="a1", spec_revision=1, method_key=key, method_revision=2,
                          fingerprint="f", brief={}, status="completed", created_at=when))
        await db.commit()
