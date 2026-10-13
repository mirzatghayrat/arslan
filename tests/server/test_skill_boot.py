"""0.1.61 §C2: imports from before 0.1.61 move into <data>/skills/<key>/, the two bundled seeds
that carry scripts get their folder, their text points at scripts that exist, and a start tidies
what a crash in the middle of a swap left — deciding by the database (the folder a committed row
describes is the live one), never by a folder's name, and only ever to the Trash."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import shutil
import uuid
from pathlib import Path

import pytest

from server.db.models import CapabilitySource, SkillPack
from server.services import skill_boot, skill_files, skill_import
from tests.server.skill_archives import COMMIT, tarball

SEEDS = Path(__file__).resolve().parents[2] / "arslan" / "spawn" / "seeds"
OLD_BODY = ("> Imported verbatim from https://github.com/example-org/example-skills at 0123456789ab (MIT) on "
            "2026-09-01.\n\n# Handoff\nSteps.\n\n## Bundled scripts\nRun inside the sandbox via the run_python "
            "tool with {\"skill_script\": \"handoff/<file>\"}:\n- `handoff/run.py`\n\n## Bundled references\n"
            "Reference docs shipped with this skill.\n- `references/a.md`")
REPO = "example-org/example-skills"
C1, C2 = COMMIT, "fedcba9876543210fedcba9876543210fedcba98"


def skill_md(version: int) -> str:
    return f"---\nname: handoff\ndescription: Hand work over, version {version}.\n---\n\n# Handoff {version}\nSteps.\n"


def v(version: int) -> dict[str, str]:
    """One skill of a repository, in a subfolder: SKILL.md, a script and a reference."""
    return {"skills/handoff/SKILL.md": skill_md(version),
            "skills/handoff/scripts/run.py": f"print({version})\n",
            "skills/handoff/references/a.md": f"# ref {version}\n"}


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "data"))
    trashed = []
    monkeypatch.setattr(skill_files, "_trash", lambda path: trashed.append(path.name) or path.rename(
        tmp_path / f"trash-{len(trashed)}"))
    return tmp_path / "data", trashed


def github(monkeypatch, files, commit):
    """GitHub as the importer meets it: the repository's metadata and its archive."""
    async def fetch_repo(owner, repo):
        return {"full_name": f"{owner}/{repo}", "html_url": f"https://github.com/{owner}/{repo}",
                "stars": 10, "forks": 1, "license": "MIT", "pushed_days": 1, "description": "", "topics": []}

    async def fetch_archive(owner, repo, ref):
        return tarball(files, commit=commit)
    monkeypatch.setattr(skill_import.github_eval, "fetch_repo", fetch_repo)
    monkeypatch.setattr(skill_import, "_fetch_archive", fetch_archive)
    skill_import._archive_cache.clear()


async def do_import(monkeypatch, version: int) -> dict:
    github(monkeypatch, v(version), C1 if version == 1 else C2)
    return await skill_import.import_skill(REPO, "skills/handoff/SKILL.md")


def put(folder: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text)
    return folder


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def leftovers(root: Path) -> list[str]:
    skills = root / "skills"
    return sorted(p.name for p in skills.iterdir() if p.name.startswith(".")) if skills.is_dir() else []


def tree(folder: Path) -> dict[str, str]:
    return skill_files.checksums(folder)


async def row_of(execution_db, key: str) -> SkillPack | None:
    async with execution_db() as db:
        return await db.get(SkillPack, key)


async def commit_import(execution_db, key: str, files: dict[str, str], *, prefix: str = "skills/x/",
                        origin: str = "imported") -> None:
    """A committed import row and its dossier, as `_record_import` writes them: the dossier names
    every file by its path in the repository (`prefix` + the path in the skill's folder)."""
    async with execution_db() as db:
        source = CapabilitySource(id=uuid.uuid4().hex, owner_id="local", kind="skill", name=key,
                                  candidate_id=f"github:{REPO}:{prefix}SKILL.md", needs={}, grants={},
                                  files={prefix + rel: sha(text) for rel, text in files.items()},
                                  state="installed", skill_key=key)
        db.add(source)
        db.add(SkillPack(key=key, name=key, category="imported", description="d", tier="safe",
                         status="registered", body="# live", origin=origin, source_id=source.id,
                         folder=str(skill_files.folder_for(key))))
        await db.commit()


# ── the old imports move ───────────────────────────────────────────────────────

