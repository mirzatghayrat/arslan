"""L7-5f (L7-7 bench, T11 r2): a job's "was the goal reached" judge reads what the user told it during the work.

The stand-in declined the delete card with a note: "别删，改成移到 workspace 里的 trash 文件夹". The job moved the 5
files there and answered "按你的要求 … 移到了 trash，没删 … 没有执行删除，文件都还在". The judge saw only the
goal ("clean up the .bak files") and that answer, said a confident "no", and the job ended blocked/goal_not_reached.
The user's note changed the goal: the judge now gets the notes the user gave on this job's cards.
"""
from __future__ import annotations

import pytest

from server.services import background_jobs, judgment, permissions

NOTE = "别删，改成移到 workspace 里的 trash 文件夹"
ANSWER = "按你的要求，我把 5 个 .bak 文件从 workspace 移到了 `workspace/trash` 文件夹，没删。未核对：没有执行删除，文件都还在。"


@pytest.fixture
def job():
    job = background_jobs.Job(job_id="job-notes", conversation_id="c", goal="把 workspace 里所有的 .bak 文件清理掉。",
                              acceptance=[])
    background_jobs._jobs[job.job_id] = job
    token = background_jobs._inside_job.set(job.job_id)
    yield job
    background_jobs._inside_job.reset(token)
    background_jobs._jobs.pop(job.job_id, None)


def _no(note: str) -> permissions.Decision:
    return permissions.Decision(False, "user", note=note, model_text=permissions._declined_text("x", note))


def test_a_no_with_a_note_inside_a_job_is_kept_on_the_job(job):
    permissions._done(_no(NOTE))
    assert job.user_notes == [NOTE]


@pytest.mark.parametrize("decision", [
    permissions.Decision(True, "user", "once"),                              # a yes carries no note
    permissions.Decision(False, "expired", model_text="nobody answered"),    # an expiry is not the user's word
    permissions.Decision(False, "user", note="", model_text="no"),           # a bare no adds nothing
    permissions.Decision(False, "policy", note="x", model_text="refused"),   # a rule, not the user
])
def test_only_the_users_own_note_is_kept(job, decision):
    permissions._done(decision)
    assert job.user_notes == []


def test_outside_a_job_nothing_is_kept():
    assert background_jobs._inside_job.get() is None
    permissions._done(_no(NOTE))           # no job to keep it on, and no error


def test_notes_are_bounded(job):
    for i in range(12):
        permissions._done(_no(f"note {i} " + "x" * 600))
    assert len(job.user_notes) == background_jobs.USER_NOTES_MAX
    assert job.user_notes[-1].startswith("note 11") and all(len(n) <= 500 for n in job.user_notes)


async def test_the_judge_reads_the_users_notes_with_the_goal_and_answer(job, monkeypatch):
    seen = []

    async def judge(point, state, **kwargs):
        seen.append(state)
        return judgment.Verdict(True, 0.9, 1)
    monkeypatch.setattr(judgment, "judge", judge)
    job.user_notes.append(NOTE)
    assert await background_jobs._goal_not_reached(job, ANSWER) is False
    assert seen == [{"goal": job.goal, "answer": ANSWER, "user_notes": [NOTE]}]
    seen.clear()
    job.user_notes.clear()                  # no note: the judge's facts are what they were
    await background_jobs._goal_not_reached(job, ANSWER)
    assert seen == [{"goal": job.goal, "answer": ANSWER}]


def test_the_question_takes_the_users_notes_as_changing_the_goal():
    point = judgment.REGISTRY["job.accomplished"]
    assert "user_notes" in point.fields
    assert "user_notes" in point.question
    kept = judgment.minimal_state(point, {"goal": "g", "answer": "a", "user_notes": [NOTE], "other": "dropped"})
    assert kept == {"goal": "g", "answer": "a", "user_notes": [NOTE]}
