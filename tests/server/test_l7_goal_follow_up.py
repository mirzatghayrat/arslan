"""L7-5f (L7-7 bench, T8): a follow-up goal's checks that name "the report" with no path mean the file the earlier
work in this conversation saved.

Turn 1's goal saved report.md. Turn 2, "把报告的第二节改短一些，其他两节不要动", drafted every check over "报告" (the
report): c1 file_saved ended `file_target_unresolved`, the judgements `judged_file_unreadable`, and after 3 rounds the
goal blocked with no_progress, while the job had edited report.md. Drafting now sees the files this conversation's
last finished job saved, and a bare name (no folder, no extension) resolves to that job's one file.
"""
from __future__ import annotations

import json

import pytest

from server.services import background_jobs, goal_command, goal_mode
from server.services.goal_mode import GoalCheck, GoalSpec
from tests.server import test_l7_goal_start as _start
from tests.server.test_l7_goal_start import CID, Model, _row, _say

active, fresh, jobs = _start.active, _start.fresh, _start.jobs          # its fixtures, used here as they are

REPORT = "/work/T8/report.md"
FOLLOW_UP = "把报告的第二节改短一些，其他两节不要动。"
DRAFT = {"criteria": [
    {"description": "报告文件已保存", "kind": "file_saved", "path": "报告"},
    {"description": "报告第二节更简短", "kind": "judgement", "path": "报告"},
    {"description": "notes are kept", "kind": "file_contains", "path": "notes.md", "phrases": ["42"]},
    {"description": "the folder has it", "kind": "file_saved", "path": "out/"},
]}


def _finished(job_id: str, files: list[str], cid: str = CID) -> background_jobs.Job:
    job = background_jobs.Job(job_id=job_id, conversation_id=cid, goal="g", acceptance=[], phase="finished",
                              files=files)
    background_jobs._jobs[job_id] = job
    return job


def test_the_last_finished_jobs_files_are_what_the_conversation_saved():
    assert goal_command.earlier_files(CID) == ()
    _finished("j1", ["/work/old.md"])
    _finished("j2", [REPORT, REPORT])
    background_jobs._jobs["j3"] = background_jobs.Job(job_id="j3", conversation_id=CID, goal="g", acceptance=[],
                                                      phase="running", files=["/work/live.md"])   # not finished
    _finished("j4", [])                                    # wrote nothing: the one before counts
    _finished("other", ["/work/elsewhere.md"], cid="another-chat")
    assert goal_command.earlier_files(CID) == (REPORT,)


def test_a_bare_name_resolves_to_the_earlier_works_one_file():
    checks = goal_command.drafted_checks(json.dumps(DRAFT), FOLLOW_UP)
    resolved = goal_command.resolved(checks, (REPORT,))
    assert [c.path for c in resolved] == [REPORT, REPORT, "notes.md", "out/"]    # a file name or folder is kept
    assert resolved[1].by_user is checks[1].by_user                                # only the path changes
    assert goal_mode.unverifiable(GoalSpec(objective=FOLLOW_UP, checks=resolved)) == ()


@pytest.mark.parametrize("earlier", [(), ("/work/a.md", "/work/b.md")])
def test_with_no_or_several_earlier_files_nothing_is_guessed(earlier):
    checks = goal_command.drafted_checks(json.dumps(DRAFT), FOLLOW_UP)
    assert goal_command.resolved(checks, earlier) == checks


@pytest.mark.parametrize("path", ["~", "~/报告", "/abs/报告", "Makefile.d/x", "report.md"])
def test_a_path_or_a_file_name_is_never_replaced(path):
    check = GoalCheck(id="c1", description="d", kind="file_saved", path=path)
    assert goal_command.resolved((check,), (REPORT,)) == (check,)


async def test_a_follow_up_goal_drafts_with_the_earlier_file_and_checks_it(execution_db, active, monkeypatch, jobs):
    from server.orchestrator import tool_loop
    model = Model(draft=DRAFT)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    _finished("turn-1", [REPORT])
    line = await _say(f"/goal {FOLLOW_UP}")
    (request,) = model.requests
    assert REPORT in request["user"] and request["user"].index(REPORT) > request["user"].index(FOLLOW_UP)
    spec = GoalSpec.model_validate((await _row(execution_db)).privacy["goal_spec"])
    assert [c.path for c in spec.checks][:2] == [REPORT, REPORT] and "⚠ c" not in line


async def test_a_first_goal_drafts_as_before(execution_db, active, monkeypatch, jobs):
    from server.orchestrator import tool_loop
    model = Model(draft=DRAFT)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    await _say(f"/goal {FOLLOW_UP}")
    (request,) = model.requests
    assert "saved before" not in request["user"]
    spec = GoalSpec.model_validate((await _row(execution_db)).privacy["goal_spec"])
    assert [c.path for c in spec.checks][:2] == ["报告", "报告"]