async def test_an_old_import_moves_into_its_folder_once(execution_db, data):
    root, trashed = data
    old = root / "skill_scripts" / "handoff"
    (old / "references").mkdir(parents=True)
    (old / "run.py").write_text("print(1)\n")
    (old / "references" / "a.md").write_text("# ref\n")
    (old / "evil").symlink_to("/etc/hosts")
    async with execution_db() as db:
        db.add(SkillPack(key="handoff", name="handoff", category="imported", description="d", tier="safe",
                         status="registered", body=OLD_BODY))
        await db.commit()
    assert await skill_boot.migrate_legacy_imports() == ["handoff"]
    new = skill_files.folder_for("handoff")
    assert (new / "scripts" / "run.py").read_text() == "print(1)\n"
    assert (new / "references" / "a.md").exists() and not (new / "scripts" / "evil").exists()
    assert trashed == ["handoff"] and not (root / "skill_scripts").exists()
    row = await row_of(execution_db, "handoff")
    assert row.folder == str(new) and row.origin == "imported"
    assert "Bundled scripts" not in row.body and "run_python" not in row.body and row.body.endswith("Steps.")
    assert await skill_boot.migrate_legacy_imports() == []          # idempotent


async def test_booting_twice_changes_nothing_the_second_time(execution_db, data):
    root, trashed = data
    old = root / "skill_scripts" / "handoff"
    old.mkdir(parents=True)
    (old / "run.py").write_text("print(1)\n")
    async with execution_db() as db:
        db.add(SkillPack(key="handoff", name="handoff", category="imported", description="d", tier="safe",
                         status="registered", body=OLD_BODY))
        await db.commit()
    first = await skill_boot.run()
    assert first == {"tidied": [], "moved": ["handoff"], "installed": []}
    folder, row_then = skill_files.folder_for("handoff"), await row_of(execution_db, "handoff")
    snapshot = (tree(folder), sorted(p.name for p in (root / "skills").iterdir()), len(trashed))
    assert await skill_boot.run() == {"tidied": [], "moved": [], "installed": []}
    row_now = await row_of(execution_db, "handoff")
    assert (tree(folder), sorted(p.name for p in (root / "skills").iterdir()), len(trashed)) == snapshot
    assert (row_now.folder, row_now.body, row_now.origin) == (row_then.folder, row_then.body, row_then.origin)


async def test_a_move_a_crash_interrupted_is_finished_at_the_next_start(execution_db, data):
    root, trashed = data
    old = root / "skill_scripts" / "handoff"
    old.mkdir(parents=True)
    (old / "run.py").write_text("print(1)\n")
    new = skill_files.folder_for("handoff")
    (new / "scripts").mkdir(parents=True)                       # the folder moved, the row did not
    (new / "scripts" / "run.py").write_text("print(1)\n")
    async with execution_db() as db:
        db.add(SkillPack(key="handoff", name="handoff", category="imported", description="d", tier="safe",
                         status="registered", body=OLD_BODY))
        await db.commit()
    assert await skill_boot.migrate_legacy_imports() == ["handoff"]
    row = await row_of(execution_db, "handoff")
    assert row.folder == str(new) and "run_python" not in row.body and trashed == ["handoff"]


async def test_a_move_that_died_after_staging_is_tidied_and_then_finished(execution_db, data, monkeypatch):
    root, trashed = data
    old = root / "skill_scripts" / "handoff"
    old.mkdir(parents=True)
    (old / "run.py").write_text("print(1)\n")
    async with execution_db() as db:
        db.add(SkillPack(key="handoff", name="handoff", category="imported", description="d", tier="safe",
                         status="registered", body=OLD_BODY))
        await db.commit()
    with monkeypatch.context() as crash:                         # the process died after the copy was staged
        def died(*args, **kwargs):
            raise RuntimeError("killed")
        crash.setattr(skill_files, "swap_in", died)
        crash.setattr(skill_files, "discard", lambda staged: None)
        out = await skill_boot.run()
    assert out["moved"] == [] and (old / "run.py").exists() and len(leftovers(root)) == 1
    again = await skill_boot.run()
    assert len(again["tidied"]) == 1 and again["moved"] == ["handoff"]
    assert leftovers(root) == [] and (skill_files.folder_for("handoff") / "scripts" / "run.py").exists()
    assert trashed[0].startswith(".staging-") and trashed[1] == "handoff"


async def test_a_trash_that_cannot_be_reached_leaves_the_old_import_and_it_is_not_called_moved(
        execution_db, data, monkeypatch):
    root, trashed = data
    old = root / "skill_scripts" / "handoff"
    old.mkdir(parents=True)
    (old / "run.py").write_text("print(1)\n")
    async with execution_db() as db:
        db.add(SkillPack(key="handoff", name="handoff", category="imported", description="d", tier="safe",
                         status="registered", body=OLD_BODY))
        await db.commit()
    with monkeypatch.context() as down:
        def unreachable(path):
            raise OSError("Trash is on another volume")
        down.setattr(skill_files, "_trash", unreachable)
        assert await skill_boot.migrate_legacy_imports() == []
    new = skill_files.folder_for("handoff")
    assert (new / "scripts" / "run.py").exists() and (old / "run.py").exists()      # copied, not yet retired
    assert (await row_of(execution_db, "handoff")).folder == str(new)
    assert await skill_boot.migrate_legacy_imports() == ["handoff"]                # the next start finishes it
    assert not (root / "skill_scripts").exists() and trashed == ["handoff"]


