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
    """A skill whose name is not its key (#499 review: the scripts folder and the Trash go by key)."""
    return SkillPack(key=key, name=key.replace("-", " ").title(), category=category, description="d", tier="safe",
                     status="registered", body="## Trigger\nx", **extra)


SCRIPTS = ("csv-tidy", "xlsx", "deck", "designed-html-report")        # skills with a scripts folder
ADDED = datetime(2026, 9, 1)                                           # when the connections were added


async def _seed(execution_db, tmp_path) -> None:
    """A built-in skill, one of each kind the user has, two hand-added and an installed connection."""
    for key in SCRIPTS:
        (tmp_path / "data" / "skill_scripts" / key).mkdir(parents=True)
        (tmp_path / "data" / "skill_scripts" / key / "run.py").write_text("print('hi')\n")
    (tmp_path / "data" / "capabilities" / "m1").mkdir(parents=True)
    async with execution_db() as db:
        db.add_all([
            _pack("designed-html-report", "creative"),                   # planted by the seeder
            _pack("csv-tidy", "imported"),                               # pasted a link (skill_import)
            _pack("xlsx", "productivity", source_id="sk1"),              # installed from a card
            _pack("deck", "productivity", source_id="sk2"),              # installed from a card too
            _pack("weekly-report", "authored"),                          # the save card
            _pack("page-notes", "authored-outside"),                     # the save card, after a page
            _pack("gh-acme-notes", "general"),                           # Discover, before CAP1a
            CapabilitySource(id="sk1", kind="skill", name="xlsx", candidate_id="c", needs={}, grants={},
                             state="installed", skill_key="xlsx", created_at=datetime(2026, 10, 1)),
            CapabilitySource(id="sk2", kind="skill", name="deck", candidate_id="c", needs={}, grants={},
                             state="installed", skill_key="deck", created_at=datetime(2026, 10, 1)),
            MCPServer(id=1, label="github", command="", url="https://mcp.example.test/", transport="http", host_allowed=True,
                      status="registered", created_at=ADDED),
            MCPServer(id=2, label="excel", command="npx", transport="stdio", host_allowed=False, state="off",
                      status="registered", sandbox={"folders": []}, created_at=ADDED),
            MCPServer(id=3, label="notes", command="", url="https://notes.example.test/", transport="http",
                      host_allowed=True, status="registered", created_at=ADDED),
            CapabilitySource(id="m1", kind="mcp", name="excel", candidate_id="c", needs={}, grants={},
                             state="installed", mcp_server_id=2, created_at=datetime(2026, 10, 1)),
        ])
        await db.commit()


async def _state(execution_db, tmp_path) -> dict:
    """Everything a delete could reach: skills, servers, capability sources and the scripts folders."""
    from sqlalchemy import select
    async with execution_db() as db:
        skills = set((await db.execute(select(SkillPack.key))).scalars())
        servers = set((await db.execute(select(MCPServer.id))).scalars())
        sources = dict((await db.execute(select(CapabilitySource.id, CapabilitySource.state))).all())
    folder = tmp_path / "data" / "skill_scripts"
    return {"skills": skills, "servers": servers, "sources": sources,
            "scripts": {p.name for p in folder.iterdir()} if folder.is_dir() else set()}


def _without(state: dict, *, skill: str | None = None, server: int | None = None, source: str | None = None) -> dict:
    """`state` with one thing deleted, and nothing else touched."""
    return {"skills": state["skills"] - {skill}, "servers": state["servers"] - {server},
            "sources": {**state["sources"], **({source: "removed"} if source else {})},
            "scripts": state["scripts"] - {skill}}


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
    """Every row the page shows without a delete button is refused by the server too, and nothing changes: not
    the row, not a built-in skill's scripts folder (#499 review: nothing is moved before the check)."""
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    kept = [key for key, row in (await _rows(api)).items() if not row["deletable"]]
    assert {"terminal", "files", "skill:designed-html-report"} <= set(kept)          # not vacuous
    for key in kept:
        response = await api.delete(f"/api/v1/capabilities/{key}")
        assert (response.status_code, response.json()["detail"]) == (409, {"code": "not_removable"}), key
    assert set(kept) <= set(await _rows(api))
    assert await _state(execution_db, tmp_path) == before
    assert (tmp_path / "data" / "skill_scripts" / "designed-html-report" / "run.py").is_file()


