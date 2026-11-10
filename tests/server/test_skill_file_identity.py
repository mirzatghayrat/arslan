"""Skills (v0.1.64): a script or reference with another name on disk, or a skill with no record, is refused.

`run_python` and `read_skill` read a skill's files with Arslan's own rights and hand their text to the sandbox or the
model. So each file read must be the skill's own: one with another name on disk (a hard link) may be another skill's
script, one switched off, or a file outside every skill, and resolve() can't see the other name; a link is never
followed; and the file opened must be the one that was checked. A folder of scripts with no row is not an installed
skill and doesn't run. Both sources (the data folder's skill_scripts/<key>, and ~/.agents/skills), on a scratch HOME and
data folder, through the real executors. The sandbox only records what it was handed, so these run on every platform."""
import hashlib
import os
from pathlib import Path

import pytest

from server import config
from server.db import session as db_session
from server.db.models import SkillPack
from server.registry.executors import ReadSkillExecutor, RunPythonExecutor
from server.services import agent_skills, code_sandbox

pytestmark = pytest.mark.asyncio

CANARY = "FAKE-CANARY-not-a-secret-7f3a"          # what the file outside every skill holds
SKILL_MD = "---\nname: {k}\ndescription: Test skill {k}.\n---\n\n## Trigger\nWhen testing, run its script.\n"


def _hard_link(path: str) -> str:
    return f"skill file has another name on disk (a hard link), so Arslan won't run or read it: {path}"


def _link(path: str, kind: str = "file") -> str:
    return f"skill {kind} is a link (a symlink), so Arslan won't run or read it: {path}"


def _no_record(key: str) -> str:
    return f"skill not installed: {key}. Arslan has no record of it, so its scripts don't run."


def _pack(key: str, *, enabled: bool = True, category: str = "imported") -> SkillPack:
    return SkillPack(key=key, name=key, category=category, description="d", tier="safe", status="registered",
                     body="## Trigger\nx", enabled=enabled)


@pytest.fixture
async def env(execution_db, monkeypatch, tmp_path):
    from server.registry import executors
    monkeypatch.setattr(executors, "AsyncSessionLocal", execution_db)      # imported by name there
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "data" / "skill_scripts").mkdir(parents=True)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "outside.txt").write_text(CANARY + "\n")
    handed: list = []

    async def sandbox(code, *, extra_files=None, read_only_files=None):
        handed.append((code, extra_files, read_only_files))
        return {"ok": True, "stdout": "", "files": [], "sandboxed": True, "network_isolated": True}

    monkeypatch.setattr(code_sandbox, "run_python", sandbox)
    return {"scripts": tmp_path / "data" / "skill_scripts", "home": tmp_path / "home",
            "outside": tmp_path / "home" / "outside.txt", "handed": handed}


async def _add(*packs: SkillPack) -> None:
    async with db_session.AsyncSessionLocal() as db:
        db.add_all(packs)
        await db.commit()


async def _run(ref: str) -> dict:
    return await RunPythonExecutor().execute({"skill_script": ref})


def _refused(out: dict, error: str) -> None:
    assert out == {"ok": False, "external": False, "error": error}, out


def _swap_at_open(monkeypatch, target: Path, outside: Path, swapped_in: str) -> None:
    """What a writer racing the check could do: right before `target` is opened (after it was looked at), put another
    file in its place, once: a second name of `outside`, or a FIFO, which no one writes to (an open that waits for a
    writer would hold the server)."""
    real_open, want, done = os.open, target.resolve(), []

    def racing_open(path, flags, *args, **kwargs):
        if not done and Path(path).resolve() == want:
            done.append(path)
            if swapped_in == "fifo":
                os.mkfifo(target.with_name(".swap"))
            else:
                os.link(outside, target.with_name(".swap"))
            os.replace(target.with_name(".swap"), target)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", racing_open)


# ── the data folder: skill_scripts/<key> ────────────────────────────────────────────────────────────────────────────

async def test_a_second_name_of_an_off_skills_script_is_refused(env):
    """Under an on skill's key, an off skill's script (#786) isn't reached by a hard link: neither run as the entry
    nor handed over as a module the entry imports."""
    on, off = env["scripts"] / "on-a", env["scripts"] / "off-b"
    on.mkdir()
    off.mkdir()
    (off / "main.py").write_text("print('RAN-OFF-B')\n")
    (off / "helper.py").write_text("WORD = 'OFF-B'\n")
    await _add(_pack("on-a"), _pack("off-b", enabled=False))
    os.link(off / "main.py", on / "run.py")
    _refused(await _run("on-a/run.py"), _hard_link("on-a/run.py"))
    (on / "run.py").unlink()
    (on / "main.py").write_text("from helper import WORD\nprint('RAN-' + WORD)\n")
    os.link(off / "helper.py", on / "helper.py")
    _refused(await _run("on-a/main.py"), _hard_link("on-a/helper.py"))
    assert env["handed"] == []


