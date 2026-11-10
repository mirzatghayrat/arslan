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
    assert tree["scripts/run.py"] == RUN.encode() and tree["scripts/helper.py"] == HELPER.encode()
    assert tree["references/how.md"] == HOW.encode()
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
    # one copy: once the folder passed the check, the data folder's copy is gone; run_python reads the folder
    assert not data.exists() and agent_skills.export_state()["copies_left"] == []
    handed = _sandbox(monkeypatch)
    out = await RunPythonExecutor().execute({"skill_script": "weekly-report/run.py"})
    assert out["ok"] and handed[0][0] == RUN and handed[0][1]["extra_files"] == {"helper.py": HELPER}, out
    assert handed[0][1]["read_only_files"] == {"how.md": HOW}


async def test_a_switched_off_skill_is_not_exported(home):
    """The shared folder would show it to other tools as available: it stays in the data folder, off."""
    data = await _imported(scripts={"run.py": RUN}, enabled=False)
    await _imported("bb-on", scripts={"run.py": RUN})
    assert (await agent_skills.export_imported())["exported"] == ["bb-on"]
    assert _in_root(home) == ["bb-on"] and (data / "run.py").read_text() == RUN
    assert not agent_skills.is_folder_skill("weekly-report") and (await _pack()).enabled is False
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


@pytest.mark.parametrize("bad", ["a file", "the rows"])
async def test_a_backup_that_reads_back_wrong_exports_nothing(home, tmp_path, monkeypatch, bad):
    """The backup is read back before anything moves: one changed byte in a copied file, or in the rows."""
    data = await _imported(scripts={"run.py": RUN})
    if bad == "a file":
        real = agent_skills.shutil.copytree

        def copytree(src, dst, **kwargs):
            out = real(src, dst, **kwargs)
            (Path(dst) / "run.py").write_text(RUN.replace("W", "V"))
            return out
        monkeypatch.setattr(agent_skills.shutil, "copytree", copytree)
    else:
        real_rows = agent_skills._write_rows

        def write_rows(path, rows):
            real_rows(path, {key: {**row, "body": row["body"][:-1]} for key, row in rows.items()})
        monkeypatch.setattr(agent_skills, "_write_rows", write_rows)
    with pytest.raises(OSError, match="does not match"):
        await agent_skills.export_imported()
    assert _in_root(home) == [] and agent_skills.entries() == {} and agent_skills.export_state() is None
    assert [p.name for p in (tmp_path / "data" / "backups").iterdir()] == []      # no backup, no .partial
    assert (data / "run.py").read_text() == RUN


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


@pytest.mark.parametrize("where", ["while it writes a skill", "after a skill is in place", "after its hashes",
                                   "while its data-folder copy goes"])
async def test_an_export_cut_short_finishes_when_run_again(home, monkeypatch, where):
    for key in ("aa-first", "bb-second"):
        await _imported(key, scripts={"run.py": RUN}, refs={"how.md": HOW})
    real_rename, real_record, real_clear = os.rename, agent_skills.record, agent_skills._clear

    def clear(path):
        if where == "while its data-folder copy goes" and path == agent_skills._data_folder("aa-first"):
            (path / "run.py").unlink()                     # part of it gone, then the stop
            raise _Crash()
        return real_clear(path)
    monkeypatch.setattr(agent_skills, "_clear", clear)

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
    monkeypatch.setattr(agent_skills, "_clear", real_clear)
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
        assert not agent_skills._data_folder(key).exists()                  # one copy left, the folder's
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


THEIRS = "---\nname: Weekly report\ndescription: Another tool's.\n---\n\n## Trigger\nTheirs.\n"


def _replace_or_edit(home: Path, how: str) -> dict[str, bytes]:
    folder = home / ".agents" / "skills" / "weekly-report"
    if how == "another tool replaced it":
        import shutil
        shutil.rmtree(folder)
        _place(home, key="weekly-report", text=THEIRS, scripts__theirs_py="print('theirs')\n")
    else:
        (folder / "SKILL.md").write_text((folder / "SKILL.md").read_text() + "\nThe user's own line.\n")
    return _tree(folder)