async def test_one_old_import_that_cannot_move_never_stops_the_others(execution_db, data, monkeypatch):
    root, _ = data
    for key in ("aaa", "bbb"):
        (root / "skill_scripts" / key).mkdir(parents=True)
        (root / "skill_scripts" / key / "run.py").write_text("print(1)\n")
    real = skill_files.stage_files

    def broken_for_aaa(pairs):
        if any("aaa" in str(src) for _, src in pairs):
            raise OSError("disk full")
        return real(pairs)
    monkeypatch.setattr(skill_files, "stage_files", broken_for_aaa)
    out = await skill_boot.run()
    assert out["moved"] == ["bbb"] and (root / "skill_scripts" / "aaa" / "run.py").exists()
    assert sorted(out["installed"]) == []           # no seed rows in this database: nothing to install


async def test_a_row_that_is_not_an_import_keeps_its_folder_when_the_scripts_move(execution_db, data):
    root, trashed = data
    old = root / "skill_scripts" / "plan"
    old.mkdir(parents=True)
    (old / "run.py").write_text("print(1)\n")
    async with execution_db() as db:
        db.add(SkillPack(key="plan", name="plan", category="agents", description="d", tier="safe",
                         status="registered", body="# theirs", origin="agents", folder="/Users/x/.agents/skills/plan"))
        await db.commit()
    assert await skill_boot.migrate_legacy_imports() == ["plan"]       # the scripts move; the shared skill's row is not theirs
    row = await row_of(execution_db, "plan")
    assert (row.origin, row.folder, row.body) == ("agents", "/Users/x/.agents/skills/plan", "# theirs")


async def test_an_old_folder_with_nothing_to_copy_makes_no_new_folder(execution_db, data):
    root, trashed = data
    old = root / "skill_scripts" / "handoff"
    old.mkdir(parents=True)
    (old / "evil").symlink_to("/etc/hosts")
    assert await skill_boot.migrate_legacy_imports() == ["handoff"]
    assert not skill_files.folder_for("handoff").exists() and trashed == ["handoff"]


def test_the_old_lists_come_out_and_other_sections_stay():
    body = "# T\nintro\n\n## Bundled scripts\n- `k/a.py`\n\n## Steps\n1. go\n\n## Bundled references\n- `references/x.md`"
    assert skill_boot.strip_bundled_lists(body) == "# T\nintro\n\n## Steps\n1. go"


# ── the bundled seeds ──────────────────────────────────────────────────────────

async def test_the_bundled_seeds_with_scripts_get_their_folder_and_it_follows_the_app(execution_db, data):
    root, trashed = data
    from server.registry.seeder import seed_registry
    await seed_registry()
    assert sorted(await skill_boot.install_bundled()) == ["github-eval", "research"]
    research = skill_files.folder_for("research")
    assert (research / "scripts" / "research_cli.py").read_bytes() == (
        SEEDS / "research" / "scripts" / "research_cli.py").read_bytes()
    row, plain = await row_of(execution_db, "research"), await row_of(execution_db, "plan")
    assert (row.origin, row.folder) == ("bundled", str(research))
    assert (plain.origin, plain.folder) == ("bundled", None)            # a seed with no files has none
    assert await skill_boot.install_bundled() == []                     # the same files: nothing copied
    (research / "scripts" / "research_cli.py").write_text("stale")
    assert await skill_boot.install_bundled() == ["research"]          # differs from the app: copied again
    assert (research / "scripts" / "research_cli.py").read_bytes() == (
        SEEDS / "research" / "scripts" / "research_cli.py").read_bytes()
    # the copy it replaced is a person's folder as far as the disk can tell: to the Trash, never deleted
    assert [n for n in trashed if n.startswith(".old-research-")] and not leftovers(root)


async def test_an_install_that_fails_puts_everything_back(execution_db, data, monkeypatch):
    root, _ = data
    from server.registry.seeder import seed_registry
    await seed_registry()
    await skill_boot.install_bundled()
    research = skill_files.folder_for("research")
    (research / "scripts" / "research_cli.py").write_text("stale")

    async def database_down(key, folder):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(skill_boot, "_set_folder", database_down)
    assert await skill_boot.install_bundled() == []                   # logged, not raised: the boot goes on
    assert (research / "scripts" / "research_cli.py").read_text() == "stale"     # the folder as it was
    assert leftovers(root) == []


