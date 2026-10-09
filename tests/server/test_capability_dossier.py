"""0.1.57 P4: what Arslan found for later, dossiers, page installs, folders, updates, projects."""
import copy
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from server.services import capability_dossier as cd
from server.services import capability_flow, capability_install, capability_lookahead, capability_search

CAND = {"id": "registry:io.github.haris-musa/excel-mcp-server@1.1.2", "kind": "mcp", "name": "excel-mcp-server",
        "summary": "Reads and writes .xlsx", "source": "registry", "source_url": "https://github.com/haris-musa/excel-mcp-server",
        "repo": "haris-musa/excel-mcp-server", "version": "1.1.2", "runtime": "uv",
        "package": {"registry_type": "pypi", "identifier": "excel-mcp-server", "version": "1.1.2",
                    "arguments": [{"type": "positional", "value": "stdio"},
                                  {"type": "named", "name": "--allow-dir", "format": "filepath"}]},
        "remote": None, "not_here": None, "path": None, "stars": 4216, "pushed_days": 10,
        "needs": {"keys": [], "network": None},
        "license": {"spdx": "MIT", "read_from": "github:LICENSE", "verdict": "usable"}}


async def _find(execution_db, *, cand=CAND, days_ago=0, state="open", why="declined", level_id=None):
    from server.db.models import CapabilityFind
    async with execution_db() as db:
        row = CapabilityFind(id=f"f{datetime.utcnow().timestamp()}{days_ago}{state}", need="formulas", why=why,
                             candidate=copy.deepcopy(cand), state=state, level_id=level_id,
                             created_at=datetime.utcnow() - timedelta(days=days_ago))
        db.add(row)
        await db.commit()
        return row.id


# ── found for later ──────────────────────────────────────────────────────────

async def test_finds_are_open_recent_and_one_per_candidate(execution_db):
    await _find(execution_db, days_ago=2)
    newest = await _find(execution_db, days_ago=0)
    await _find(execution_db, cand={**CAND, "id": "other"}, days_ago=40)       # too old
    await _find(execution_db, cand={**CAND, "id": "gone"}, state="dismissed")
    rows = await cd.finds()
    assert [r["id"] for r in rows] == [newest]
    assert capability_search.seen(cd.PAGE, CAND["id"]) is not None             # installable from the page
    await cd.dismiss(newest)
    assert [r["id"] for r in await cd.finds()] != [newest]
    with pytest.raises(cd.DossierError, match="find_not_found"):
        await cd.dismiss("nope")


# ── a candidate's dossier and installing it from the page ────────────────────

async def test_check_reads_the_license_from_the_source_file(execution_db, monkeypatch):
    capability_search.remember(cd.PAGE, {"candidates": [{**CAND, "license": {"spdx": None, "read_from": None,
                                                                              "verdict": "unknown"}}]})
    asked = []

    async def license_of(repo):
        asked.append(repo)
        return "MIT", "LICENSE"
    monkeypatch.setattr(capability_install, "source_license", license_of)
    out = await cd.check(CAND["id"])
    assert asked == ["haris-musa/excel-mcp-server"]
    assert out["candidate"]["license"] == {"spdx": "MIT", "read_from": "LICENSE", "verdict": "usable"}
    assert out["installable"] is True
    assert capability_search.seen(cd.PAGE, CAND["id"])["license"]["verdict"] == "usable"     # remembered

    async def proprietary(repo):
        return None, "LICENSE.txt"
    monkeypatch.setattr(capability_install, "source_license", proprietary)
    out = await cd.check(CAND["id"])
    assert out["candidate"]["license"]["verdict"] == "reference_only" and out["why_not"] == "license_not_usable"
    with pytest.raises(cd.DossierError, match="unknown_candidate"):
        await cd.check("never-shown")


async def test_a_page_install_is_the_same_flow_and_clears_its_finds(execution_db, monkeypatch):
    await _find(execution_db)
    await cd.finds()                                         # the page saw it
    calls = []

    async def install(c, *, folders, keys):
        calls.append((c["id"], folders, keys))
        return {"state": "on", "source_id": "s1", "tools": ["read_range"]}
    monkeypatch.setattr(capability_flow, "install_mcp", install)
    out = await cd.install(CAND["id"], folders=["/tmp"], keys={})
    assert out["state"] == "on" and calls == [(CAND["id"], ["/tmp"], {})]
    assert await cd.finds() == []                            # installed: off the rail
    with pytest.raises(cd.DossierError, match="unknown_candidate"):
        await cd.install("never-shown", folders=[], keys={})


# ── an installed capability ──────────────────────────────────────────────────

