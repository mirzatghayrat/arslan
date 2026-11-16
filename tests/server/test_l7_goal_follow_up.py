"""L7-5f (L7-7 bench, T8): a follow-up goal's checks that name "the report" with no path mean the file the earlier
work in this conversation saved.

Turn 1's goal saved report.md. Turn 2, "把报告的第二节改短一些，其他两节不要动", drafted every check over "报告" (the
report): c1 file_saved ended `file_target_unresolved`, the judgements `judged_file_unreadable`, and after 3 rounds the
goal blocked with no_progress, while the job had edited report.md. Drafting now sees the files this conversation's
last finished job saved. The host never rewrites a drafted path (#977 review round 1).
"""
from __future__ import annotations


import pytest

from server.services import background_jobs, goal_command
from server.services.goal_mode import GoalSpec
from tests.server import test_l7_goal_start as _start
from tests.server.test_l7_goal_start import CID, Model, _row, _say

active, fresh, jobs = _start.active, _start.fresh, _start.jobs          # its fixtures, used here as they are

REPORT = "/work/T8/report.md"
HEADER = "Files this conversation's earlier work saved"
FOLLOW_UP = "把报告的第二节改短一些，其他两节不要动。"


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


@pytest.mark.parametrize("path", ["报告", ".", "..", ".gitignore", ".env", "Makefile", "Dockerfile", "trash",
                                  "Reminders", "提醒事项", "arxiv", "out/"])
async def test_the_host_never_rewrites_a_drafted_path(execution_db, active, monkeypatch, jobs, path):
    # #977 review round 1: a bare name may be an app, a dotfile, a build file, a folder or a site, not the report
    from server.orchestrator import tool_loop
    model = Model(draft={"criteria": [{"description": "d", "kind": "judgement", "path": path},
                                      {"description": "s", "kind": "file_saved", "path": path},
                                      {"description": "r", "kind": "sources_read", "path": path}]})
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    _finished("turn-1", [REPORT])
    await _say(f"/goal {FOLLOW_UP}")
    spec = GoalSpec.model_validate((await _row(execution_db)).privacy["goal_spec"])
    assert [c.path for c in spec.checks] == [path, path, path]


class Drafter(Model):
    """Drafts over the listed file when the request lists one, else over the bare word."""

    async def chat(self, system, user, history=None, tools=None, **kw):
        path = REPORT if REPORT in user else "报告"
        self.draft = {"criteria": [{"description": "报告文件已保存", "kind": "file_saved", "path": path},
                                   {"description": "报告第二节更简短", "kind": "judgement", "path": path}]}
        return await super().chat(system, user, history, tools, **kw)


async def test_a_follow_up_goal_drafts_with_the_earlier_file_and_checks_it(execution_db, active, monkeypatch, jobs):
    from server.orchestrator import tool_loop
    model = Drafter()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    _finished("turn-1", [REPORT])
    line = await _say(f"/goal {FOLLOW_UP}")
    (request,) = model.requests
    assert HEADER in request["user"] and request["user"].index(FOLLOW_UP) < request["user"].index(HEADER) \
        < request["user"].index(REPORT)
    spec = GoalSpec.model_validate((await _row(execution_db)).privacy["goal_spec"])
    assert [c.path for c in spec.checks][:2] == [REPORT, REPORT] and "⚠ c" not in line
    assert spec.checks[1].by_user                       # the host listed it: vouched for as the user's own path


async def test_a_judgement_over_a_path_the_host_did_not_list_is_still_flagged(execution_db, active, monkeypatch,
                                                                              jobs):
    from server.orchestrator import tool_loop
    model = Model(draft={"criteria": [{"description": "d", "kind": "judgement", "path": "/work/T8/other.md"}]})
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    _finished("turn-1", [REPORT])
    line = await _say(f"/goal {FOLLOW_UP}")
    spec = GoalSpec.model_validate((await _row(execution_db)).privacy["goal_spec"])
    assert not spec.checks[0].by_user and "⚠ c1" in line


async def test_a_first_goal_drafts_as_before(execution_db, active, monkeypatch, jobs):
    from server.orchestrator import tool_loop
    model = Drafter()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    await _say(f"/goal {FOLLOW_UP}")
    (request,) = model.requests
    assert HEADER not in request["user"]
    spec = GoalSpec.model_validate((await _row(execution_db)).privacy["goal_spec"])
    assert [c.path for c in spec.checks][:2] == ["报告", "报告"]