def test_the_two_seeds_point_at_scripts_that_exist():
    for key, script in (("research", "research_cli.py"), ("github-eval", "github_eval_cli.py")):
        md = (SEEDS / key / "SKILL.md").read_text()
        assert f'${{SKILL_DIR}}/scripts/{script}' in md and (SEEDS / key / "scripts" / script).is_file()
    assert "`outline <主题>`" not in (SEEDS / "research" / "SKILL.md").read_text()


async def test_a_skill_the_person_already_has_under_a_new_seeds_name_is_kept(execution_db, data):
    root, _ = data
    mine = skill_files.folder_for("research")
    (mine / "scripts").mkdir(parents=True)
    (mine / "scripts" / "mine.py").write_text("print('mine')\n")
    async with execution_db() as db:
        db.add(SkillPack(key="research", name="My research", category="imported", description="mine",
                         tier="safe", status="registered", body="> Imported verbatim from …\n\n# Mine",
                         origin="imported", folder=str(mine)))
        db.add(SkillPack(key="github-eval", name="GitHub check", category="method", description="mine too",
                         tier="safe", status="registered", body="# My own check", origin="saved"))
        await db.commit()
    from server.registry.seeder import seed_registry
    await seed_registry()
    assert await skill_boot.install_bundled() == []
    research, ge, plan = (await row_of(execution_db, "research"), await row_of(execution_db, "github-eval"),
                          await row_of(execution_db, "plan"))
    assert (research.origin, research.name, research.body.endswith("# Mine")) == ("imported", "My research", True)
    assert (ge.origin, ge.body) == ("saved", "# My own check") and plan.origin == "bundled"
    assert (mine / "scripts" / "mine.py").exists() and not (mine / "scripts" / "research_cli.py").exists()


async def test_a_seed_takes_its_name_back_from_a_shared_folder_skill(execution_db, data):
    async with execution_db() as db:
        db.add(SkillPack(key="plan", name="plan", category="agents", description="d", tier="safe",
                         status="registered", body="# theirs", origin="agents", folder="/Users/x/.agents/skills/plan",
                         scan={"level": "clean", "verdict": "clean", "findings": []}, text_sha256="0" * 64))
        await db.commit()
    from server.registry.seeder import seed_registry
    await seed_registry()
    plan = await row_of(execution_db, "plan")
    assert (plan.origin, plan.folder, plan.scan, plan.text_sha256) == ("bundled", None, None, None)


# ── stage_files ────────────────────────────────────────────────────────────────

def test_stage_files_takes_regular_files_to_their_new_place(data, tmp_path):
    src = tmp_path / "loose.py"
    src.write_text("print(2)\n")
    link = tmp_path / "link.py"
    link.symlink_to(src)
    staged = skill_files.stage_files([("scripts/loose.py", src), ("scripts/link.py", link)])
    assert set(staged.files) == {"scripts/loose.py"} and staged.skipped == ["scripts/link.py"]
    skill_files.discard(staged)


def test_stage_files_skips_what_a_skill_never_holds(data, tmp_path):
    good, junk, ds = tmp_path / "a.py", tmp_path / "b.py", tmp_path / "c"
    good.write_text("1")
    junk.write_text("2")
    ds.write_text("3")
    pipe = tmp_path / "pipe"
    os.mkfifo(pipe)                                            # opened for reading it would wait for a writer forever
    staged = skill_files.stage_files([("scripts/a.py", good), ("../escape.py", junk), ("scripts/.DS_Store", ds),
                                      ("scripts/pipe", pipe), ("scripts/gone.py", tmp_path / "gone.py")])
    assert set(staged.files) == {"scripts/a.py"}
    assert sorted(staged.skipped) == ["../escape.py", "scripts/.DS_Store", "scripts/gone.py", "scripts/pipe"]
    assert not (staged.path.parent / "escape.py").exists()
    skill_files.discard(staged)


def test_stage_files_refuses_a_folder_over_the_limit_and_leaves_no_scratch(data, tmp_path, monkeypatch):
    monkeypatch.setattr(skill_files, "MAX_FOLDER_FILES", 2)
    files = []
    for i in range(3):
        f = tmp_path / f"f{i}.py"
        f.write_text("x")
        files.append((f"scripts/f{i}.py", f))
    with pytest.raises(skill_files.FolderTooLarge):
        skill_files.stage_files(files)
    assert leftovers(tmp_path / "data") == []


# ── the boot and the backup ────────────────────────────────────────────────────