async def test_what_the_page_may_delete_is_what_d7_never_retires(api, execution_db, tmp_path):
    """#499 review F1: the page's mark agrees with D7 (seeder._USERS_SKILL): what the seeder never retires is
    not built in here, and what it may retire is. A skill promoted from Skill Forge before CAP2a reads as the
    user's because migration 0077 (CAP2b, merged into this branch) marked it. "gh-" rows are the user's by their
    key: no seed or retired key is one (test_no_seed_skill_has_a_gh_key)."""
    from sqlalchemy import select

    from server.registry import seeder
    await _seed(execution_db, tmp_path)
    async with execution_db() as db:
        everyone = set((await db.execute(select(SkillPack.key))).scalars())
        users = set((await db.execute(select(SkillPack.key).where(seeder._USERS_SKILL))).scalars())
    rows = await _rows(api)
    assert users and everyone - users                                               # both kinds present
    for key in everyone:
        assert (rows[f"skill:{key}"]["origin"] != "builtin") == (key in users or key.startswith("gh-")), key
        assert rows[f"skill:{key}"]["deletable"] == (key in users or key.startswith("gh-")), key


def test_no_seed_skill_has_a_gh_key():
    """A "gh-" key reads as installed and can be deleted, so no skill the seeder plants or retires may have one."""
    from server.registry import seed_catalog, seeder
    keys = [key for key, *_ in seed_catalog.SKILLS] + list(seeder.RETIRED_SKILL_KEYS)
    assert keys and not [key for key in keys if key.startswith("gh-")]


@pytest.mark.parametrize("key", ["csv-tidy", "weekly-report", "page-notes", "gh-acme-notes"])
async def test_a_skill_the_user_has_is_deleted_and_its_files_go_to_the_trash(api, execution_db, tmp_path, key):
    """Only that skill and its own scripts folder (by key, not by name); every other skill, source, server and
    folder stays (#499 review F2)."""
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    response = await api.delete(f"/api/v1/capabilities/skill:{key}")
    assert (response.status_code, response.json()) == (200, {"ok": True})
    assert await _state(execution_db, tmp_path) == _without(before, skill=key)
    assert f"skill:{key}" not in await _rows(api)
    if key == "csv-tidy":
        assert (tmp_path / "home" / ".Trash" / "Arslan capability csv-tidy" / "run.py").is_file()


async def test_an_installed_skill_is_deleted_and_its_source_marked_removed(api, execution_db, tmp_path):
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capabilities/skill:xlsx")).status_code == 200
    assert await _state(execution_db, tmp_path) == _without(before, skill="xlsx", source="sk1")
    assert (tmp_path / "home" / ".Trash" / "Arslan capability xlsx" / "run.py").is_file()


async def test_a_connection_added_by_hand_is_deleted(api, execution_db, tmp_path):
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capabilities/mcp:1")).status_code == 200
    assert await _state(execution_db, tmp_path) == _without(before, server=1)


async def test_an_installed_connection_is_removed_with_its_folder(api, execution_db, tmp_path):
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capabilities/mcp:2")).status_code == 200
    assert await _state(execution_db, tmp_path) == _without(before, server=2, source="m1")
    assert (tmp_path / "home" / ".Trash" / "Arslan capability m1").is_dir()


