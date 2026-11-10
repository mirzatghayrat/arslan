"""CAP6a, second part (v0.1.64): the one-time export of skills imported before CAP6a to ~/.agents/skills
(docs/plans/0164/CAP-capabilities.md §CAP6a, and the risk line: changing storage can lose skills already installed).

A skill imported before CAP6a keeps its scripts and references in Arslan's data folder. The export moves it, at the
same version, into `~/.agents/skills/<key>/` through part 1's install path (each file created new, then read back)
and its hash records. It backs up first, checks the count and the hashes after, runs once (the record in the data
folder), finishes when it is run again after a stop, never overwrites a folder another tool put there, and leaves a
skill it can't move working as before. Also two items of #795's review: a SKILL.md name or description is capped
before it is cleaned, and a reload during an approval no longer switches the just-approved skill off.

Real paths on a scratch HOME and data folder."""
import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from server import config
from server.db import session as db_session
from server.db.models import CapabilitySource, SkillPack
from server.registry.executors import ReadSkillExecutor, RunPythonExecutor
from server.services import agent_skills, code_sandbox, skill_import
from tests.server.test_cap6a_skills_folder import _place, _prepared

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def home(execution_db, monkeypatch, tmp_path):
    """As test_cap6a_skills_folder's: a scratch HOME (so ~/.agents/skills) and data folder, never the real ones."""
    from server.registry import executors
    monkeypatch.setattr(executors, "AsyncSessionLocal", execution_db)
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "data").mkdir()
    return tmp_path / "home"


@pytest.fixture
async def api(home, monkeypatch):
    import httpx
    from fastapi import FastAPI

    from server import auth
    from server.api.capabilities import router
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-cap6a-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 headers={"Authorization": "Bearer synthetic-cap6a-token"}) as client:
        yield client

BODY = ("> Imported verbatim from https://github.com/acme/skills at 000000000000 (MIT) on 2026-10-01.\n\n"
        "## Trigger\nWhen the week ends, write the report from the notes, in five short lines.\n\n"
        "## Bundled scripts\n- `weekly-report/run.py`")
RUN = "from helper import W\nprint(W)\n"
HELPER = "W = 1\n"
HOW = "# how\nfive short lines\n"


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


async def _imported(key: str = "weekly-report", *, scripts: dict | None = None, refs: dict | None = None,
                    category: str = "imported", source_id: str | None = None, description: str = "Write the report.",
                    enabled: bool = True) -> Path:
    """A skill as an import before CAP6a left it: its row, and its files under <data>/skill_scripts/<key>/."""
    async with db_session.AsyncSessionLocal() as db:
        db.add(SkillPack(key=key, name="Weekly report", category=category, description=description, tier="safe",
                         status="registered", body=BODY, enabled=enabled, source_id=source_id))
        await db.commit()
    base = config.data_dir() / "skill_scripts" / key
    for name, text in (scripts or {}).items():
        base.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(text)
    for name, text in (refs or {}).items():
        (base / "references").mkdir(parents=True, exist_ok=True)
        (base / "references" / name).write_text(text)
    return base


async def _pack(key: str = "weekly-report") -> SkillPack | None:
    async with db_session.AsyncSessionLocal() as db:
        return await db.get(SkillPack, key)


def _sandbox(monkeypatch) -> list:
    handed: list = []

    async def run(code, **kwargs):
        handed.append((code, kwargs))
        return {"ok": True, "stdout": "1\n", "network_isolated": True}
    monkeypatch.setattr(code_sandbox, "run_python", run)
    return handed