async def _left_as_another_tools(home: Path, before: dict[str, bytes]) -> None:
    folder = home / ".agents" / "skills" / "weekly-report"
    assert _tree(folder) == before and not (home / ".Trash" / "Arslan skill weekly-report").exists()
    assert "weekly-report" not in agent_skills.entries() and await _pack() is None
    await agent_skills.sync()                         # what is left reads as another tool's, off until its card
    pack = await _pack()
    assert pack.category == "other-tool" and pack.enabled is False
    assert await agent_skills.needs_card("weekly-report")


@pytest.mark.parametrize("how", ["another tool replaced it", "the user edited its SKILL.md"])
async def test_deleting_an_exported_skill_never_takes_a_folder_that_isnt_still_arslans(api, home, how):
    await _imported(scripts={"run.py": RUN})
    await agent_skills.export_imported()
    before = _replace_or_edit(home, how)
    await agent_skills.sync()
    response = await api.delete("/api/v1/capabilities/skill:weekly-report")
    assert response.status_code == 200, response.text
    await _left_as_another_tools(home, before)


async def test_the_dossier_removal_never_takes_an_exported_folder_that_isnt_still_arslans(home, execution_db):
    from server.services import capability_dossier
    async with execution_db() as db:
        db.add(CapabilitySource(id="src-1", kind="skill", name="Weekly report", candidate_id="github:acme/skills:w",
                                runtime="skill", needs={}, grants={}, state="installed", skill_key="weekly-report"))
        await db.commit()
    await _imported(scripts={"run.py": RUN}, source_id="src-1")
    assert (await agent_skills.export_imported())["exported"] == ["weekly-report"]
    before = _replace_or_edit(home, "another tool replaced it")
    await capability_dossier.remove("src-1")
    await _left_as_another_tools(home, before)


async def test_a_lost_hash_file_after_the_export_fails_closed(home, tmp_path, monkeypatch):
    """No second copy to fall back to: the row's text still reads, its scripts don't run, and the folder (whose files
    nothing vouches for now) is never taken back by a run of the export again."""
    await _imported(scripts={"run.py": RUN})
    await agent_skills.export_imported()
    (tmp_path / "data" / "agent_skills.json").unlink()
    await agent_skills.sync()
    handed = _sandbox(monkeypatch)
    out = await RunPythonExecutor().execute({"skill_script": "weekly-report/run.py"})
    assert out["ok"] is False and handed == [], out
    report = await agent_skills.export_imported()
    assert report["kept"] == {"weekly-report": "clash"} and "weekly-report" not in agent_skills.entries()
    assert (await RunPythonExecutor().execute({"skill_script": "weekly-report/run.py"}))["ok"] is False
    assert (await ReadSkillExecutor().execute({"key": "weekly-report"}))["ok"]


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


async def _reload_in_the_window(monkeypatch, work, *, after: bool, during=None):
    reached, release = _pause_commit(monkeypatch, after=after)
    task = asyncio.create_task(work)
    await asyncio.wait_for(reached.wait(), 5)
    # the Capabilities page loading in the window, or another call
    reload = asyncio.create_task(during() if during else agent_skills.sync())
    await asyncio.sleep(0.3)
    release.set()
    await asyncio.wait_for(task, 5)
    return await asyncio.wait_for(reload, 5)


async def test_a_read_skill_during_an_approval_waits_for_its_hashes(api, home, monkeypatch):
    """#808 review: `checked` compares again under the lock before it switches anything off."""
    _place(home)
    await agent_skills.sync()
    digest = agent_skills.card("pdf-notes")["digest"]
    out = await _reload_in_the_window(monkeypatch, agent_skills.approve("pdf-notes", digest), after=True,
                                      during=lambda: ReadSkillExecutor().execute({"key": "pdf-notes"}))
    assert out["ok"], out
    assert (await _pack("pdf-notes")).enabled is True and not await agent_skills.needs_card("pdf-notes")


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


# ── #808 review ────────────────────────────────────────────────────────────────────────────────────────────────