async def _installed(execution_db, tmp_path, monkeypatch):
    from server import config
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    (tmp_path / "data").mkdir()

    async def mit(repo):
        return "MIT", "LICENSE"

    async def pypi(root, identifier, version):
        (root / "requirements.lock").write_text("x")
        return {"command": str(root / "venv/bin/excel-mcp-server"), "args": [], "lock_sha256": "a" * 64}
    monkeypatch.setattr(capability_install, "source_license", mit)
    monkeypatch.setattr(capability_install, "install_pypi", pypi)
    old = tmp_path / "Old"
    old.mkdir()
    return await capability_install.install(CAND, folders=[str(old)])


async def test_changing_folders_updates_the_sandbox_and_the_folder_argument(execution_db, monkeypatch, tmp_path):
    from server.db.models import MCPServer
    row = await _installed(execution_db, tmp_path, monkeypatch)
    new = tmp_path / "New"
    new.mkdir()
    out = await cd.set_folders(row.id, [str(new)])
    assert out["grants"]["folders"] == [str(new.resolve())]
    async with execution_db() as db:
        server = await db.get(MCPServer, row.mcp_server_id)
    assert server.args == ["stdio", "--allow-dir", str(new.resolve())]
    assert server.sandbox["folders"] == [str(new.resolve())]
    await cd.set_folders(row.id, [])
    async with execution_db() as db:
        assert (await db.get(MCPServer, row.mcp_server_id)).args == ["stdio"]


async def test_update_installs_beside_and_removes_the_old_only_when_the_new_one_passes(execution_db, monkeypatch, tmp_path):
    row = await _installed(execution_db, tmp_path, monkeypatch)

    async def latest(sid):
        return {"current": "1.1.2", "latest": "1.2.0", "newer": True,
                "candidate": {**CAND, "id": "registry:io.github.haris-musa/excel-mcp-server@1.2.0", "version": "1.2.0"}}
    monkeypatch.setattr(cd, "check_update", latest)
    removed, folders_seen = [], []

    async def remove(sid):
        removed.append(sid)
    monkeypatch.setattr(capability_install, "remove", remove)

    async def failing(c, *, folders, keys):
        folders_seen.append(folders)
        return {"state": "failed", "stage": "test", "detail": "x"}
    monkeypatch.setattr(capability_flow, "install_mcp", failing)
    out = await cd.update(row.id)
    assert out["state"] == "failed" and removed == []                          # the old one stays on
    assert folders_seen == [row.grants["folders"]]                             # same folders as before

    async def passing(c, *, folders, keys):
        return {"state": "on", "source_id": "new", "tools": ["a"]}
    monkeypatch.setattr(capability_flow, "install_mcp", passing)
    out = await cd.update(row.id)
    assert out["state"] == "on" and removed == [row.id]


async def test_check_update_compares_with_the_registry(execution_db, monkeypatch, tmp_path):
    row = await _installed(execution_db, tmp_path, monkeypatch)
    real = httpx.AsyncClient

    def handler(request):
        assert "io.github.haris-musa" in str(request.url) and str(request.url).endswith("/versions/latest")
        return httpx.Response(200, json={"server": {"name": "io.github.haris-musa/excel-mcp-server", "version": "1.10.0",
                                                    "repository": {"url": "https://github.com/haris-musa/excel-mcp-server"},
                                                    "packages": [{"registryType": "pypi", "identifier": "excel-mcp-server",
                                                                  "version": "1.10.0", "transport": {"type": "stdio"}}]}})

    class Client(real):
        def __init__(self, *a, **kw):
            kw.setdefault("transport", httpx.MockTransport(handler))
            super().__init__(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    out = await cd.check_update(row.id)
    assert out["newer"] is True and out["latest"] == "1.10.0" and out["current"] == "1.1.2"
    assert out["compare_url"] == "https://github.com/haris-musa/excel-mcp-server/compare/v1.1.2...v1.10.0"
    # The registry lists an older version than the one installed: nothing to update.
    from server.db.models import CapabilitySource
    async with execution_db() as db:
        (await db.get(CapabilitySource, row.id)).version = "1.11.0"
        await db.commit()
    out = await cd.check_update(row.id)
    assert out["newer"] is False and out["candidate"] is None


async def test_removing_a_skill_moves_its_files_to_the_trash(execution_db, monkeypatch, tmp_path):
    from pathlib import Path

    from server import config
    from server.db.models import CapabilitySource, SkillPack
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "skill_scripts" / "csv-tidy").mkdir(parents=True)
    async with execution_db() as db:
        db.add(SkillPack(key="csv-tidy", name="c", category="imported", description="d", tier="safe",
                         status="registered", body="x"))
        db.add(CapabilitySource(id="sk1", kind="skill", name="c", candidate_id="c", needs={}, grants={},
                                state="installed", skill_key="csv-tidy", created_at=datetime.utcnow()))
        await db.commit()
    await cd.remove("sk1")
    async with execution_db() as db:
        assert await db.get(SkillPack, "csv-tidy") is None
        assert (await db.get(CapabilitySource, "sk1")).state == "removed"
    assert not (tmp_path / "skill_scripts" / "csv-tidy").exists()
    assert (tmp_path / "home" / ".Trash" / "Arslan capability csv-tidy").is_dir()


