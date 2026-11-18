"""L7-5c: a judgement check whose named target the host's judge can't read as a file is a check Arslan can't verify.

The host's judge reads one named file (`task_validation._read_named`). Over anything else it failed every round as
`judged_file_unreadable` and the goal stopped blocked. The bench hit two shapes: T18's "the original invoices are
unchanged" named the invoices FOLDER, and T1's Reminders checks named the app ('提醒事项'), not a file. Drafting
varies between runs (one T1 draft flagged them, the next didn't), so the host flags them at drafting, as any other
check Arslan can't verify: Start asks the user to confirm them as their own.
"""
from __future__ import annotations

import pytest

from server.services import goal_mode
from server.services.goal_mode import GoalCheck, GoalSpec


def _judged(path: str, **kw) -> GoalCheck:
    return GoalCheck.model_validate({"id": "c1", "description": "The result is right", "kind": "judgement",
                                     "path": path, "by_user": True, **kw})


def _spec(*checks, saved: str = "ledger.csv") -> GoalSpec:
    first = GoalCheck.model_validate({"id": "c0", "description": "Ledger saved", "kind": "file_saved", "path": saved})
    return GoalSpec(objective="Do the task", checks=(first, *checks))


# -- flagged: the judge could never read it --------------------------------------------------------------------------

def test_t1_shape_a_bare_app_name_is_flagged():
    assert goal_mode.unverifiable(_spec(_judged("提醒事项"))) == ("c1",)
    assert goal_mode.unverifiable(_spec(_judged("Reminders"))) == ("c1",)
    assert goal_mode.unverifiable(_spec(_judged("Reminders.app"))) == ("c1",)     # an app bundle is no file either


def test_t18_shape_a_named_folder_is_flagged(tmp_path, monkeypatch):
    folder = tmp_path / "invoices"
    folder.mkdir()
    assert goal_mode.unverifiable(_spec(_judged(str(folder)))) == ("c1",)
    assert goal_mode.unverifiable(_spec(_judged(str(folder) + "/"))) == ("c1",)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert goal_mode.unverifiable(_spec(_judged("~/invoices"))) == ("c1",)
    assert goal_mode.unverifiable(_spec(_judged("invoices"))) == ("c1",)          # a bare folder name, relative


def test_a_folder_named_like_a_file_is_still_flagged(tmp_path):
    odd = tmp_path / "archive.d"
    odd.mkdir()
    assert goal_mode.unverifiable(_spec(_judged(str(odd)))) == ("c1",)


# -- kept: a file the judge can read, now or once the goal saves it ---------------------------------------------------

def test_an_absolute_existing_file_is_verifiable(tmp_path):
    named = tmp_path / "Makefile"                     # no extension, but a file that is there
    named.write_text("x")
    assert goal_mode.unverifiable(_spec(_judged(str(named)))) == ()


def test_a_file_the_goal_itself_saves_is_verifiable(tmp_path):
    later = str(tmp_path / "REPORT")                  # not there yet, no extension: the goal's own file_saved names it
    assert goal_mode.unverifiable(_spec(_judged(later), saved=later)) == ()
    assert goal_mode.unverifiable(_spec(_judged(str(tmp_path / "later.md")))) == ()


@pytest.mark.parametrize("name", ["ledger.csv", "out/summary.md", "notes.txt"])
def test_a_relative_file_name_is_resolved_later(name):
    assert goal_mode.unverifiable(_spec(_judged(name))) == ()


def test_the_user_can_still_take_such_a_check_as_their_own():
    assert goal_mode.unverifiable(_spec(_judged("提醒事项", user_confirmed=True))) == ()


def test_a_home_file_without_an_extension_is_read_through_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "TODO").write_text("x")
    assert goal_mode.unverifiable(_spec(_judged("~/TODO"))) == ()


def test_t2_shape_a_folder_the_goals_own_file_saved_names_is_still_flagged(tmp_path):
    # L7-7 bench, T2/T3: c1 "a table is saved in this folder" named the run folder, and so did the judgement check.
    folder = str(tmp_path)
    assert goal_mode.unverifiable(_spec(_judged(folder), saved=folder)) == ("c1",)
    assert goal_mode.unverifiable(_spec(_judged("out/"), saved="out/")) == ("c1",)


def test_a_name_ending_in_a_slash_is_a_folder_even_before_it_exists():
    assert goal_mode.unverifiable(_spec(_judged("exports.v2/"))) == ("c1",)
