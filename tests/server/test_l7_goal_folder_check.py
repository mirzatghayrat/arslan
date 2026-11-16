"""L7-5c: a judgement check whose named target is a folder is a check Arslan can't verify.

The host's judge reads one named file (`task_validation._read_named`), so over a folder it failed every round as
`judged_file_unreadable` and the goal stopped blocked (bench T18: "the original invoices are unchanged" named the
invoices folder). It is flagged at drafting instead, like any other check Arslan can't verify: Start asks the user to
confirm it as their own.
"""
from __future__ import annotations

from server.services import goal_mode
from server.services.goal_mode import GoalCheck, GoalSpec


def _judged(path: str, **kw) -> GoalCheck:
    return GoalCheck.model_validate({"id": "c1", "description": "The originals are unchanged", "kind": "judgement",
                                     "path": path, "by_user": True, **kw})


def _spec(*checks) -> GoalSpec:
    saved = GoalCheck.model_validate({"id": "c0", "description": "Ledger saved", "kind": "file_saved",
                                      "path": "ledger.csv"})
    return GoalSpec(objective="Build the ledger", checks=(saved, *checks))


def test_a_judgement_over_a_named_folder_is_flagged(tmp_path):
    folder = tmp_path / "invoices"
    folder.mkdir()
    assert goal_mode.unverifiable(_spec(_judged(str(folder)))) == ("c1",)
    assert goal_mode.unverifiable(_spec(_judged(str(folder) + "/"))) == ("c1",)


def test_a_judgement_over_a_named_file_is_still_verifiable(tmp_path):
    named = tmp_path / "notes.md"
    named.write_text("x")
    assert goal_mode.unverifiable(_spec(_judged(str(named)))) == ()
    # a file that doesn't exist yet, or a relative name the host resolves later, is judged as before
    assert goal_mode.unverifiable(_spec(_judged(str(tmp_path / "later.md")))) == ()
    assert goal_mode.unverifiable(_spec(_judged("invoices"))) == ()


def test_the_user_can_still_take_a_folder_check_as_their_own(tmp_path):
    folder = tmp_path / "invoices"
    folder.mkdir()
    assert goal_mode.unverifiable(_spec(_judged(str(folder), user_confirmed=True))) == ()


def test_a_home_relative_folder_is_flagged_too(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "invoices").mkdir()
    assert goal_mode.unverifiable(_spec(_judged("~/invoices"))) == ("c1",)


def test_a_relative_name_that_is_a_folder_here_is_not_guessed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "invoices").mkdir()
    assert goal_mode.unverifiable(_spec(_judged("invoices"))) == ()       # resolved later against the readable folders