async def test_a_slow_folder_read_holds_up_nothing_else(home, monkeypatch):
    """The reload's folder read is not under the lock: a read_skill and an install go on meanwhile. What the install
    changed while the folder was read is read again once the lock is taken, so it is not taken for gone."""
    import threading
    await _imported("aa-exported", scripts={"run.py": RUN})
    await agent_skills.export_imported()
    held, real = threading.Event(), agent_skills._list_and_read

    def list_and_read():
        out = real()                                   # listed before the install below
        held.wait(10)
        return out
    monkeypatch.setattr(agent_skills, "_list_and_read", list_and_read)
    reload = asyncio.create_task(agent_skills.sync())
    await asyncio.sleep(0.1)
    try:
        out = await asyncio.wait_for(ReadSkillExecutor().execute({"key": "aa-exported"}), 2)
        assert out["ok"], out
        await asyncio.wait_for(skill_import.install_prepared(_prepared()), 2)
    finally:
        held.set()
    assert await asyncio.wait_for(reload, 5) == {"aa-exported": "ok", "weekly-report": "ok"}
    pack = await _pack()
    assert pack.category == "imported" and pack.enabled is True


async def test_a_fifo_in_place_of_a_file_never_blocks_the_read(tmp_path):
    """A FIFO swapped in after the caller's lstat: opened without blocking, and refused as not a regular file."""
    fifo = tmp_path / "swapped"
    os.mkfifo(fifo)
    task = asyncio.ensure_future(asyncio.to_thread(agent_skills._read_file, fifo))
    done, _ = await asyncio.wait({task}, timeout=2)
    if not done:
        os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))          # let the stuck read go
        await asyncio.wait({task}, timeout=2)
        pytest.fail("the read blocked on a FIFO")
    with pytest.raises(OSError, match="not a regular file"):
        task.result()


async def test_finders_ds_store_is_not_a_change(api, home):
    folder = _place(home)
    await agent_skills.sync()
    digest = agent_skills.card("pdf-notes")["digest"]
    await agent_skills.approve("pdf-notes", digest)
    (folder / ".DS_Store").write_bytes(b"\x00\x01")
    (folder / "scripts").mkdir()
    (folder / "scripts" / ".DS_Store").write_bytes(b"\x00\x02")
    assert (await ReadSkillExecutor().execute({"key": "pdf-notes"}))["ok"]
    assert (await _pack("pdf-notes")).enabled is True and await agent_skills.sync() == {"pdf-notes": "ok"}


async def test_the_user_is_told_once(api, home, tmp_path):
    """One line on the Capabilities page after the export: how many imported skills moved to the shared folder.
    Shown once: the page says it showed it, and that is recorded in the data folder."""
    assert (await api.get("/api/v1/skill-export-notice")).json() == {"count": 0}     # before the export
    for key in ("aa-first", "bb-second"):
        await _imported(key, scripts={"run.py": RUN})
    await _imported("cc-off", enabled=False)
    await agent_skills.export_imported()
    assert (await api.get("/api/v1/skill-export-notice")).json() == {"count": 2}
    assert (await api.post("/api/v1/skill-export-notice/seen")).status_code == 200
    assert (await api.get("/api/v1/skill-export-notice")).json() == {"count": 0}
    assert json.loads((tmp_path / "data" / "agent_skills.json").read_text())["export"]["notice_shown"] is True
    agent_skills.record("zz-later", by="arslan", files={})          # later manifest writes keep the record
    assert (await api.get("/api/v1/skill-export-notice")).json() == {"count": 0}


async def test_nothing_exported_is_never_told(api, home):
    await agent_skills.export_imported()
    assert (await api.get("/api/v1/skill-export-notice")).json() == {"count": 0}


async def test_at_start_a_cut_short_plugin_install_goes_before_the_export(monkeypatch):
    """#808 review: the export runs after plugin_package.finish_interrupted, so a cut-short plugin's parts are switched
    off and removed first, never moved into the shared folder; then the folder is read."""
    from server import main
    from server.services import plugin_package
    order: list[str] = []

    def step(name):
        async def run():
            order.append(name)
        return run
    monkeypatch.setattr(plugin_package, "finish_interrupted", step("finish_interrupted"))
    monkeypatch.setattr(agent_skills, "export_imported", step("export"))
    monkeypatch.setattr(agent_skills, "sync", step("sync"))
    await main._boot_skills()
    assert order == ["finish_interrupted", "export", "sync"]
