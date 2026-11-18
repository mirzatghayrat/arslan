"""L7-5i, the user's second exception under the goal freeze (11-17), for Gate 1 of the L7-7 bench (r3, goal on).

T20 r2/r3/r4/r6 (checker 3): a judgement over the summaries/ folder, which the judge can't read as one file, was
`failed / judged_file_unreadable`, so the goal went on to round 2 and stopped at the soft tool limit, and the card said
"wall_seconds 2700/2700" for a run of about 300 s. Now such a check is no verdict (`not_run`, the user's to confirm),
as r1/r5 ended (review, then done), and the card names the limit the counts reached.

T21 r5 (checker 3): drafting wrote "The cleaned CSV passes validation, so the provided check exits 0" as a judgement
beside the user's own `check:` line; a judge that reads files never sees an exit code, so it failed 7 rounds and the
goal was blocked. Drafting now drops a judgement about a command's exit status when the goal has the user's check.
"""
from __future__ import annotations

import json

import pytest

from server.services import goal_command
from server.services.goal_mode import GoalSpec
from tests.server import test_l7_goal_round as _round, test_l7_goal_start as _start

active, fresh, jobs = _start.active, _start.fresh, _start.jobs          # its fixtures, used here as they are

# -- T20 r2, as recorded: c1/c2 file saved, c3 a judgement over the summaries/ folder, c4 over index.md ------------


def _t20_r2(root) -> GoalSpec:
    return _round._goal(
        _round._check(id="c1", kind="file_saved", path=str(root / "summaries"), phrases=(),
                      description="A summaries directory is created under the specified run directory."),
        _round._check(id="c2", kind="file_saved", path=str(root / "summaries" / "index.md"), phrases=(),
                      description="The summaries/index.md file is created."),
        _round._check(id="c3", kind="judgement", path=str(root / "summaries"), phrases=(), description=(
            "Each note in the notes directory has a corresponding summary file with the same filename in the "
            "summaries directory, and each summary contains exactly two sentences that include the note's code word "
            "and its date.")),
        _round._check(id="c4", kind="judgement", path=str(root / "summaries" / "index.md"), phrases=(),
                      description="The summaries/index.md file lists every note by its file name."))


async def test_a_judgement_the_judge_cant_read_is_no_verdict_and_the_goal_ends_review_in_round_1(
        execution_db, monkeypatch, tmp_path):
    def work(n):
        (tmp_path / "summaries").mkdir(exist_ok=True)              # the work creates the folder, as in r2
        (tmp_path / "summaries" / "n01.md").write_text("INV-1 was filed on 2026-02-03. It is paid.\n")
        (tmp_path / "summaries" / "index.md").write_text("- n01.md\n")
        return "Summarised every note."
    result, task, record, rounds, calls = await _round._goal_turn(
        _t20_r2(tmp_path), monkeypatch, tmp_path, work, judge=lambda user: '{"passed": true}')
    assert (record.status, record.round, rounds) == ("review", 1, 1) and len(calls["turn"]) == 1
    assert record.unjudged == ("c3",) and "c3" in record.unmet
    assert task.phase == "waiting_user" and "judged_not_a_file" in result["final"]


# -- T21 r5, as recorded: the drafted criteria and the user's own check: line -----------------------------------

_T21_R5_DRAFT = {"criteria": [
    {"description": "The cleaned CSV file exists at the target path.", "kind": "file_saved", "path": "clean/orders.csv"},
    {"description": "The cleaned CSV has the same columns as the original data/orders.csv.", "kind": "judgement",
     "path": "clean/orders.csv"},
    {"description": "The cleaned CSV passes validation, so the provided check exits 0.", "kind": "judgement",
     "path": "clean/orders.csv"}]}
_T21_CHECK = (("python3", "validate.py", "--rules", "rules.dat", "clean/orders.csv"),)
_T21_OBJECTIVE = ("Clean data/orders.csv into clean/orders.csv, with the same columns, so that the check below exits 0. "
                  "Don't edit validate.py, rules.dat or data/orders.csv.\n"
                  "check: python3 validate.py --rules rules.dat clean/orders.csv")