async def test_a_skill_key_that_is_not_a_plain_key_is_refused_before_anything_is_read(api, execution_db, tmp_path):
    """#499 review F3: `{key:path}` lets "/" through, and the key names the scripts folder. Not reachable today
    (every writer makes [a-z0-9-] keys), but a stored "../victim" must never move data/victim."""
    from server.services import capability_list
    await _seed(execution_db, tmp_path)
    (tmp_path / "data" / "victim").mkdir()
    async with execution_db() as db:
        db.add(_pack("../victim", "imported"))
        await db.commit()
    with pytest.raises(capability_list.NotRemovable):
        await capability_list.remove("skill:../victim")
    assert (tmp_path / "data" / "victim").is_dir()
    for key in ("skill:a/b", "skill:Notion", "skill:a_b"):
        response = await api.delete(f"/api/v1/capabilities/{key}")
        assert (response.status_code, response.json()["detail"]) == (409, {"code": "not_removable"}), key


async def test_the_dossier_never_moves_a_folder_outside_the_scripts_folder(execution_db, monkeypatch, tmp_path):
    """#499 review F3, the same join in the dossier's own removal."""
    from server.services import capability_dossier
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "data" / "victim").mkdir(parents=True)
    (tmp_path / "data" / "skill_scripts").mkdir()                    # so "../victim" resolves
    async with execution_db() as db:
        db.add(CapabilitySource(id="bad", kind="skill", name="x", candidate_id="c", needs={}, grants={},
                                state="installed", skill_key="../victim", created_at=datetime(2026, 10, 1)))
        await db.commit()
    await capability_dossier.remove("bad")
    assert (tmp_path / "data" / "victim").is_dir()


async def test_a_failed_move_to_the_trash_keeps_the_skill(api, execution_db, monkeypatch, tmp_path):
    """#499 review F4: the files go to the Trash before the row goes, so a failed move leaves the skill whole,
    never a row-less scripts folder the next skill of that key would pick up."""
    from server.services import capability_install, capability_list

    def stuck(path, prefix="Arslan capability"):
        raise OSError("Trash not writable")
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    monkeypatch.setattr(capability_install, "to_trash", stuck)
    with pytest.raises(OSError):
        await capability_list.remove("skill:csv-tidy")
    assert await _state(execution_db, tmp_path) == before


@pytest.mark.parametrize("key", ["mcp:١", "mcp:²"])
async def test_a_server_number_in_other_digits_is_refused(api, execution_db, tmp_path, key):
    """#499 review nit: str.isdigit() takes "١" (Arabic-Indic one, aliasing server 1) and "²"."""
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    deleted = await api.delete(f"/api/v1/capabilities/{key}")
    assert (deleted.status_code, deleted.json()["detail"]) == (409, {"code": "not_removable"})
    switched = await api.put(f"/api/v1/capabilities/{key}", json={"on": False})
    assert (switched.status_code, switched.json()["detail"]) == (409, {"code": "not_switchable"})
    assert await _state(execution_db, tmp_path) == before


async def test_a_connection_says_how_it_is_reached_and_others_do_not(api, execution_db, tmp_path):
    """#500 recheck: the page's search finds a connection by its command and arguments, or its address."""
    await _seed(execution_db, tmp_path)
    rows = await _rows(api)
    assert (rows["mcp:1"]["reach"], rows["mcp:2"]["reach"]) == ("https://mcp.example.test", "npx")
    assert rows["terminal"]["reach"] is None and rows["skill:csv-tidy"]["reach"] is None