@pytest.mark.parametrize("name", ["entry.py", "leak.py", "references/notes.md"])
async def test_a_second_name_of_a_file_outside_every_skill_is_refused(env, name):
    """As the entry, as a module beside it, or as a reference: the outside file's text never reaches the sandbox."""
    on = env["scripts"] / "on-a"
    (on / "references").mkdir(parents=True)
    (on / "main.py").write_text("print('on-a')\n")
    os.link(env["outside"], on / name)
    await _add(_pack("on-a"))
    _refused(await _run("on-a/entry.py" if name == "entry.py" else "on-a/main.py"), _hard_link(f"on-a/{name}"))
    assert env["handed"] == []


@pytest.mark.parametrize("kind", ["file", "folder"])
async def test_a_link_in_references_is_never_followed(env, kind):
    """#787 kept links out of the scripts handed over; references/, a file in it or the folder itself, was still
    followed."""
    on = env["scripts"] / "on-a"
    on.mkdir()
    (on / "main.py").write_text("print(open('references/notes.md').read())\n")
    if kind == "file":
        (on / "references").mkdir()
        (on / "references" / "notes.md").symlink_to(env["outside"])
    else:
        (env["home"] / "docs").mkdir()
        (env["home"] / "docs" / "notes.md").write_text(CANARY + "\n")
        (on / "references").symlink_to(env["home"] / "docs", target_is_directory=True)
    await _add(_pack("on-a"))
    _refused(await _run("on-a/main.py"), _link("on-a/references/notes.md" if kind == "file" else "on-a/references",
                                               kind))
    assert env["handed"] == []


async def test_a_plain_skill_still_runs_with_its_modules_and_references(env):
    on = env["scripts"] / "on-a"
    (on / "references").mkdir(parents=True)
    (on / "main.py").write_text("from helper import WORD\nprint(WORD)\n")
    (on / "helper.py").write_text("WORD = 'on-a'\n")
    (on / "references" / "notes.md").write_text("# notes\n")
    await _add(_pack("on-a"))
    out = await _run("on-a/main.py")
    assert out["ok"] is True, out
    assert env["handed"] == [("from helper import WORD\nprint(WORD)\n", {"helper.py": "WORD = 'on-a'\n"},
                              {"notes.md": "# notes\n"})]


@pytest.mark.parametrize("swapped_in", ["hard link", "fifo"])
async def test_a_file_swapped_after_its_check_is_refused(env, monkeypatch, swapped_in):
    on = env["scripts"] / "on-a"
    on.mkdir()
    (on / "main.py").write_text("print('on-a')\n")
    await _add(_pack("on-a"))
    _swap_at_open(monkeypatch, on / "main.py", env["outside"], swapped_in)
    _refused(await _run("on-a/main.py"),
             "skill file changed while Arslan opened it, so Arslan won't run or read it: on-a/main.py")
    assert env["handed"] == []


async def test_a_scripts_folder_with_no_record_does_not_run(env, monkeypatch):
    """A folder with no row (a removed skill's or a failed import's leftover) is not an installed skill: refused before
    any of its files is read."""
    ghost = env["scripts"] / "ghost"
    ghost.mkdir()
    (ghost / "main.py").write_text("print('RAN-GHOST')\n")

    def unread(ref):
        raise AssertionError(f"the files of a skill with no record were read: {ref}")

    monkeypatch.setattr(RunPythonExecutor, "_load_skill_script", staticmethod(unread))
    _refused(await _run("ghost/main.py"), _no_record("ghost"))
    assert env["handed"] == []