def test_drafting_drops_a_judgement_about_the_users_checks_exit_status():
    drafted = goal_command.drafted_checks(json.dumps(_T21_R5_DRAFT), _T21_OBJECTIVE, commands=_T21_CHECK)
    assert [check.description for check in drafted] == [
        "The cleaned CSV file exists at the target path.",
        "The cleaned CSV has the same columns as the original data/orders.csv."]


@pytest.mark.parametrize("description,dropped", [
    ("The cleaned CSV passes validation, so the provided check exits 0.", True),
    ("validate.py exits with code 0 on the cleaned file.", True),
    ("The command exits with code 0.", True),
    ("The check passes on the cleaned file.", True),
    ("The README explains how to exit the app.", False),
    ("Each summary ends with an exit line naming the next step.", False),
    # #993 review r1 MF3: real criteria that only sound like it are kept
    ("The function returns 0 for an empty list.", False),
    ("docs/cli.md explains every exit code.", False),
    ("README documents the exit status of each subcommand.", False),
    ("The spell check passes on the report.", False),
    ("clean/orders.csv has the same columns as data/orders.csv.", False),
    ("validate.py and rules.dat are left unchanged.", False),          # names the check's script, no exit or pass
])
def test_only_a_judgement_about_an_exit_status_or_the_check_passing_is_dropped(description, dropped):
    draft = {"criteria": [{"description": description, "kind": "judgement", "path": "clean/orders.csv"}]}
    assert (goal_command.drafted_checks(json.dumps(draft), _T21_OBJECTIVE, commands=_T21_CHECK) == ()) is dropped


@pytest.mark.parametrize("argv,description", [
    (("make", "test"), "The README makes clear which invoices passed review."),
    (("go", "test", "./..."), "The summary is a good read and every claim passes a fact check."),
    (("uv", "run", "pytest"), "Each run summary in runs.md passes a quick skim."),
    (("test", "-f", "out.csv"), "The latest report passes a reader's sanity test."),
    (_T21_CHECK[0], "clean/orders.csv passes a reader's check of every column."),     # a data file, not the script
    (("bash", "check.sh"), "The precheck.sh notes pass a quick review."),        # only part of another word
], ids=["make-test", "go-test", "uv-run-pytest", "test-f", "data-file", "part-of-a-word"])
def test_a_bare_program_or_subcommand_word_never_drops_a_criterion(argv, description):
    # #993 review r2 MF4: only a script file name (with an extension) counts, as a whole word
    draft = {"criteria": [{"description": description, "kind": "judgement", "path": "README.md"}]}
    assert len(goal_command.drafted_checks(json.dumps(draft), "Do it.\ncheck: x", commands=(argv,))) == 1


@pytest.mark.parametrize("argv,description", [
    (("bash", "scripts/check.sh"), "check.sh exits 0 on the result."),
    (("python3", "tests/run_checks.py"), "run_checks.py passes on the fixed ledger."),
])
def test_a_script_file_name_with_an_exit_or_pass_still_drops(argv, description):
    draft = {"criteria": [{"description": description, "kind": "judgement", "path": "README.md"}]}
    assert goal_command.drafted_checks(json.dumps(draft), "Do it.\ncheck: x", commands=(argv,)) == ()


def test_without_the_users_check_line_such_a_judgement_is_kept():
    drafted = goal_command.drafted_checks(json.dumps(_T21_R5_DRAFT), _T21_OBJECTIVE, commands=())
    assert len(drafted) == 3


# -- L7-5i: a goal that wrapped up at a soft limit says which one (L7-7 r3, T20: "wall_seconds 2700/2700") -----------

_T20_STOP = {"limits": {"model_requests": 180, "tool_calls": 120, "tokens": 900000, "wall_seconds": 2700.0},
             "soft_limits": {"model_requests": 120, "tool_calls": 80, "tokens": 600000, "wall_seconds": 1800},
             "used": {"model_requests": 45, "tool_calls": 81, "tokens": 236239, "wall_seconds": 335.25},
             "stop_reason": None}