def _tree(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def _in_root(home: Path) -> list[str]:
    root = home / ".agents" / "skills"
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


async def _works_from_the_data_folder(monkeypatch, key: str = "weekly-report") -> None:
    """The skill as it was before the export: its row's text, and its script from the data folder."""
    assert not agent_skills.is_folder_skill(key)
    out = await ReadSkillExecutor().execute({"key": key})
    assert out["ok"] and out["body"].startswith("> Imported verbatim"), out
    handed = _sandbox(monkeypatch)
    out = await RunPythonExecutor().execute({"skill_script": f"{key}/run.py"})
    assert out["ok"], out
    assert handed[-1][0] == RUN
    assert (await _pack(key)).enabled is True


# ── the export ──────────────────────────────────────────────────────────────────────────────────────────────────

async def test_an_imported_skill_goes_to_the_folder_at_the_same_version(home, monkeypatch):
    data = await _imported(scripts={"run.py": RUN, "helper.py": HELPER}, refs={"how.md": HOW})
    report = await agent_skills.export_imported()
    assert report["exported"] == ["weekly-report"] and report["kept"] == {}, report
    folder = home / ".agents" / "skills" / "weekly-report"
    tree = _tree(folder)
    assert sorted(tree) == ["SKILL.md", "references/how.md", "scripts/helper.py", "scripts/run.py"]
    assert tree["scripts/run.py"] == (data / "run.py").read_bytes() and tree["references/how.md"] == HOW.encode()
    info = skill_import.parse_skill_md(tree["SKILL.md"].decode(), "weekly-report/SKILL.md")
    assert info["name"] == "Weekly report" and info["description"] == "Write the report." and info["body"] == BODY
    entry = agent_skills.entries()["weekly-report"]
    assert entry == {"by": "arslan", "files": {rel: _sha(raw) for rel, raw in tree.items()}}
    pack = await _pack()                                             # the row is as it was
    assert pack.category == "imported" and pack.body == BODY and pack.enabled is True
    assert await agent_skills.sync() == {"weekly-report": "ok"}
    out = await ReadSkillExecutor().execute({"key": "weekly-report"})
    assert out["ok"] and out["body"] == BODY, out
    ref = await ReadSkillExecutor().execute({"key": "weekly-report", "section": "references/how.md"})
    assert ref["ok"] and ref["body"] == HOW, ref
    # run_python reads the folder now (the bytes just checked), no longer the data folder's copy
    (data / "helper.py").write_text("W = 'the old copy'\n")
    handed = _sandbox(monkeypatch)
    out = await RunPythonExecutor().execute({"skill_script": "weekly-report/run.py"})
    assert out["ok"] and handed[0][0] == RUN and handed[0][1]["extra_files"] == {"helper.py": HELPER}, out
    assert handed[0][1]["read_only_files"] == {"how.md": HOW}


async def test_a_switched_off_skill_stays_off(home):
    await _imported(scripts={"run.py": RUN}, enabled=False)
    assert (await agent_skills.export_imported())["exported"] == ["weekly-report"]
    assert (await _pack()).enabled is False
    assert (await ReadSkillExecutor().execute({"key": "weekly-report"}))["ok"] is False


async def test_it_backs_up_first(home, tmp_path, monkeypatch):
    await _imported(scripts={"run.py": RUN}, refs={"how.md": HOW})
    seen: list = []
    real = agent_skills.write_new

    def write_new(base, expected):
        seen.append(sorted(p.name for p in (tmp_path / "data" / "backups").iterdir()))
        return real(base, expected)
    monkeypatch.setattr(agent_skills, "write_new", write_new)
    report = await agent_skills.export_imported()
    backup = tmp_path / "data" / report["backup"]
    assert seen == [[backup.name]]                                  # whole before the first file is written
    rows = json.loads((backup / "skills.json").read_text())
    assert rows["weekly-report"]["body"] == BODY and rows["weekly-report"]["category"] == "imported"
    assert rows["weekly-report"]["files"] == {"scripts/run.py": _sha(RUN), "references/how.md": _sha(HOW)}
    assert (backup / "skill_scripts" / "weekly-report" / "run.py").read_text() == RUN
    assert (backup / "skill_scripts" / "weekly-report" / "references" / "how.md").read_text() == HOW


async def test_a_backup_that_fails_exports_nothing(home, tmp_path, monkeypatch):
    await _imported(scripts={"run.py": RUN})
    real = agent_skills.shutil.copytree

    def copytree(*args, **kwargs):
        raise OSError("the disk is full")
    monkeypatch.setattr(agent_skills.shutil, "copytree", copytree)
    with pytest.raises(OSError):
        await agent_skills.export_imported()
    assert _in_root(home) == [] and agent_skills.entries() == {} and agent_skills.export_state() is None
    assert [p.name for p in (tmp_path / "data" / "backups").iterdir()] == []     # no half backup left
    await _works_from_the_data_folder(monkeypatch)
    monkeypatch.setattr(agent_skills.shutil, "copytree", real)
    assert (await agent_skills.export_imported())["exported"] == ["weekly-report"]   # and the next start does it


async def test_it_runs_once(home, tmp_path):
    await _imported()
    assert (await agent_skills.export_imported())["exported"] == ["weekly-report"]
    state = json.loads((tmp_path / "data" / "agent_skills.json").read_text())["export"]
    assert state["state"] == "done" and state["exported"] == ["weekly-report"]
    await _imported("later-skill")
    assert await agent_skills.export_imported() is None
    assert _in_root(home) == ["weekly-report"] and "later-skill" not in agent_skills.entries()


async def test_with_nothing_to_export_it_is_done_at_once(home, tmp_path):
    assert (await agent_skills.export_imported())["exported"] == []
    assert agent_skills.export_state()["state"] == "done" and not (tmp_path / "data" / "backups").exists()
    await _imported()
    assert await agent_skills.export_imported() is None


async def test_only_imported_skills_and_a_sources_skills_are_exported(home, execution_db):
    from server.registry.skill_trust import SEEDED
    async with execution_db() as db:
        db.add(CapabilitySource(id="plug-1", kind="plugin", name="Plug", candidate_id="github:x/plug", runtime="plugin",
                                needs={}, grants={}, state="installed"))
        await db.commit()
    await _imported("aa-imported")
    await _imported("bb-sourced", category="custom", source_id="plug-1")
    await _imported("cc-authored", category="authored")
    await _imported("dd-other", category="other-tool")
    await _imported(sorted(SEEDED)[0])
    report = await agent_skills.export_imported()
    assert report["exported"] == ["aa-imported", "bb-sourced"] and report["kept"] == {}, report
    assert _in_root(home) == ["aa-imported", "bb-sourced"]


class _Crash(BaseException):
    """Arslan stopping: nothing after it runs."""


@pytest.mark.parametrize("where", ["while it writes a skill", "after a skill is in place", "after its hashes"])
async def test_an_export_cut_short_finishes_when_run_again(home, monkeypatch, where):
    for key in ("aa-first", "bb-second"):
        await _imported(key, scripts={"run.py": RUN}, refs={"how.md": HOW})
    real_rename, real_record = os.rename, agent_skills.record

    def rename(src, dst, *args, **kwargs):
        if Path(dst) == agent_skills.folder("aa-first") and where == "while it writes a skill":
            raise _Crash()
        real_rename(src, dst, *args, **kwargs)
        if Path(dst) == agent_skills.folder("aa-first") and where == "after a skill is in place":
            raise _Crash()

    def record(key, *, by, files):
        real_record(key, by=by, files=files)
        if key == "aa-first" and where == "after its hashes":
            raise _Crash()
    monkeypatch.setattr(agent_skills.os, "rename", rename)
    monkeypatch.setattr(agent_skills, "record", record)
    with pytest.raises(_Crash):
        await agent_skills.export_imported()
    monkeypatch.setattr(agent_skills.os, "rename", real_rename)
    monkeypatch.setattr(agent_skills, "record", real_record)
    # Stopped there, the skill still works (from the folder once its hashes are kept, else from the data folder),
    # and the folder's reading at start leaves it on.
    await agent_skills.sync()
    assert (await _pack("aa-first")).enabled is True
    assert (await ReadSkillExecutor().execute({"key": "aa-first"}))["ok"]
    handed = _sandbox(monkeypatch)
    assert (await RunPythonExecutor().execute({"skill_script": "aa-first/run.py"}))["ok"] and handed[0][0] == RUN
    report = await agent_skills.export_imported()
    assert report["exported"] == ["aa-first", "bb-second"] and report["kept"] == {}, report
    assert _in_root(home) == ["aa-first", "bb-second"]                   # nothing half-written left
    for key in ("aa-first", "bb-second"):
        assert agent_skills.entries()[key]["by"] == "arslan"
        assert sorted(_tree(agent_skills.folder(key))) == ["SKILL.md", "references/how.md", "scripts/run.py"]
    assert agent_skills.export_state()["state"] == "done"


@pytest.mark.parametrize("theirs", ["a skill of its own", "an empty folder"])
async def test_a_folder_another_tool_put_there_is_never_overwritten(home, monkeypatch, theirs):
    await _imported(scripts={"run.py": RUN})
    folder = home / ".agents" / "skills" / "weekly-report"
    if theirs == "an empty folder":
        folder.mkdir(parents=True)
    else:
        _place(home, key="weekly-report")
    before = _tree(folder)
    report = await agent_skills.export_imported()
    assert report["kept"] == {"weekly-report": "clash"} and report["exported"] == [], report
    assert folder.is_dir() and _tree(folder) == before and _in_root(home) == ["weekly-report"]
    assert "weekly-report" not in agent_skills.entries()
    assert agent_skills.export_state()["kept"] == {"weekly-report": "clash"}       # reported
    await agent_skills.sync()
    pack = await _pack()
    assert pack.category == "imported" and pack.body == BODY                       # the copy in Arslan's database
    await _works_from_the_data_folder(monkeypatch)


async def test_a_skill_whose_export_fails_works_as_before(home, monkeypatch):
    for key in ("aa-first", "bb-second"):
        await _imported(key, scripts={"run.py": RUN})
    real = agent_skills.write_new

    def write_new(base, expected):
        if base.name.endswith("aa-first"):
            (base / "SKILL.md").write_text("half")
            raise OSError("the disk is full")
        return real(base, expected)
    monkeypatch.setattr(agent_skills, "write_new", write_new)
    report = await agent_skills.export_imported()
    assert report["exported"] == ["bb-second"] and report["kept"] == {"aa-first": "failed (OSError)"}, report
    assert _in_root(home) == ["bb-second"]                                 # no half-written folder anywhere
    assert agent_skills.export_state()["state"] == "done"
    await _works_from_the_data_folder(monkeypatch, "aa-first")


@pytest.mark.parametrize("after", ["a file added", "a file changed"])
async def test_the_check_after_puts_back_a_skill_that_does_not_match(home, monkeypatch, after):
    """The count (the same files, no more) and the hashes, read again once every skill is in place."""
    await _imported(scripts={"run.py": RUN})
    real = os.rename

    def rename(src, dst, *args, **kwargs):
        real(src, dst, *args, **kwargs)
        if Path(dst) == agent_skills.folder("weekly-report"):
            if after == "a file added":
                (Path(dst) / "scripts" / "extra.py").write_text("print('extra')\n")
            else:
                (Path(dst) / "scripts" / "run.py").write_text("print('changed')\n")
    monkeypatch.setattr(agent_skills.os, "rename", rename)
    report = await agent_skills.export_imported()
    assert report["kept"] == {"weekly-report": "check failed"} and report["exported"] == [], report
    monkeypatch.setattr(agent_skills.os, "rename", real)
    await _works_from_the_data_folder(monkeypatch)


async def test_a_row_whose_text_is_not_a_valid_skill_md_stays(home, monkeypatch):
    await _imported(scripts={"run.py": RUN}, description="")
    report = await agent_skills.export_imported()
    assert report["kept"] == {"weekly-report": "its text is not a valid SKILL.md"}, report
    assert _in_root(home) == []
    handed = _sandbox(monkeypatch)
    assert (await RunPythonExecutor().execute({"skill_script": "weekly-report/run.py"}))["ok"] and handed[0][0] == RUN


async def test_files_with_a_link_stay_in_the_data_folder(home, tmp_path, monkeypatch):
    data = await _imported(scripts={"run.py": RUN})
    (tmp_path / "secret.txt").write_text("not the skill's\n")
    (data / "notes.txt").symlink_to(tmp_path / "secret.txt")
    report = await agent_skills.export_imported()
    assert report["kept"] == {"weekly-report": "its files hold a link"} and _in_root(home) == [], report


async def test_deleting_an_exported_skill_takes_the_data_folder_copy_too(api, home, monkeypatch):
    data = await _imported(scripts={"run.py": RUN})
    await agent_skills.export_imported()
    response = await api.delete("/api/v1/capabilities/skill:weekly-report")
    assert response.status_code == 200, response.text
    assert _in_root(home) == [] and not data.exists() and await _pack() is None
    handed = _sandbox(monkeypatch)
    out = await RunPythonExecutor().execute({"skill_script": "weekly-report/run.py"})
    assert out["ok"] is False and handed == [], out


async def test_a_lost_hash_file_after_the_export_is_healed_at_the_next_start(home, tmp_path, monkeypatch):
    await _imported(scripts={"run.py": RUN})
    await agent_skills.export_imported()
    (tmp_path / "data" / "agent_skills.json").unlink()
    await agent_skills.sync()                       # until the next start: the data folder's copy, never off
    await _works_from_the_data_folder(monkeypatch)
    report = await agent_skills.export_imported()   # the export's own folder, exactly its files: taken back
    assert report["exported"] == ["weekly-report"] and agent_skills.entries()["weekly-report"]["by"] == "arslan"


# ── #795 review 1: a name or description is capped before it is cleaned ────────────────────────────────────────

async def test_a_huge_name_or_description_is_refused_before_it_is_read(home):
    """A 5 MB plain scalar took seconds to parse and clean, on the event loop (the dossier, the start)."""
    import time
    huge = "---\nname: n\ndescription: " + "a" * 5_000_000 + "\n---\n\n## Trigger\nx\n"
    started = time.monotonic()
    assert skill_import.parse_skill_md(huge, "x/SKILL.md") is None
    assert time.monotonic() - started < 0.5, time.monotonic() - started
    for name, description in (("n" * 1_001, "d"), ("n", "d" * 5_001)):
        assert skill_import.parse_skill_md(f"---\nname: {name}\ndescription: {description}\n---\n\n## Trigger\nx\n") \
            is None, (len(name), len(description))
    fine = skill_import.parse_skill_md(f"---\nname: {'n' * 1_000}\ndescription: {'d' * 5_000}\n---\n\n## Trigger\nx\n")
    assert len(fine["name"]) == 100 and len(fine["description"]) == 300          # cleaned and cut as before
    _place(home, key="zz-huge", text=huge)
    started = time.monotonic()
    await agent_skills.sync()
    assert time.monotonic() - started < 1.0 and await _pack("zz-huge") is None


# ── #795 review 2: a reload during an approval ─────────────────────────────────────────────────────────────────

def _pause_commit(monkeypatch, *, after: bool):
    """The next commit stops (after the real commit, or before it) until `release`; later commits run as usual."""
    from sqlalchemy.ext.asyncio import AsyncSession
    real = AsyncSession.commit
    reached, release, armed = asyncio.Event(), asyncio.Event(), [True]

    async def commit(self):
        if not armed[0]:
            return await real(self)
        armed[0] = False
        if after:
            await real(self)
        reached.set()
        await release.wait()
        if not after:
            await real(self)
    monkeypatch.setattr(AsyncSession, "commit", commit)
    return reached, release


async def _reload_in_the_window(monkeypatch, work, *, after: bool):
    reached, release = _pause_commit(monkeypatch, after=after)
    task = asyncio.create_task(work)
    await asyncio.wait_for(reached.wait(), 5)
    reload = asyncio.create_task(agent_skills.sync())          # the Capabilities page loading, in the window
    await asyncio.sleep(0.3)
    release.set()
    await asyncio.wait_for(task, 5)
    await asyncio.wait_for(reload, 5)


async def test_a_reload_between_an_approvals_commit_and_its_hashes_leaves_it_on(api, home, monkeypatch):
    _place(home)
    await agent_skills.sync()
    digest = agent_skills.card("pdf-notes")["digest"]
    await _reload_in_the_window(monkeypatch, agent_skills.approve("pdf-notes", digest), after=True)
    assert (await _pack("pdf-notes")).enabled is True and not await agent_skills.needs_card("pdf-notes")
    assert (await ReadSkillExecutor().execute({"key": "pdf-notes"}))["ok"]


async def test_a_reload_between_an_installs_hashes_and_its_row_leaves_it_arslans(home, monkeypatch):
    await _reload_in_the_window(monkeypatch, skill_import.install_prepared(_prepared()), after=False)
    pack = await _pack()
    assert pack.category == "imported" and pack.enabled is True
    assert agent_skills.entries()["weekly-report"]["by"] == "arslan"
    assert await agent_skills.sync() == {"weekly-report": "ok"}