def test_the_boot_runs_the_skills_step_and_backups_carry_the_folders():
    from server import main
    from server.services import backup
    source = inspect.getsource(main.lifespan)
    assert "skill_boot.run()" in source
    assert source.index("seed_registry()") < source.index("skill_boot.run()") < source.index("scheduler.start()")
    assert "skills" in backup.ASSET_DIRS and "skill_scripts" in backup.ASSET_DIRS


async def test_the_boot_steps_run_in_order_and_one_failure_never_stops_the_next(monkeypatch):
    calls = []

    def step(name, *, fails=False):
        async def run():
            calls.append(name)
            if fails:
                raise RuntimeError(name)
            return [name]
        return run
    monkeypatch.setattr(skill_boot, "tidy", step("tidy", fails=True))
    monkeypatch.setattr(skill_boot, "migrate_legacy_imports", step("moved"))
    monkeypatch.setattr(skill_boot, "install_bundled", step("installed"))
    assert await skill_boot.run() == {"tidied": [], "moved": ["moved"], "installed": ["installed"]}
    assert calls == ["tidy", "moved", "installed"]


def test_a_backup_made_before_the_skills_folders_still_restores(tmp_path, monkeypatch):
    from server.services import backup
    from tests.server.test_backup import source
    old_layout = tuple(d for d in backup.ASSET_DIRS if d != "skills")
    data = source(tmp_path)
    (data / "skill_scripts" / "handoff").mkdir(parents=True)
    (data / "skill_scripts" / "handoff" / "run.py").write_text("print(1)\n")
    archive = tmp_path / "before.zip"
    with monkeypatch.context() as before:
        before.setattr(backup, "ASSET_DIRS", old_layout)
        backup.create(data, archive)
    restored = tmp_path / "restored-before"
    backup.restore(archive, restored)                                  # the app as it is now
    assert (restored / "skill_scripts" / "handoff" / "run.py").read_text() == "print(1)\n"
    assert (restored / "artifacts" / "result.csv").exists() and not (restored / "skills").exists()


def test_a_backup_now_carries_the_skill_folders(tmp_path):
    from server.services import backup
    from tests.server.test_backup import source
    data = source(tmp_path)
    put(data / "skills" / "handoff", {"SKILL.md": "x", "scripts/run.py": "print(1)\n", "references/a.md": "r"})
    archive = tmp_path / "now.zip"
    backup.create(data, archive)
    restored = tmp_path / "restored-now"
    backup.restore(archive, restored)
    assert tree(restored / "skills" / "handoff") == tree(data / "skills" / "handoff")


# ── what a crash left, tidied by the database ──────────────────────────────────

async def test_leftovers_of_a_crash_are_tidied_by_what_the_row_describes(execution_db, data):
    root, trashed = data
    skills = root / "skills"
    await commit_import(execution_db, "csv", {"SKILL.md": "csv"})
    put(skills / "csv", {"SKILL.md": "csv"})                                      # the live copy
    put(skills / ".old-csv-5e6f7a8b", {"SKILL.md": "an older csv"})               # moved aside once
    put(skills / ".new-csv-1a2b3c4d", {"SKILL.md": "a copy thrown away"})
    put(skills / ".staging-0123456789ab", {"SKILL.md": "half built"})
    put(skills / ".old-pdf-1a2b3c4d", {"SKILL.md": "pdf"})                        # no row: nobody's skill
    assert sorted(await skill_boot.tidy()) == [".new-csv-1a2b3c4d", ".old-csv-5e6f7a8b", ".old-pdf-1a2b3c4d",
                                               ".staging-0123456789ab"]
    assert sorted(trashed) == sorted([".new-csv-1a2b3c4d", ".old-csv-5e6f7a8b", ".old-pdf-1a2b3c4d",
                                      ".staging-0123456789ab"])
    assert sorted(p.name for p in skills.iterdir()) == ["csv"] and (skills / "csv" / "SKILL.md").read_text() == "csv"
    assert await skill_boot.tidy() == []                                          # nothing left to do


async def test_a_crash_after_the_copy_was_staged_leaves_the_live_folder_alone(execution_db, data, monkeypatch):
    root, trashed = data
    await do_import(monkeypatch, 1)
    live = skill_files.folder_for("handoff")
    before = tree(live)
    with monkeypatch.context() as crash:                         # killed right after the staged copy was built
        def died(*args, **kwargs):
            raise RuntimeError("killed")
        crash.setattr(skill_files, "swap_in", died)
        crash.setattr(skill_files, "discard", lambda staged: None)
        with pytest.raises(RuntimeError):
            await do_import(monkeypatch, 2)
    left = leftovers(root)
    assert len(left) == 1 and left[0].startswith(".staging-")
    assert await skill_boot.tidy() == left and trashed == left
    assert tree(live) == before and leftovers(root) == []
    assert (await row_of(execution_db, "handoff")).body.endswith("# Handoff 1\nSteps.")
    assert await skill_boot.tidy() == []


