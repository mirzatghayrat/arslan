"""0.1.61 §C2: a skill's folder is copied whole and safely — regular files only, every path
inside the folder, size caps, the executable bit, staged then swapped, replaced folders to the
Trash."""
from __future__ import annotations

import os
import stat

import pytest

from server.services import skill_files
from tests.server.skill_archives import COMMIT, case_insensitive, tarball


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "data"))
    trashed = []
    monkeypatch.setattr(skill_files, "_trash", lambda path: trashed.append(path) or path.rename(
        tmp_path / f"trashed-{len(trashed)}"))
    return trashed


def _everything(path: str) -> bool:
    return True


def _staging_left() -> list[str]:
    root = skill_files.skills_root()
    return [p.name for p in root.iterdir() if p.name.startswith(".staging-")] if root.exists() else []


def test_read_archive_names_the_commit_and_keeps_only_what_was_asked():
    archive = skill_files.read_archive(tarball({"skills/a/SKILL.md": "---\nname: a\n---\nx",
                                                "skills/a/big.bin": b"\0" * 10, "README.md": "r"}),
                                       keep=lambda p: p.startswith("skills/a/"))
    assert archive.commit == COMMIT
    assert archive.text("skills/a/SKILL.md").startswith("---")
    assert archive.entries["README.md"].data is None            # listed, not read
    assert archive.skill_mds() == ["skills/a/SKILL.md"]
    assert archive.skill_mds("skills/b") == []


def test_read_archive_refuses_what_is_not_an_archive_or_too_big(monkeypatch):
    with pytest.raises(skill_files.BadArchive):
        skill_files.read_archive(b"not a tarball", keep=_everything)
    monkeypatch.setattr(skill_files, "MAX_UNPACKED_BYTES", 5)
    with pytest.raises(skill_files.BadArchive, match="unpacks"):
        skill_files.read_archive(tarball({"a.txt": "0123456789"}), keep=_everything)


def test_links_devices_and_escaping_paths_are_skipped_and_named(data):
    archive = skill_files.read_archive(tarball({
        "s/SKILL.md": "body", "s/scripts/run.py": ("exec", "print(1)"),
        "s/evil": ("link", "/Users/someone/.ssh/id_rsa"), "s/hard": ("hardlink", "s/SKILL.md"),
        "s/pipe": ("fifo",), "s/../outside.txt": "no", "s/a\\b.txt": "no"}), keep=_everything)
    staged = skill_files.stage(archive, "s")
    assert set(staged.files) == {"SKILL.md", "scripts/run.py"}
    assert {"evil", "hard", "pipe", "../outside.txt", "a\\b.txt"} <= set(staged.skipped)
    assert not (staged.path / "evil").exists() and not (staged.path.parent / "outside.txt").exists()
    skill_files.discard(staged)


def test_the_executable_bit_is_kept_and_nothing_else_of_the_mode(data):
    archive = skill_files.read_archive(tarball({"s/run.sh": ("exec", "#!/bin/sh\necho hi\n"),
                                                "s/notes.md": "n", "s/suid": ("mode", 0o4755, "x")}),
                                       keep=_everything)
    staged = skill_files.stage(archive, "s")
    modes = {name: stat.S_IMODE(os.stat(staged.path / name).st_mode) for name in ("run.sh", "notes.md", "suid")}
    assert modes == {"run.sh": 0o755, "notes.md": 0o644, "suid": 0o755}
    skill_files.discard(staged)


def test_two_names_that_differ_only_by_case_keep_the_first(data, tmp_path):
    archive = skill_files.read_archive(tarball({"s/README.md": "first", "s/readme.md": "second"}),
                                       keep=_everything)
    staged = skill_files.stage(archive, "s")
    assert (staged.path / "README.md").read_text() == "first"
    if case_insensitive(staged.path):
        assert "readme.md" in staged.skipped and "readme.md" not in staged.files
    else:
        assert {"README.md", "readme.md"} <= set(staged.files)
    skill_files.discard(staged)


def test_over_the_caps_nothing_is_copied(data, monkeypatch):
    archive = skill_files.read_archive(tarball({f"s/f{i}.txt": "x" for i in range(4)}), keep=_everything)
    monkeypatch.setattr(skill_files, "MAX_FOLDER_FILES", 3)
    with pytest.raises(skill_files.FolderTooLarge):
        skill_files.stage(archive, "s")
    monkeypatch.setattr(skill_files, "MAX_FOLDER_FILES", 2000)
    monkeypatch.setattr(skill_files, "MAX_FOLDER_BYTES", 3)
    with pytest.raises(skill_files.FolderTooLarge):
        skill_files.stage(archive, "s")
    assert _staging_left() == []


def _staged_with(text):
    return skill_files.stage(skill_files.read_archive(tarball({"s/SKILL.md": text}), keep=_everything), "s")


def _leftovers() -> list[str]:
    return sorted(p.name for p in skill_files.skills_root().iterdir() if p.name.startswith("."))


def test_swap_in_replaces_and_swap_back_restores(data):
    assert skill_files.swap_in(_staged_with("one"), "handoff") is None
    aside = skill_files.swap_in(_staged_with("two"), "handoff")
    assert (skill_files.folder_for("handoff") / "SKILL.md").read_text() == "two"
    assert aside is not None and aside.name.startswith(".old-handoff-") and (aside / "SKILL.md").read_text() == "one"
    skill_files.swap_back("handoff", aside)                   # the database write failed
    assert (skill_files.folder_for("handoff") / "SKILL.md").read_text() == "one"
    assert data == [] and _leftovers() == []                  # the new copy was Arslan's own: deleted
    skill_files.retire(None)
    assert data == []