async def test_reach_never_carries_a_secret(api, execution_db, tmp_path):
    """#500 rechecks: `reach` is only searched, never shown, so it keeps only what is allowed: the command's name,
    package-like arguments (lowercase, with a "/" or naming "mcp") and the address's scheme, host and port. Values
    after a flag are written here to look like packages, so only the flag rule can drop them."""
    import json

    from server import crypto
    flagged = ["--token", "mcp-alpha", "--access-token", "mcp-bravo", "--api_key", "mcp-charlie", "-t", "mcp-delta",
               "-HAuthorization: Bearer echo", "--header", "mcp-foxtrot", "=".join(("API_KEY", "mcp-golf")),
               "--secret", "--header", "mcp-papa"]                # a flag is never the value of the one before
    loose = ["Authorization: Bearer hotel", "Bearer", "india", "someone:juliet@host", "postgresql://u:kilo@localhost/db",
             "--port=8080", "@acme/mcp-tool",                # a flag with its value inline leaves the next alone
             "mcp-envsecret"]                                # package-shaped, but the server's own secret
    async with execution_db() as db:
        db.add_all([
            MCPServer(id=7, label="remote", command="", transport="http", host_allowed=True, status="registered",
                      url="https://someone:lima1@mcp.example.test:8443/api/mcp/s/mikekey/mcp?key=novq&v=2#oscar",
                      created_at=ADDED),
            MCPServer(id=8, label="local", command="/opt/tools/bin/npx", transport="stdio", host_allowed=True,
                      status="registered", args=["-y", "@playwright/mcp@latest", *flagged, *loose, "some-mcp"],
                      env=crypto.encrypt(json.dumps({"TOKEN": "mcp-envsecret"})), created_at=ADDED),
        ])
        await db.commit()
    rows = await _rows(api)
    assert rows["mcp:7"]["reach"] == "https://mcp.example.test:8443"
    assert rows["mcp:8"]["reach"] == "npx @playwright/mcp@latest @acme/mcp-tool **** some-mcp"
    for secret in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet",
                   "kilo", "lima1", "mikekey", "novq", "oscar", "papa", "envsecret", "8080", "/opt/tools"):
        assert secret not in rows["mcp:7"]["reach"] + rows["mcp:8"]["reach"], secret


def test_a_connection_is_deleted_only_through_the_capabilities_list():
    """#500 recheck: DELETE /mcp/servers/{id} skipped an installed connection's removal (no Trash, the source left
    "installed") and had no caller left; DELETE /capabilities/mcp:<id> is the one way."""
    from server.api import mcp as mcp_api
    assert not [route for route in mcp_api.router.routes if "DELETE" in getattr(route, "methods", set())]


async def test_a_row_the_server_would_refuse_offers_no_delete_whatever_its_origin(api, execution_db, tmp_path):
    """#500 review F3: deleting also needs a plain key, so the page's flag says so too; nothing writes such a key
    today."""
    async with execution_db() as db:
        db.add(_pack("odd_key", "imported"))
        await db.commit()
    row = (await _rows(api))["skill:odd_key"]
    assert (row["origin"], row["deletable"]) == ("installed", False)
    response = await api.delete("/api/v1/capabilities/skill:odd_key")
    assert (response.status_code, response.json()["detail"]) == (409, {"code": "not_removable"})


async def test_a_skill_arslan_wrote_under_a_gh_key_reads_as_written(api, execution_db, tmp_path):
    """#499 review F7: create_skill takes "gh-" keys too; what Arslan wrote is checked first."""
    async with execution_db() as db:
        db.add(_pack("gh-weekly", "authored"))
        await db.commit()
    assert (await _rows(api))["skill:gh-weekly"]["origin"] == "authored"


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


async def test_a_connections_last_use_counts_only_from_when_it_was_added(api, execution_db, tmp_path):
    """#499 review F5: server ids are reused after the newest one is deleted; a call to the old server under the
    same id is not the new one's use."""
    await _seed(execution_db, tmp_path)
    await _steps(execution_db, ("mcp_3__search", datetime(2026, 8, 20, 9), "{}"))        # before server 3
    assert (await _rows(api))["mcp:3"]["last_used"] is None
    await _steps(execution_db, ("mcp_3__search", datetime(2026, 9, 2, 9), "{}"))
    assert (await _rows(api))["mcp:3"]["last_used"] == "2026-09-02T09:00:00Z"


@pytest.mark.parametrize("row,tool", [("browser", "browser_click"), ("hands", "desktop_type"),
                                      ("shortcuts", "mac_run_shortcut")])
async def test_the_browser_hands_and_shortcuts_rows_count_all_their_tools(api, execution_db, tmp_path, row, tool):
    """#499 review F8c: those rows stand for a family of tools, not only the two the row lists."""
    await _steps(execution_db, (tool, datetime(2026, 10, 26, 9), "{}"))
    assert (await _rows(api))[row]["last_used"] == "2026-10-26T09:00:00Z"


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