# ── read_skill's references in the data folder ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("how", ["hard link", "file link", "references link", "skill folder link"])
async def test_read_skill_reads_no_reference_through_a_link_or_a_second_name(env, how):
    """resolve() already kept a linked file inside references/, but not a second name of an outside file, nor a
    references/ or skill folder that is itself a link."""
    skill = env["scripts"] / "on-a"
    docs = env["home"] / "docs" / "references"
    docs.mkdir(parents=True)
    (docs / "notes.md").write_text(CANARY + "\n")
    if how == "skill folder link":
        skill.symlink_to(docs.parent, target_is_directory=True)
        expected = _link("on-a", "folder")
    elif how == "references link":
        skill.mkdir()
        (skill / "references").symlink_to(docs, target_is_directory=True)
        expected = _link("on-a/references", "folder")
    else:
        (skill / "references").mkdir(parents=True)
        if how == "hard link":
            os.link(env["outside"], skill / "references" / "notes.md")
            expected = _hard_link("on-a/references/notes.md")
        else:
            (skill / "references" / "notes.md").symlink_to(env["outside"])
            expected = _link("on-a/references/notes.md")
    await _add(_pack("on-a"))
    out = await ReadSkillExecutor().execute({"key": "on-a", "section": "references/notes.md"})
    assert out == {"ok": False, "external": False, "error": expected}, out


async def test_read_skill_still_reads_a_plain_reference(env):
    (env["scripts"] / "on-a" / "references").mkdir(parents=True)
    (env["scripts"] / "on-a" / "references" / "notes.md").write_text("# notes\n")
    await _add(_pack("on-a"))
    out = await ReadSkillExecutor().execute({"key": "on-a", "section": "references/notes.md"})
    assert out["ok"] is True and out["body"] == "# notes\n", out


# ── ~/.agents/skills (CAP6a) ────────────────────────────────────────────────────────────────────────────────────────

def _place(env, key: str, **files: str) -> Path:
    folder = env["home"] / ".agents" / "skills" / key
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_MD.format(k=key))
    for rel, text in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text)
    return folder


@pytest.mark.parametrize("ref", ["on-a/run.py", "on-a/main.py"])
async def test_a_folder_skill_holding_a_second_name_has_no_card_and_does_not_run(env, ref):
    """Its card listed only the files' names, and the scan found nothing in them, so a yes pinned another skill's
    script, or an outside file, as this skill's own. Now it has no card; one approved before this check is switched off
    at its next run."""
    off = _place(env, "off-b", **{"scripts/main.py": "print('RAN-OFF-B')\n"})
    on = _place(env, "on-a", **{"scripts/main.py": "print(open('references/notes.md').read())\n"})
    os.link(off / "scripts" / "main.py", on / "scripts" / "run.py")      # another skill's script
    (on / "references").mkdir()
    os.link(env["outside"], on / "references" / "notes.md")              # a file in no skill's folder
    with pytest.raises(agent_skills.Unreadable, match="another name on disk"):
        agent_skills.card("on-a")
    # As an approval from before this check left it: the row on, and the hash of every file kept.
    await _add(_pack("on-a", category="other-tool"), _pack("off-b", enabled=False, category="other-tool"))
    agent_skills.record("on-a", by=agent_skills.OTHER, files={
        p.relative_to(on).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in on.rglob("*") if p.is_file()})
    _refused(await _run(ref), f"skill on-a: {agent_skills.CHANGED}")
    assert env["handed"] == []
    async with db_session.AsyncSessionLocal() as db:
        assert (await db.get(SkillPack, "on-a")).enabled is False


@pytest.mark.parametrize("swapped_in", ["hard link", "fifo"])
async def test_a_folder_file_swapped_after_its_check_is_unreadable(env, monkeypatch, swapped_in):
    """The same race in ~/.agents/skills: what the card shows and a yes records is the file that was looked at."""
    folder = _place(env, "on-a", **{"references/notes.md": "# notes\n"})
    _swap_at_open(monkeypatch, folder / "references" / "notes.md", env["outside"], swapped_in)
    with pytest.raises(agent_skills.Unreadable, match="changed while it was read"):
        agent_skills.read_folder("on-a")


async def test_an_install_cut_short_before_its_row_does_not_run(env):
    """skill_import.install_prepared writes the folder and keeps its hashes, then makes the row. Stopped in between,
    the folder reads as approved, with no record of the skill."""
    folder = env["home"] / ".agents" / "skills" / "ghost"
    folder.mkdir(parents=True)
    files = agent_skills.write_new(folder, {"SKILL.md": SKILL_MD.format(k="ghost"),
                                            "scripts/main.py": "print('RAN-GHOST')\n"})
    agent_skills.record("ghost", by=agent_skills.ARSLAN, files=files)
    _refused(await _run("ghost/main.py"), _no_record("ghost"))
    assert env["handed"] == []