async def test_a_crash_between_the_two_renames_puts_the_old_folder_back(execution_db, data, monkeypatch):
    root, trashed = data
    await do_import(monkeypatch, 1)
    live = skill_files.folder_for("handoff")
    before = tree(live)
    staged = skill_files.stage_texts({"scripts/run.py": "print(2)\n"}, skill_md=skill_md(2))
    (live).rename(live.with_name(".old-handoff-1a2b3c4d"))        # swap_in's first rename, then killed
    assert not live.exists()
    assert sorted(await skill_boot.tidy()) == sorted([".old-handoff-1a2b3c4d", staged.path.name])
    assert tree(live) == before and leftovers(root) == []
    assert trashed == [staged.path.name]                           # only the unfinished new copy went
    assert await skill_boot.tidy() == []


async def test_a_crash_after_the_swap_and_before_the_commit_puts_the_old_folder_back(execution_db, data, monkeypatch):
    root, trashed = data
    await do_import(monkeypatch, 1)
    live = skill_files.folder_for("handoff")
    before = tree(live)
    with monkeypatch.context() as crash:                         # killed after the swap, before the row committed
        async def died(**kwargs):
            raise RuntimeError("killed")
        crash.setattr(skill_import, "_record_import", died)
        crash.setattr(skill_files, "swap_back", lambda key, aside: None)
        with pytest.raises(RuntimeError):
            await do_import(monkeypatch, 2)
    assert (live / "scripts" / "run.py").read_text() == "print(2)\n"       # the folder is version 2
    assert (await row_of(execution_db, "handoff")).body.endswith("# Handoff 1\nSteps.")   # the row is version 1
    assert len(leftovers(root)) == 1 and leftovers(root)[0].startswith(".old-handoff-")
    done = await skill_boot.tidy()
    assert len(done) == 1 and done[0].startswith(".old-handoff-")     # the old one put back, the new one moved off
    assert tree(live) == before and leftovers(root) == []
    assert len(trashed) == 1 and trashed[0].startswith(".new-handoff-")       # version 2 is in the Trash, not gone
    assert await skill_boot.tidy() == []


async def test_a_crash_after_the_commit_and_before_the_retire_keeps_the_new_folder(execution_db, data, monkeypatch):
    root, trashed = data
    await do_import(monkeypatch, 1)
    live = skill_files.folder_for("handoff")
    with monkeypatch.context() as crash:                         # killed after the row committed, before the Trash
        crash.setattr(skill_files, "retire", lambda path: None)
        await do_import(monkeypatch, 2)
    after = tree(live)
    assert (await row_of(execution_db, "handoff")).body.endswith("# Handoff 2\nSteps.")
    left = leftovers(root)
    assert len(left) == 1 and left[0].startswith(".old-handoff-")
    assert await skill_boot.tidy() == left and trashed == left
    assert tree(live) == after and (live / "scripts" / "run.py").read_text() == "print(2)\n"
    assert (await row_of(execution_db, "handoff")).body.endswith("# Handoff 2\nSteps.")
    assert await skill_boot.tidy() == []


async def test_an_interrupted_swap_back_finishes_with_the_old_folder_in_place(execution_db, data):
    root, trashed = data
    skills = root / "skills"
    await commit_import(execution_db, "csv", {"SKILL.md": "csv one", "scripts/a.py": "1"})
    put(skills / ".old-csv-1a2b3c4d", {"SKILL.md": "csv one", "scripts/a.py": "1"})     # the committed version
    put(skills / ".new-csv-5e6f7a8b", {"SKILL.md": "csv two", "scripts/a.py": "2"})     # the copy swap_back moved off
    assert sorted(await skill_boot.tidy()) == [".new-csv-5e6f7a8b", ".old-csv-1a2b3c4d"]
    assert (skills / "csv" / "scripts" / "a.py").read_text() == "1" and trashed == [".new-csv-5e6f7a8b"]


async def test_a_staged_copy_that_is_a_committed_rows_live_copy_is_swapped_into_place(execution_db, data):
    root, trashed = data
    skills = root / "skills"
    await commit_import(execution_db, "csv", {"SKILL.md": "csv", "scripts/a.py": "1"})
    put(skills / ".staging-0123456789ab", {"SKILL.md": "csv", "scripts/a.py": "1"})     # the row's folder is missing
    put(skills / ".staging-abcdef012345", {"SKILL.md": "something else"})
    assert sorted(await skill_boot.tidy()) == [".staging-0123456789ab", ".staging-abcdef012345"]
    assert (skills / "csv" / "scripts" / "a.py").read_text() == "1" and trashed == [".staging-abcdef012345"]