# ── using a candidate in a project ───────────────────────────────────────────

async def test_as_material_puts_its_readme_into_the_projects_materials(execution_db, monkeypatch):
    from server.db.models import Collection, Project
    from server.services import ingest
    async with execution_db() as db:
        db.add(Project(id="p1", owner_id="local", name="Budget", kind="general", summary="", status="active",
                       version=1, collection_ids=[]))
        await db.commit()
    capability_search.remember(cd.PAGE, {"candidates": [CAND]})
    real = httpx.AsyncClient

    class Client(real):
        def __init__(self, *a, **kw):
            kw.setdefault("transport", httpx.MockTransport(lambda r: httpx.Response(200, text="# Excel MCP\nUse it.")))
            super().__init__(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    texts = []

    async def ingest_text(spawn, source, text, *, collection_id, compress=False):
        texts.append((source, text, collection_id))
        return 3
    monkeypatch.setattr(ingest, "ingest_text", ingest_text)
    out = await cd.as_material("p1", CAND["id"])
    async with execution_db() as db:
        project = await db.get(Project, "p1")
        col = await db.get(Collection, out["collection_id"])
    assert project.collection_ids == [col.id] and project.version == 1          # not a project edit
    assert out["chunks"] == 3 and "# Excel MCP" in texts[0][1] and "License: MIT" in texts[0][1]


# ── looking ahead at a level start ───────────────────────────────────────────

class _Reply:
    def __init__(self, content):
        self.content = content


def _model(content):
    class Adapter:
        async def chat(self, *, system, user):
            return _Reply(content)

    async def build():
        return Adapter()
    return build


async def test_a_level_that_needs_something_missing_puts_one_find_on_the_rail(execution_db, monkeypatch):
    from server.db.models import CapabilityFind
    monkeypatch.setattr(capability_lookahead, "_adapter", _model(
        '{"missing": true, "need": "Upload screenshots to App Store Connect", "keywords": ["app store connect"]}'))
    searched = []

    async def search(need, *, words=None, kinds=None):
        searched.append((need, words, kinds))
        return {"words": words, "notes": [], "candidates": [
            {**CAND, "id": "gpl", "license": {"spdx": "GPL-3.0", "read_from": "x", "verdict": "reference_only"}},
            {**CAND, "id": "good", "name": "asc-mcp"}]}
    monkeypatch.setattr(capability_search, "search", search)
    project = {"id": "p1", "name": "Sluice", "template": "game"}
    level = {"id": "L7", "name": "Store prep", "clear_condition": "submitted", "checkpoints": [{"text": "screenshots"}]}
    fid = await capability_lookahead.check_level(project, level)
    assert searched == [("Upload screenshots to App Store Connect", ["app store connect"], {"mcp", "skill"})]
    async with execution_db() as db:
        row = await db.get(CapabilityFind, fid)
    assert (row.why, row.project_id, row.level_id, row.candidate["id"]) == ("project_level", "p1", "L7", "good")
    assert await capability_lookahead.check_level(project, level) is None      # one look per level


@pytest.mark.parametrize("reply", ['{"missing": false}', "not json", None])
async def test_nothing_missing_or_no_model_means_no_find(execution_db, monkeypatch, reply):
    from server.db.models import CapabilityFind
    if reply is None:
        async def broken():
            raise RuntimeError("no model configured")
        monkeypatch.setattr(capability_lookahead, "_adapter", broken)
    else:
        monkeypatch.setattr(capability_lookahead, "_adapter", _model(reply))
    searched = []

    async def search(need, *, words=None, kinds=None):
        searched.append(need)
        return {"words": [], "notes": [], "candidates": [CAND]}
    monkeypatch.setattr(capability_search, "search", search)
    assert await capability_lookahead.check_level({"id": "p"}, {"id": "L", "name": "x", "checkpoints": []}) is None
    assert searched == []
    async with execution_db() as db:
        assert (await db.execute(select(CapabilityFind))).scalars().all() == []


async def test_a_level_becoming_current_starts_the_look(execution_db, monkeypatch):
    from server.db.models import Project
    from server.services import project_plan
    started = []
    monkeypatch.setattr(capability_lookahead, "later", lambda project, level: started.append((project["id"], level["name"])))
    async with execution_db() as db:
        db.add(Project(id="p2", owner_id="local", name="Game", kind="general", summary="", status="active", version=1,
                       collection_ids=[], template="game"))
        await db.commit()
        project = await db.get(Project, "p2")
        await project_plan.put_plan(db, project, 0, [{"name": "One", "band": "shaping", "checkpoints": [{"text": "a"}]},
                                                     {"name": "Two", "band": "done"}])
        await project_plan.start(db, project, actor="user", reason="test")
        await project_plan.advance(db, project, actor="user", leftover="move")   # 0.1.58: "a" is still open
        await db.commit()
    assert started == [("p2", "One"), ("p2", "Two")]
