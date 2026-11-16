"""A command that moves files says so (L7-7 bench, T11 r2; the user, via ⓪Plan).

The user declined `find … -delete` and asked for the .bak files to be moved to a trash folder. The model ran
`mkdir -p trash && find … -exec mv {} trash/ \;`: exit 0, no output. The result said only "exit 0", and the model
wrote that nothing was deleted and "the files are still there". Now a run_command whose `mv` names a destination folder
lists that folder before and after the command and reports what is new there: what the folder shows, not a guess.
"""
import os
from pathlib import Path

import pytest

from server.registry.executors import EXECUTORS

run = EXECUTORS["run_command"].execute


@pytest.fixture
def own_folder(execution_db):
    return Path(os.environ["ARSLAN_DEFAULT_WORKSPACE"])


@pytest.fixture
def work(own_folder):
    folder = own_folder / "workspace"
    (folder / "notes").mkdir(parents=True, exist_ok=True)
    for name in ("data.csv.bak", "report.md.bak", "notes/todo.txt.bak", "keep.md"):
        (folder / name).write_text("x")
    return folder


async def test_the_t11_move_to_a_trash_folder_says_how_many_and_where(work):
    trash = work / "trash"
    r = await run({"command": f"mkdir -p '{trash}' && find '{work}' -type f -name '*.bak' -not -path '*/trash/*' "
                              f"-exec mv {{}} '{trash}/' \;"})
    assert r["ok"] is True and r["exit_code"] == 0
    assert r["moved"] == f"3 new item(s) in {trash.resolve()} after the command: data.csv.bak, report.md.bak, todo.txt.bak"
    assert r["moved"] in r["summary"]


@pytest.mark.parametrize("command", ["mv data.csv.bak report.md.bak bin/", "mv -f data.csv.bak report.md.bak bin",
                                     "cd . && mv data.csv.bak report.md.bak ./bin"])
async def test_plain_mv_forms_into_a_folder(work, command):
    (work / "bin").mkdir()
    (work / "bin" / "old.txt").write_text("already there")          # not counted: it was there before
    r = await run({"command": f"cd '{work}' && {command}"})
    assert r["moved"] == f"2 new item(s) in {(work / 'bin').resolve()} after the command: data.csv.bak, report.md.bak"


@pytest.mark.parametrize("command", [
    "mv keep.md kept.md",                         # a rename: the destination is not a folder
    "mv missing.bak bin/",                        # nothing moved: the command failed
    'mv data.csv.bak "$HOME/bin/"',               # the shell picks the destination: not judged
    "cp data.csv.bak bin/",                       # a copy is not a move
    "echo mv data.csv.bak bin/",                  # the word in an argument
    "ls",
])
async def test_no_move_report_when_nothing_was_moved_or_the_destination_is_not_known(work, command):
    (work / "bin").mkdir()
    r = await run({"command": f"cd '{work}' && {command}"})
    assert "moved" not in r and "moved" not in r["summary"]


async def test_many_items_are_listed_up_to_ten(work):
    for i in range(14):
        (work / f"f{i:02d}.bak").write_text("x")
    (work / "t").mkdir()
    r = await run({"command": f"cd '{work}' && mv f*.bak t/"})
    assert r["moved"].startswith(f"14 new item(s) in {(work / 't').resolve()} after the command: f00.bak, f01.bak")
    assert r["moved"].endswith("f09.bak, …")


async def test_a_folder_outside_the_working_folder_is_never_listed(work, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    r = await run({"command": f"cd '{work}' && mv data.csv.bak '{outside}/'"})
    assert "moved" not in r


async def test_after_a_cd_the_shell_picks_nothing_is_judged(work):
    (work / "bin").mkdir()
    r = await run({"command": f"cd '{work}' && cd \"$PWD\" && mv data.csv.bak bin/"})
    assert "moved" not in r


# -- which folders are read: unit level ---------------------------------------------------------------------------

@pytest.mark.parametrize("command,want", [
    ("mv a b trash/", ["trash"]),
    ("find . -name '*.bak' -exec mv {} trash/ \;", ["trash"]),
    ("cd sub && mv a ../trash", ["trash"]),
    ("mv a /elsewhere/", []),                     # outside the working folder: never listed
    ("mv a ../../out/", []),
    ("echo mv a trash/", []),                     # not a command position
    ("cd \"$PWD\" && mv a trash/", []),           # the shell picks the folder: stop
    ('mv a "$HOME/trash"', []),
    ("mv a trash*", []),
    ("mv a", []),                                 # one operand: no destination
    ("mv -f a b", ["b"]),                         # a rename's destination is read; only a folder reports
])
def test_destinations(tmp_path, command, want):
    from server.services import move_report
    (tmp_path / "sub").mkdir()
    got = move_report.destinations(command, tmp_path)
    assert got == [(tmp_path / w).resolve() for w in want]



# -- #982 review round 1 ---------------------------------------------------------------------------------------------

async def test_the_exact_t11_glob_form(work):
    r = await run({"command": f"cd '{work}' && mkdir -p trash && mv *.bak trash/"})
    assert r["moved"] == f"2 new item(s) in {(work / 'trash').resolve()} after the command: data.csv.bak, report.md.bak"


@pytest.fixture
def private(tmp_path):
    """A folder outside the working folder whose names must never be listed (stands in for ~/.ssh)."""
    folder = tmp_path / "private"
    (folder / "trash").mkdir(parents=True)
    for name in ("id_secret", "trash/inner_secret"):
        (folder / name).write_text("x")
    return folder


async def test_a_symlink_the_command_makes_is_never_followed(work, private):
    r = await run({"command": f"cd '{work}' && ln -s '{private}' trash && mv nope.bak trash/"})
    assert "moved" not in r and "secret" not in r["summary"]
    r = await run({"command": f"cd '{work}' && ln -s '{private}' sub && cd sub && mv nope.bak trash/"})
    assert "moved" not in r and "secret" not in r["summary"]


async def test_a_folder_rename_is_not_reported_as_a_move(work):
    r = await run({"command": f"cd '{work}' && mv notes backup"})
    assert r["ok"] and (work / "backup" / "todo.txt.bak").exists()
    assert "moved" not in r
    r = await run({"command": f"cd '{work}' && mv back* again"})           # a glob source: the same
    assert r["ok"] and "moved" not in r


async def test_names_with_control_characters_are_escaped(work):
    (work / "a\nb.bak").write_text("x")
    (work / "t").mkdir()
    r = await run({"command": f"cd '{work}' && mv a*b.bak t/"})
    assert r["moved"].endswith("after the command: a\\x0ab.bak") and "\n" not in r["summary"]


def test_a_full_folder_or_many_folders_are_not_read(tmp_path, monkeypatch):
    from server.services import move_report
    monkeypatch.setattr(move_report, "FOLDER_MAX", 2)
    (tmp_path / "t").mkdir()
    for name in "abc":
        (tmp_path / "t" / name).write_text("x")
    assert move_report._listing(tmp_path.resolve(), (tmp_path / "t").resolve()) is None
    command = " && ".join(f"mv a d{i}/" for i in range(9))
    assert len(move_report.destinations(command, tmp_path)) == move_report.FOLDERS_MAX