async def test_a_staged_copy_never_replaces_a_folder_an_import_put_there_first(execution_db, data):
    root, trashed = data
    skills = root / "skills"
    await commit_import(execution_db, "csv", {"SKILL.md": "csv", "scripts/a.py": "1"})
    put(skills / ".staging-0123456789ab", {"SKILL.md": "csv", "scripts/a.py": "1"})     # the row's folder is missing...
    async with skill_files.key_lock("csv"):                          # ...an import holds its lock...
        task = asyncio.ensure_future(skill_boot.tidy())
        await asyncio.sleep(0.2)
        put(skills / "csv", {"SKILL.md": "csv", "scripts/a.py": "1", "references/new.md": "r"})   # ...and finishes first
    assert await asyncio.wait_for(task, 5) == [".staging-0123456789ab"]
    assert (skills / "csv" / "references" / "new.md").exists() and trashed == [".staging-0123456789ab"]


async def test_a_copy_set_aside_as_new_that_the_row_describes_takes_the_folders_place(execution_db, data):
    root, trashed = data
    skills = root / "skills"
    await commit_import(execution_db, "csv", {"SKILL.md": "csv", "scripts/a.py": "1"})
    put(skills / ".new-csv-5e6f7a8b", {"SKILL.md": "csv", "scripts/a.py": "1"})         # the folder itself is missing
    assert await skill_boot.tidy() == [".new-csv-5e6f7a8b"] and trashed == []
    assert (skills / "csv" / "scripts" / "a.py").read_text() == "1"


async def test_a_staged_copy_is_claimed_only_by_a_row_that_points_at_its_folder(execution_db, data):
    root, trashed = data
    skills = root / "skills"
    from server.registry.seeder import seed_registry
    await seed_registry()                                          # research is bundled, its folder not installed yet
    shutil.copytree(SEEDS / "research", skills / ".staging-0123456789ab")
    assert await skill_boot.tidy() == [".staging-0123456789ab"]
    assert not (skills / "research").exists() and trashed == [".staging-0123456789ab"]


async def test_nothing_a_row_describes_is_moved_when_no_copy_matches_it(execution_db, data):
    root, trashed = data
    skills = root / "skills"
    await commit_import(execution_db, "csv", {"SKILL.md": "csv", "scripts/a.py": "1"})
    put(skills / "csv", {"SKILL.md": "csv", "scripts/a.py": "edited by hand"})
    put(skills / ".old-csv-1a2b3c4d", {"SKILL.md": "another version"})
    assert await skill_boot.tidy() == [] and trashed == []                     # no proof: nothing is touched
    assert (skills / "csv" / "scripts" / "a.py").read_text() == "edited by hand"
    assert (skills / ".old-csv-1a2b3c4d").is_dir()


async def test_a_row_with_no_record_of_its_files_keeps_its_folder_and_gets_a_missing_one_back(execution_db, data):
    root, trashed = data
    skills = root / "skills"
    async with execution_db() as db:
        for key in ("notes", "memo"):
            db.add(SkillPack(key=key, name=key, category="x", description="d", tier="safe", status="registered",
                             body="# b", origin="saved", folder=str(skill_files.folder_for(key))))
        await db.commit()
    put(skills / "notes", {"SKILL.md": "new, unproven"})
    put(skills / ".old-notes-1a2b3c4d", {"SKILL.md": "old"})                   # which one is live cannot be told
    put(skills / ".old-memo-1a2b3c4d", {"SKILL.md": "the only copy"})          # memo's folder is gone
    assert await skill_boot.tidy() == [".old-memo-1a2b3c4d"]
    assert (skills / "memo" / "SKILL.md").read_text() == "the only copy" and trashed == []
    assert (skills / "notes" / "SKILL.md").read_text() == "new, unproven" and (skills / ".old-notes-1a2b3c4d").is_dir()


async def test_a_migrated_import_is_known_by_the_files_it_was_moved_with(execution_db, data):
    """The dossier of an import from before 0.1.61 names SKILL.md too; the moved folder never held it."""
    root, trashed = data
    skills = root / "skills"
    await commit_import(execution_db, "handoff", {"SKILL.md": "md", "scripts/run.py": "old", "references/a.md": "r"})
    put(skills / ".old-handoff-1a2b3c4d", {"scripts/run.py": "old", "references/a.md": "r"})     # as migrated
    put(skills / "handoff", {"SKILL.md": "md two", "scripts/run.py": "new"})                      # an update that never committed
    assert await skill_boot.tidy() == [".old-handoff-1a2b3c4d"]
    assert (skills / "handoff" / "scripts" / "run.py").read_text() == "old" and len(trashed) == 1