def test_a_goal_stopped_at_the_soft_tool_limit_says_so_with_its_real_counts():
    from server.services import background_jobs
    stop = background_jobs.budget_stop_of(_T20_STOP, pause_reason="task_budget_exhausted", tier="standard")
    assert stop == {"reason": "tool_calls", "used": 81, "limit": 80, "soft": True, "tier": "standard"}


def test_a_hard_limit_reached_is_named_before_a_soft_one():
    from server.services import background_jobs
    budget = {**_T20_STOP, "used": {**_T20_STOP["used"], "model_requests": 180, "tool_calls": 81}}
    stop = background_jobs.budget_stop_of(budget, pause_reason="task_budget_exhausted", tier="standard")
    assert stop == {"reason": "model_requests", "used": 180, "limit": 180, "tier": "standard"}


def test_a_clock_stop_whose_saved_count_lags_is_still_the_wall_clock():
    from server.services import background_jobs
    budget = {**_T20_STOP, "used": {"model_requests": 3, "tool_calls": 4, "tokens": 10, "wall_seconds": 2650.4}}
    stop = background_jobs.budget_stop_of(budget, pause_reason="task_budget_exhausted", tier="standard")
    assert stop == {"reason": "wall_seconds", "used": 2700, "limit": 2700, "tier": "standard"}


def test_a_goal_that_wrapped_up_at_the_soft_wall_time_says_so():
    from server.services import background_jobs
    budget = {**_T20_STOP, "used": {"model_requests": 3, "tool_calls": 4, "tokens": 10, "wall_seconds": 1850.2}}
    stop = background_jobs.budget_stop_of(budget, pause_reason="task_budget_exhausted", tier="standard")
    assert stop == {"reason": "wall_seconds", "used": 1850, "limit": 1800, "soft": True, "tier": "standard"}



async def test_a_goal_set_with_the_users_check_line_keeps_no_exit_status_judgement(execution_db, active, jobs,
                                                                                     monkeypatch):
    from server.orchestrator import tool_loop
    from tests.server import test_l7_goal_start as start
    model = start.Model(draft=_T21_R5_DRAFT)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    await start._say(f"/goal {_T21_OBJECTIVE}")
    spec = GoalSpec.model_validate((await start._row(execution_db)).privacy["goal_spec"])
    assert [check.kind for check in spec.checks] == ["file_saved", "judgement", "check"]
    assert not any("exits 0" in check.description for check in spec.checks)


def test_a_target_the_host_cant_even_stat_stays_failed_never_a_crash(tmp_path):
    # #993 review r1 MF1: Path.exists() raises PermissionError under a folder the user can't search (mode 000, or a
    # macOS folder the app has no permission for); the target stays failed, as before, and validation goes on.
    from server.services import task_validation
    locked = tmp_path / "locked"
    (locked / "summaries").mkdir(parents=True)
    locked.chmod(0o000)
    try:
        assert task_validation._not_a_file(str(locked / "summaries"), [], {"roots": [tmp_path], "workspace": tmp_path}) \
            is False
    finally:
        locked.chmod(0o755)


def test_a_goal_that_wrapped_up_at_its_soft_dollar_limit_says_so():
    # #993 review r1 MF2: `/goal $1`, $0.70 spent (the soft dollar limit is the cap / 1.5)
    from server.services import background_jobs
    budget = {**_T20_STOP, "used": {"model_requests": 9, "tool_calls": 12, "tokens": 50000, "wall_seconds": 210.0},
              "spend": {"usd": 0.70, "usd_cap": 1.0}}
    stop = background_jobs.budget_stop_of(budget, pause_reason="task_budget_exhausted", tier="standard")
    assert stop == {"reason": "usd", "used": "$0.70", "limit": "$0.67", "soft": True, "tier": "standard"}


def test_the_hard_clock_wins_over_a_soft_count_it_fired_after():
    # #993 review r1 MF2: past 80 tool calls (soft) and then the hard wall clock fired: the clock stopped it
    from server.services import background_jobs
    budget = {**_T20_STOP, "used": {**_T20_STOP["used"], "wall_seconds": 2698.0}}
    stop = background_jobs.budget_stop_of(budget, pause_reason="task_budget_exhausted", tier="standard")
    assert stop == {"reason": "wall_seconds", "used": 2700, "limit": 2700, "tier": "standard"}
