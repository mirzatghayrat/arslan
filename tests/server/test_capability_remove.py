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
LEFTOVER = "csv-tidy-2"           # a folder no row holds, named with another key as a prefix (#499 review 2)
INSTALLED = datetime(2026, 10, 1)                                      # when the card installed them
ADDED = datetime(2026, 9, 1)                                           # when the connections were added


async def _seed(execution_db, tmp_path) -> None:
    """A built-in skill, one of each kind the user has, two hand-added and an installed connection."""
    for key in SCRIPTS:
        (tmp_path / "data" / "skill_scripts" / key).mkdir(parents=True)
        (tmp_path / "data" / "skill_scripts" / key / "run.py").write_text("print('hi')\n")
    (tmp_path / "data" / "skill_scripts" / LEFTOVER).mkdir()
    (tmp_path / "data" / "capabilities" / "m1").mkdir(parents=True)
    async with execution_db() as db:
        db.add_all([
            _pack("designed-html-report", "creative"),                   # planted by the seeder
            _pack("ghostwriter", "dev"),                                 # no mark, not a seed key: unknown (SKF1)
            _pack("csv-tidy", "imported"),                               # pasted a link (skill_import)
            _pack("xlsx", "productivity", source_id="sk1"),              # installed from a card
            _pack("deck", "productivity", source_id="sk2"),              # installed from a card too
            _pack("weekly-report", "authored"),                          # the save card
            _pack("page-notes", "authored-outside"),                     # the save card, after a page
            _pack("gh-acme-notes", "authored-outside"),                  # Discover, as migration 0080 left it
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
                             state="installed", mcp_server_id=2, created_at=INSTALLED, installed_at=INSTALLED),
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
        "skill:page-notes", "skill:gh-acme-notes", "skill:ghostwriter", "mcp:1", "mcp:2")}
    assert seen == {
        "terminal": ("builtin", "builtin", False),
        "files": ("builtin", "builtin", False),
        "skill:designed-html-report": ("skills", "builtin", False),
        "skill:csv-tidy": ("skills", "installed", True),
        "skill:xlsx": ("skills", "installed", True),
        "skill:weekly-report": ("skills", "authored", True),
        "skill:page-notes": ("skills", "authored", True),
        "skill:gh-acme-notes": ("skills", "authored", True),
        "skill:ghostwriter": ("skills", "unknown", True),                # D2(2), 2026-10-30: deletable
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


async def test_what_the_page_may_delete_is_every_skill_but_a_seed_row(api, execution_db, tmp_path):
    """#499 review F1: the page's mark agrees with D7 (seeder._USERS_SKILL): what the seeder never retires is
    not built in here, and what it may retire is. A skill promoted from Skill Forge before CAP2a reads as the
    user's because migration 0077 (CAP2b) marked it, and one the old Discover page made because 0080 did; no row is
    the user's by its key alone (SKF1). Every row but a seed row is deletable: the user's, and since D2(2)
    (2026-10-30) one of unknown origin too."""
    from sqlalchemy import select

    from server.registry import seeder, skill_trust
    await _seed(execution_db, tmp_path)
    async with execution_db() as db:
        everyone = set((await db.execute(select(SkillPack.key))).scalars())
        users = set((await db.execute(select(SkillPack.key).where(seeder._USERS_SKILL))).scalars())
    rows = await _rows(api)
    assert users and everyone - users                                               # both kinds present
    for key in everyone:
        seed = key not in users and key in skill_trust.SEEDED
        assert (rows[f"skill:{key}"]["origin"] == "builtin") == seed, key           # SKF1: built in = a seed row
        assert rows[f"skill:{key}"]["deletable"] == (not seed), key
    assert "designed-html-report" in skill_trust.SEEDED and "ghostwriter" not in skill_trust.SEEDED   # both kinds


def test_no_seed_skill_has_a_gh_key():
    """Migration 0080 marks every "gh-" row as outside, which is right only if no skill the seeder plants or
    retires has such a key."""
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
        db.add(_pack("../victim", "imported", source_id="bad"))       # its own skill, so the key alone guards
        db.add(CapabilitySource(id="bad", kind="skill", name="x", candidate_id="c", needs={}, grants={},
                                state="installed", skill_key="../victim", created_at=datetime(2026, 10, 1)))
        await db.commit()
    await capability_dossier.remove("bad")
    assert (tmp_path / "data" / "victim").is_dir() and not (tmp_path / "data" / "victim" / "SKILL.md").exists()
    assert not (tmp_path / "home" / ".Trash").exists()


def _stuck(path, prefix="Arslan capability"):
    raise OSError("Trash not writable")


async def _source(execution_db, source_id: str) -> CapabilitySource:
    async with execution_db() as db:
        return await db.get(CapabilitySource, source_id)


@pytest.mark.parametrize("key", ["csv-tidy", "weekly-report"])
async def test_a_failed_move_to_the_trash_keeps_the_skill(api, execution_db, monkeypatch, tmp_path, key):
    """#499 review F4: the files go to the Trash before the row goes, so a failed move leaves the skill whole,
    never a row-less scripts folder the next skill of that key would pick up. Nor the copy of its text: a skill
    with files keeps only them, and one without gets no folder."""
    from server.services import capability_install, capability_list
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    monkeypatch.setattr(capability_install, "to_trash", _stuck)
    with pytest.raises(OSError):
        await capability_list.remove(f"skill:{key}")
    assert await _state(execution_db, tmp_path) == before
    assert {p.name for p in (tmp_path / "data" / "skill_scripts" / "csv-tidy").iterdir()} == {"run.py"}


@pytest.mark.parametrize("key", ["weekly-report", "csv-tidy", "xlsx"])
async def test_a_deleted_skills_text_goes_to_the_trash_with_its_files(api, execution_db, tmp_path, key):
    """#499 second review 5: a skill's text lives only in the database, and a written one's nowhere else, so a
    delete keeps a copy: a SKILL.md the importer reads again goes to the Trash, with any files it came with."""
    from server.services import skill_import
    await _seed(execution_db, tmp_path)
    assert (await api.delete(f"/api/v1/capabilities/skill:{key}")).status_code == 200
    folder = tmp_path / "home" / ".Trash" / f"Arslan capability {key}"
    assert skill_import.parse_skill_md((folder / "SKILL.md").read_text(encoding="utf-8")) == {
        "key": key, "name": key.replace("-", " ").title(), "description": "d", "body": "## Trigger\nx", "cleaned": False,
        "frontmatter": key.replace("-", " ").title() + "\nd"}
    assert {p.name for p in folder.iterdir()} == ({"SKILL.md"} if key == "weekly-report" else {"SKILL.md", "run.py"})


async def test_a_failed_move_to_the_trash_keeps_an_installed_connection(api, execution_db, monkeypatch, tmp_path):
    """#499 second review 1: capability_install.remove deleted the server before its folder moved, so a failed
    move left a gone server and a source still "installed" pointing at its freed number. The Trash goes
    first now, as for a skill."""
    from server.services import capability_install, capability_list
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    monkeypatch.setattr(capability_install, "to_trash", _stuck)
    with pytest.raises(OSError):
        await capability_list.remove("mcp:2")
    assert await _state(execution_db, tmp_path) == before
    assert (await _source(execution_db, "m1")).mcp_server_id == 2


async def test_a_removed_connection_lets_go_of_its_server_number(api, execution_db, tmp_path):
    """mcp_servers.id has no AUTOINCREMENT: the next connection added by hand may get the same number."""
    await _seed(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capabilities/mcp:2")).status_code == 200
    assert (await _source(execution_db, "m1")).mcp_server_id is None


async def test_a_source_left_pointing_at_a_number_never_claims_another_server(api, execution_db, tmp_path):
    """#499 second review 1: a scan-blocked install deleted its server and kept the number (capability_flow:
    remove, then "failed"), and so did every removal before this fix. A server is a source's only while the
    source is not removed and if the server was there when the source was installed."""
    await _seed(execution_db, tmp_path)
    later = datetime(2026, 10, 20)
    async with execution_db() as db:
        db.add_all([
            CapabilitySource(id="m4", kind="mcp", name="blocked", candidate_id="c", needs={}, grants={},
                             state="failed", mcp_server_id=4, created_at=INSTALLED, installed_at=INSTALLED),
            MCPServer(id=4, label="later", command="", url="https://later.example.test/", transport="http",
                      host_allowed=True, status="registered", created_at=later),
            CapabilitySource(id="m0", kind="mcp", name="gone", candidate_id="c", needs={}, grants={},
                             state="removed", mcp_server_id=3, created_at=INSTALLED, installed_at=INSTALLED),
        ])
        await db.commit()
    rows = await _rows(api)
    assert [rows[key]["origin"] for key in ("mcp:2", "mcp:3", "mcp:4")] == ["installed", "manual", "manual"]
    before = await _state(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capabilities/mcp:4")).status_code == 200
    assert await _state(execution_db, tmp_path) == _without(before, server=4)     # by hand: m4 is not touched


async def test_a_stale_dossier_removal_never_deletes_a_skill_saved_later_under_its_key(api, execution_db, tmp_path):
    """#499 second review 2: the dossier deleted whichever skill held the key, and took removed sources."""
    await _seed(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capabilities/skill:xlsx")).status_code == 200        # sk1 is removed
    async with execution_db() as db:
        db.add(_pack("xlsx", "authored"))                                                   # saved later
        await db.commit()
    before = await _state(execution_db, tmp_path)
    response = await api.delete("/api/v1/capability-sources/sk1")
    assert (response.status_code, response.json()["detail"]) == (404, {"code": "source_not_found"})
    assert await _state(execution_db, tmp_path) == before


async def test_a_dossier_source_naming_a_skill_it_did_not_install_removes_only_itself(api, execution_db, tmp_path):
    """#499 second review 2: a source naming a seed key deleted the seed and moved its scripts."""
    await _seed(execution_db, tmp_path)
    async with execution_db() as db:
        db.add(CapabilitySource(id="sk3", kind="skill", name="report", candidate_id="c", needs={}, grants={},
                                state="installed", skill_key="designed-html-report", created_at=INSTALLED))
        await db.commit()
    before = await _state(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capability-sources/sk3")).status_code == 200
    assert await _state(execution_db, tmp_path) == {**before, "sources": {**before["sources"], "sk3": "removed"}}


async def test_the_dossier_moves_a_folder_whose_skill_is_already_gone(api, execution_db, tmp_path):
    """#499 recheck nit: a source whose skill row is gone left skill_scripts/<key> on disk, where run_python's
    skill_script could still load it. Nothing holds the key, so its folder goes to the Trash (no copy: no text)."""
    await _seed(execution_db, tmp_path)
    (tmp_path / "data" / "skill_scripts" / "orphan").mkdir()
    (tmp_path / "data" / "skill_scripts" / "orphan" / "run.py").write_text("print('hi')\n")
    async with execution_db() as db:
        db.add(CapabilitySource(id="sk4", kind="skill", name="orphan", candidate_id="c", needs={}, grants={},
                                state="installed", skill_key="orphan", created_at=INSTALLED))
        await db.commit()
    before = await _state(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capability-sources/sk4")).status_code == 200
    assert await _state(execution_db, tmp_path) == _without(before, skill="orphan", source="sk4")
    assert {p.name for p in (tmp_path / "home" / ".Trash" / "Arslan capability orphan").iterdir()} == {"run.py"}


async def test_the_dossier_removes_its_own_skill_and_keeps_it_on_a_failed_move(api, execution_db, monkeypatch, tmp_path):
    """#499 second review 3 (D1): the dossier's own removal moves the files first too."""
    from server.services import capability_dossier, capability_install
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(capability_install, "to_trash", _stuck)
        with pytest.raises(OSError):
            await capability_dossier.remove("sk2")
    assert await _state(execution_db, tmp_path) == before
    await capability_dossier.remove("sk2")
    assert await _state(execution_db, tmp_path) == _without(before, skill="deck", source="sk2")
    assert {p.name for p in (tmp_path / "home" / ".Trash" / "Arslan capability deck").iterdir()} == {"run.py", "SKILL.md"}


@pytest.mark.parametrize("key", [".", ".."])
async def test_a_dot_key_never_names_a_folder(api, execution_db, tmp_path, key):
    """#499 second review 3 (M07): stored or asked for, "." would name skill_scripts/ itself and ".." the data
    folder."""
    from server.services import capability_list
    await _seed(execution_db, tmp_path)
    async with execution_db() as db:
        db.add(_pack(key, "imported"))
        await db.commit()
    before = await _state(execution_db, tmp_path)
    with pytest.raises(capability_list.NotRemovable):
        await capability_list.remove(f"skill:{key}")
    response = await api.delete(f"/api/v1/capabilities/skill:{key}")
    assert (response.status_code, response.json()["detail"]) == (409, {"code": "not_removable"})
    assert await _state(execution_db, tmp_path) == before
    assert (tmp_path / "data" / "skill_scripts" / "csv-tidy" / "run.py").is_file()


FIELDS = {"key", "state", "tools", "switch", "reason", "fix", "name", "detail", "section", "origin", "deletable",
          "source_id", "reach", "last_used"}


async def test_no_row_carries_what_it_counts_as_use(api, execution_db, tmp_path):
    """#499 second review 4: the tools a row counts were stashed in the row and popped later, so any path
    that skipped the pop would send them to the client. The recheck: and under any other name (mutant N8)."""
    from server.services import capability_list
    await _seed(execution_db, tmp_path)
    rows = [*await capability_list._builtin_rows(), *await capability_list._mcp_rows(),
            *await capability_list._skill_rows(), *await capability_list._method_rows()]
    assert {row["key"].split(":")[0] for row in rows} >= {"terminal", "mcp", "skill", "method"}

    def fields(row) -> set[str]:                                 # a method row says its revision and last use
        return FIELDS | {"revision"} if row["key"].startswith("method:") else FIELDS
    assert not [row["key"] for row in rows
                if set(row) != fields(row) - (set() if row["key"].startswith("method:") else {"last_used"})]
    sent = (await api.get("/api/v1/capabilities")).json()
    assert sent and not [row["key"] for row in sent if set(row) != fields(row)]


def _linked(folder: Path, target: Path) -> None:
    import shutil
    shutil.rmtree(folder)
    folder.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("via", ["list", "dossier"])
async def test_a_scripts_folder_that_is_a_link_is_never_written_through(api, execution_db, tmp_path, via):
    """#499 recheck 1: the copy of the text would overwrite the link target's own SKILL.md, and only the link
    would go to the Trash. Arslan never makes such a link; the delete is refused and nothing changes."""
    await _seed(execution_db, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("theirs\n")
    _linked(tmp_path / "data" / "skill_scripts" / "deck", outside)
    before = await _state(execution_db, tmp_path)
    url = "/api/v1/capabilities/skill:deck" if via == "list" else "/api/v1/capability-sources/sk2"
    response = await api.delete(url)
    assert (response.status_code, response.json()["detail"]) == (409, {"code": "not_removable"})
    assert await _state(execution_db, tmp_path) == before
    assert (outside / "SKILL.md").read_text() == "theirs\n" and (tmp_path / "data" / "skill_scripts" / "deck").is_symlink()


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
async def test_a_skill_md_name_inside_the_folder_never_reaches_its_target(api, execution_db, monkeypatch, tmp_path, kind):
    """#499 recheck 1: a SKILL.md link (or a second name of another file) inside the folder: the copy is a new
    file of its own, and the target is never written, neither when the delete goes through nor when it fails."""
    import os
    from server.services import capability_install, capability_list
    await _seed(execution_db, tmp_path)
    victim = tmp_path / "victim.md"
    victim.write_text("theirs\n")
    name = tmp_path / "data" / "skill_scripts" / "xlsx" / "SKILL.md"
    name.symlink_to(victim) if kind == "symlink" else os.link(victim, name)
    with monkeypatch.context() as patch:
        patch.setattr(capability_install, "to_trash", _stuck)
        with pytest.raises(OSError):
            await capability_list.remove("skill:xlsx")
    assert victim.read_text() == "theirs\n"
    before = await _state(execution_db, tmp_path)
    assert (await api.delete("/api/v1/capabilities/skill:xlsx")).status_code == 200
    assert victim.read_text() == "theirs\n"
    copy = tmp_path / "home" / ".Trash" / "Arslan capability xlsx" / "SKILL.md"
    assert not copy.is_symlink() and "## Trigger" in copy.read_text()
    assert await _state(execution_db, tmp_path) == _without(before, skill="xlsx", source="sk1")


async def test_a_failed_write_of_the_copy_leaves_no_folder(api, execution_db, monkeypatch, tmp_path):
    """#499 recheck nit: a skill with no scripts folder gets one only for the copy, and keeps none if the copy
    cannot be written."""
    from server.services import capability_list

    def full(path, text):
        raise OSError("disk full")
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    monkeypatch.setattr(capability_list, "_write_new", full)
    with pytest.raises(OSError):
        await capability_list.remove("skill:weekly-report")
    assert await _state(execution_db, tmp_path) == before


async def test_a_failed_server_delete_keeps_the_source_and_a_retry_completes(api, execution_db, monkeypatch, tmp_path):
    """#499 recheck 2: capability_install.remove caught every error from delete_server as "already gone", but
    delete_server is quiet about a missing server, so the catch only hid a real failure, and the source was
    marked removed with its server still there."""
    from server.services import capability_list, mcp_service
    real = mcp_service.delete_server

    async def broken(server_id):
        raise RuntimeError("database is locked")
    await _seed(execution_db, tmp_path)
    before = await _state(execution_db, tmp_path)
    monkeypatch.setattr(mcp_service, "delete_server", broken)
    with pytest.raises(RuntimeError):
        await capability_list.remove("mcp:2")
    assert (await _source(execution_db, "m1")).state == "installed" and (await _source(execution_db, "m1")).mcp_server_id == 2
    assert (await _state(execution_db, tmp_path))["servers"] == before["servers"]
    monkeypatch.setattr(mcp_service, "delete_server", real)
    await capability_list.remove("mcp:2")
    assert await _state(execution_db, tmp_path) == _without(before, server=2, source="m1")


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
             "mcp-envsecret",                                # package-shaped, but the server's own secret
             "mcp_sk_fake_quebec", "fake/slash-romeo", "@x/y@sierralower"]   # not a package: no word "mcp" / version
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
                   "kilo", "lima1", "mikekey", "novq", "oscar", "papa", "envsecret", "8080", "/opt/tools", "quebec",
                   "romeo", "sierralower"):
        assert secret not in rows["mcp:7"]["reach"] + rows["mcp:8"]["reach"], secret


async def test_reach_keeps_a_package_after_a_flag_that_takes_no_value(api, execution_db, tmp_path):
    """#500 final recheck: `docker run -i --rm mcp/fetch` (the Docker MCP catalogue's own form) and
    `npx --verbose @scope/pkg` are found by their package."""
    async with execution_db() as db:
        db.add_all([
            MCPServer(id=9, label="fetch", command="docker", transport="stdio", host_allowed=True, status="registered",
                      args=["run", "-i", "--rm", "mcp/fetch"], created_at=ADDED),
            MCPServer(id=10, label="tool", command="npx", transport="stdio", host_allowed=True, status="registered",
                      args=["--verbose", "-q", "@scope/pkg@1.2.0"], created_at=ADDED),
        ])
        await db.commit()
    rows = await _rows(api)
    assert (rows["mcp:9"]["reach"], rows["mcp:10"]["reach"]) == ("docker mcp/fetch", "npx @scope/pkg@1.2.0")


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