async def test_an_empty_folder_is_not_a_committed_rows_copy(execution_db, data):
    root, trashed = data
    skills = root / "skills"
    await commit_import(execution_db, "csv", {"SKILL.md": "csv"})
    (skills / ".staging-0123456789ab").mkdir(parents=True)
    assert await skill_boot.tidy() == [".staging-0123456789ab"]
    assert not (skills / "csv").exists() and trashed == [".staging-0123456789ab"]


async def test_a_bundled_rows_copy_is_the_one_that_matches_the_app(execution_db, data):
    root, trashed = data
    skills = root / "skills"
    from server.registry.seeder import seed_registry
    await seed_registry()
    await skill_boot.install_bundled()
    right = tree(skills / "research")
    put(skills / ".old-research-1a2b3c4d", {"SKILL.md": "an earlier app's copy"})
    assert await skill_boot.tidy() == [".old-research-1a2b3c4d"] and tree(skills / "research") == right
    # an interrupted install: the folder is not the app's, the one moved aside is
    (skills / "research").rename(skills / ".old-research-5e6f7a8b")
    put(skills / "research", {"SKILL.md": "half"})
    assert sorted(await skill_boot.tidy()) == [".old-research-5e6f7a8b"]
    assert tree(skills / "research") == right


async def test_tidy_waits_for_a_keys_lock_and_other_keys_never_wait(execution_db, data):
    root, trashed = data
    stray = root / "skills" / ".old-handoff-1a2b3c4d"
    put(stray, {"SKILL.md": "x"})
    async with skill_files.key_lock("other"):                       # a different key is busy: no wait
        task = asyncio.ensure_future(skill_boot.tidy())
        assert await asyncio.wait_for(task, 5) == [".old-handoff-1a2b3c4d"]
    put(stray, {"SKILL.md": "x"})
    async with skill_files.key_lock("handoff"):                     # an import of this key is in the middle of its swap
        task = asyncio.ensure_future(skill_boot.tidy())
        await asyncio.sleep(0.2)
        assert not task.done() and stray.is_dir()
    assert await asyncio.wait_for(task, 5) == [".old-handoff-1a2b3c4d"]


async def test_a_trash_that_cannot_be_reached_leaves_the_folders_for_the_next_start(execution_db, data, monkeypatch):
    root, trashed = data
    skills = root / "skills"
    put(skills / ".staging-0123456789ab", {"SKILL.md": "half"})
    put(skills / ".old-pdf-1a2b3c4d", {"SKILL.md": "pdf"})
    with monkeypatch.context() as down:
        def unreachable(path):
            raise OSError("Trash is on another volume")
        down.setattr(skill_files, "_trash", unreachable)
        assert await skill_boot.tidy() == []                          # nothing moved: nothing claimed
    assert len(leftovers(root)) == 2
    assert sorted(await skill_boot.tidy()) == [".old-pdf-1a2b3c4d", ".staging-0123456789ab"]


async def test_tidy_leaves_what_it_did_not_make_and_never_deletes(execution_db, data, monkeypatch):
    root, trashed = data
    skills = root / "skills"
    put(skills / "mine", {"SKILL.md": "a folder of the person's, no row"})
    put(skills / ".mine-notes", {"x": "a dot folder that is not Arslan's"})
    put(skills / ".old-", {"x": "not a key"})
    put(skills / ".old-Has-Caps-1a2b3c4d", {"x": "not a key"})
    put(skills / ".staging-notes", {"x": "not a staging name"})
    put(skills / ".old-csv-zzzzzzzz", {"x": "a suffix swap_in never writes"})
    put(skills / ".new-csv-1a2b3c", {"x": "a suffix swap_back never writes"})
    (skills / "loose.txt").write_text("a file")
    deletions = []
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: deletions.append(a))
    assert await skill_boot.tidy() == [] and deletions == [] and trashed == []
    assert sorted(p.name for p in skills.iterdir()) == sorted(
        ["mine", ".mine-notes", ".old-", ".old-Has-Caps-1a2b3c4d", ".staging-notes", ".old-csv-zzzzzzzz",
         ".new-csv-1a2b3c", "loose.txt"])


def test_what_tidy_trashes_has_a_name_a_person_can_find_in_finder():
    root = Path("/data/skills")
    assert skill_files._trash_name(root / ".old-csv-tidy-1a2b3c4d") == "skill csv-tidy (replaced)"
    assert skill_files._trash_name(root / ".new-csv-tidy-1a2b3c4d") == "skill csv-tidy (copy not kept)"
    assert skill_files._trash_name(root / ".staging-0123456789ab") == "skill (unfinished copy)"


async def test_nothing_to_tidy_without_a_skills_folder(data):
    assert await skill_boot.tidy() == []