def test_swap_back_never_needs_the_trash(data, monkeypatch):
    skill_files.swap_in(_staged_with("one"), "handoff")
    aside = skill_files.swap_in(_staged_with("two"), "handoff")

    def unreachable(path):
        raise PermissionError("the Trash cannot be reached")
    monkeypatch.setattr(skill_files, "_trash", unreachable)
    skill_files.swap_back("handoff", aside)
    assert (skill_files.folder_for("handoff") / "SKILL.md").read_text() == "one" and _leftovers() == []


def test_a_trash_that_cannot_be_reached_leaves_the_folder(data, monkeypatch, tmp_path):
    folder = tmp_path / "data" / "skills" / ".old-handoff-1a2b3c4d"
    folder.mkdir(parents=True)

    def unreachable(path):
        raise PermissionError("the Trash cannot be reached")
    monkeypatch.setattr(skill_files, "_trash", unreachable)
    skill_files.retire(folder)                                # logged, never raised
    assert folder.is_dir()


def test_the_trash_shows_a_visible_name(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    folder = tmp_path / ".old-handoff-1a2b3c4d"
    folder.mkdir()
    skill_files._trash(folder)
    assert (tmp_path / "home" / ".Trash" / "Arslan capability skill handoff (replaced)").is_dir()


def test_a_file_where_a_folder_is_needed_is_skipped(data):
    archive = skill_files.read_archive(tarball({"s/a": "x", "s/a/b/c.md": "y", "s/SKILL.md": "m"}), keep=_everything)
    staged = skill_files.stage(archive, "s")
    assert set(staged.files) == {"SKILL.md", "a"} and "a/b/c.md" in staged.skipped
    skill_files.discard(staged)


def test_folder_for_refuses_what_is_not_a_key(data):
    for bad in ("", "../x", ".staging-1", "Has Caps", "a/b"):
        with pytest.raises(ValueError):
            skill_files.folder_for(bad)


def test_listing_checksums_scripts_and_reading_stay_inside_the_folder(data, tmp_path):
    folder = tmp_path / "skill"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text("body")
    (folder / "scripts" / "run.py").write_text("print(1)")
    (folder / ".DS_Store").write_text("x")
    (tmp_path / "secret").mkdir()
    (tmp_path / "secret" / "id.txt").write_text("hush")
    (folder / "out").symlink_to(tmp_path / "secret")      # a link that leads out of the folder
    shown, total = skill_files.list_files(folder)
    assert shown == ["SKILL.md", "scripts/run.py"] and total == 2
    assert set(skill_files.checksums(folder)) == {"SKILL.md", "scripts/run.py"}
    assert skill_files.has_scripts(folder) and not skill_files.has_scripts(tmp_path / "none")
    assert skill_files.read_text(folder, "scripts/run.py", limit=100) == "print(1)"
    for escape in ("../skill/SKILL.md", "/etc/hosts", "out/id.txt", ""):
        assert skill_files.read_text(folder, escape, limit=100) is None, escape


def test_placeholders_become_the_folder(tmp_path):
    body = "python3 ${CLAUDE_SKILL_DIR}/a.py; ${SKILL_DIR}/b; {baseDir}/c"
    folder = tmp_path / "App Support" / "k"
    assert skill_files.substitute(body, folder) == f"python3 {folder}/a.py; {folder}/b; {folder}/c"


def test_stage_texts_writes_skill_md_and_makes_a_shebang_script_executable(data):
    staged = skill_files.stage_texts({"scripts/run.sh": "#!/bin/sh\necho hi\n", "notes.md": "n"},
                                     skill_md="---\nname: x\ndescription: d\n---\nbody")
    assert set(staged.files) == {"SKILL.md", "scripts/run.sh", "notes.md"}
    assert stat.S_IMODE(os.stat(staged.path / "scripts" / "run.sh").st_mode) == 0o755
    skill_files.discard(staged)
    with pytest.raises(ValueError):
        skill_files.stage_texts({"../x.sh": "no"}, skill_md="b")
    assert _staging_left() == []


def test_stage_tree_copies_regular_files_and_skips_links(data, tmp_path):
    src = tmp_path / "seed"
    (src / "scripts").mkdir(parents=True)
    (src / "SKILL.md").write_text("b")
    (src / "scripts" / "cli.py").write_text("print(1)")
    os.chmod(src / "scripts" / "cli.py", 0o755)
    (src / "scripts" / "link").symlink_to(src / "SKILL.md")
    staged = skill_files.stage_tree(src)
    assert set(staged.files) == {"SKILL.md", "scripts/cli.py"} and "scripts/link" in staged.skipped
    assert stat.S_IMODE(os.stat(staged.path / "scripts" / "cli.py").st_mode) == 0o755
    skill_files.discard(staged)


def test_changes_count_files_and_show_the_skill_md_diff():
    out = skill_files.changes({"SKILL.md": "a", "old.py": "o", "same.md": "s"},
                              {"SKILL.md": "b", "new.py": "n", "same.md": "s"}, "line one\n", "line two\n")
    assert (out["added"], out["removed"], out["changed"], out["files_changed"]) == (
        ["new.py"], ["old.py"], ["SKILL.md"], 3)
    assert "-line one" in out["skill_md_diff"] and "+line two" in out["skill_md_diff"]
