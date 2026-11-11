"""INB9-a (v0.1.64): the acceptance sheet an unattended run ends with, and 👀 in what waits on you.

A background job (and a sub-session, whose job has no criteria of its own) ends with three lists appended to its one
result message: ✅ what a deterministic check verified, naming its evidence; 👀 what only the user can judge (a
`glance` criterion, at most two); ⚠️ everything else (not run, failed, not reached, only the model's own judgement, a
third glance). A job whose only gap is a 👀 reads `done` only when the model's own criteria hold at least one other
check and all of them passed; its task row stays `waiting_user`, so accepting it closes it. An open 👀 newer than your
last look at its conversation counts as waiting on you (progress.waiting_reasons, reason `glance`).

Offline: a scripted adapter stands in for the model. No paid calls.
"""
import re
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from arslan.companion.contracts import AcceptanceCheck
from server.db.models import ArslanMessage, CompanionTask, ConversationSeen, ProactiveItem
from server.orchestrator import tool_loop, untrusted
from server.services import (acceptance_sheet, background_jobs, conversation_seen, desktop_status, progress,
                             runtime_messages, task_validation)
from server.services.task_repository import repository
from tests.server.test_background_jobs import (CID, PHRASE, JobAdapter, _spoken, _wait, active, frames,  # noqa: F401
                                               fresh)

ANSWER = {"id": "answer-delivered", "description": "An answer was delivered", "evaluator": "deterministic",
          "rule": {"kind": "text", "minimum": 1}}


def _det(id_, description, **rule):
    return {"id": id_, "description": description, "evaluator": "deterministic", "rule": rule}


def _human(id_, description):
    return {"id": id_, "description": description, "evaluator": "human"}


def _model(id_, description):
    return {"id": id_, "description": description, "evaluator": "model"}


def _checks(*items):
    return {"checks": [{"check_id": c, "evaluator": e, "status": s, "code": code, **extra}
                       for c, e, s, code, extra in items], "artifacts": []}


SAVED = "/Users/me/Desktop/report.md"


def _sample():
    acceptance = [ANSWER, _det("criterion-1", "Saved as report.md", kind="file_saved", target="report.md", minimum=1),
                  _human("glance-2", "The tone suits the team"),
                  _model("criterion-3", "Covers three vendors"), _model("criterion-4", "Reads naturally"),
                  _model("criterion-5", "Has a summary")]
    results = {"answer-delivered": "passed", "criterion-1": "passed", "glance-2": "not_run",
               "criterion-3": "passed", "criterion-4": "not_run", "criterion-5": "failed"}
    report = _checks(("answer-delivered", "deterministic", "passed", "text_assertion", {}),
                     ("criterion-1", "deterministic", "passed", "file_saved_assertion", {"path": SAVED}),
                     ("glance-2", "human", "not_run", "human_review_required", {}),
                     ("criterion-3", "model", "passed", "model_assessment", {}),
                     ("criterion-4", "model", "not_run", "model_check_not_run", {}),
                     ("criterion-5", "model", "failed", "model_assessment", {}))
    return acceptance, results, report


# -- 1, 2, 3: the three columns -----------------------------------------------------------------------------------

def test_each_column_has_its_own_source():
    verified, glance, unverified = acceptance_sheet.columns(*_sample())
    assert [(line.check_id, line.evidence, line.code) for line in verified] == [
        ("answer-delivered", None, "text_assertion"), ("criterion-1", SAVED, "file_saved_assertion")]
    assert [line.text for line in glance] == ["The tone suits the team"]
    assert [(line.check_id, line.note) for line in unverified] == [
        ("criterion-3", "sheet_model_only"), ("criterion-4", "sheet_not_run"), ("criterion-5", "sheet_failed")]


def test_a_check_only_a_model_passed_is_never_verified():
    """contracts.py: only deterministic or human verification may be critical; a model's yes is never ✅, also one it
    gave with its own assessment, also one whose recorded result claims another evaluator."""
    acceptance = [ANSWER, _model("criterion-1", "Reads naturally")]
    results = {"answer-delivered": "passed", "criterion-1": "passed"}
    report = _checks(("criterion-1", "deterministic", "passed", "model_assessment", {}))
    verified, _, unverified = acceptance_sheet.columns(acceptance, results, report)
    assert [line.check_id for line in verified] == ["answer-delivered"]
    assert [(line.check_id, line.note) for line in unverified] == [("criterion-1", "sheet_model_only")]


def test_a_check_never_reached_and_a_failed_deterministic_one_are_not_verified():
    acceptance = [ANSWER, _det("criterion-1", "Mentions the phrase", kind="text", contains=["x"]),
                  _det("criterion-2", "Saved", kind="file_saved", target="a.md", minimum=1)]
    verified, _, unverified = acceptance_sheet.columns(acceptance, {"answer-delivered": "passed",
                                                                    "criterion-1": "failed"}, None)
    assert [line.check_id for line in verified] == ["answer-delivered"]
    assert [(line.check_id, line.note) for line in unverified] == [("criterion-1", "sheet_failed"),
                                                                    ("criterion-2", "sheet_not_reached")]


def test_at_most_two_glances_and_a_third_says_why_it_is_not_one():
    checks = background_jobs.criteria_to_acceptance([
        {"description": "first", "kind": "glance"}, {"description": "second", "kind": "glance"},
        {"description": "third", "kind": "glance"}, {"description": f"Says {PHRASE}", "kind": "mentions",
                                                    "target": PHRASE}])
    for check in checks:
        AcceptanceCheck.model_validate(check)                    # each one a valid check of the task's spec
    assert [c["description"] for c in checks if c["evaluator"] == "human"] == ["first", "second"]
    assert all(not c.get("critical") for c in checks if c["evaluator"] == "human")
    third = next(c for c in checks if c["description"] == "third")
    assert third["evaluator"] == "model" and "rule" not in third
    results = {c["id"]: "not_run" for c in checks} | {"answer-delivered": "passed"}
    _, glance, unverified = acceptance_sheet.columns(checks, results, None)
    assert [line.text for line in glance] == ["first", "second"]
    assert [(line.text, line.note) for line in unverified] == [("third", "sheet_more_glances"),
                                                                (f"Says {PHRASE}", "sheet_not_run")]
    assert "- third — more than two to look at" in acceptance_sheet.render(checks, results, None, "en")
    # A follow-up keeps them glances (and so the cap again).
    assert [c["kind"] for c in background_jobs.criteria_from_acceptance(checks)] == ["glance"] * 3 + ["mentions"]


def test_the_sheet_reads_as_three_headed_lists_in_the_users_language():
    text = acceptance_sheet.render(*_sample(), "en")
    assert text == (
        "**✅ Checked**\n"
        "- An answer was delivered (text_assertion)\n"
        f"- Saved as report.md — `{SAVED}` (file_saved_assertion)\n"
        "\n**👀 For you to look at**\n"
        "- The tone suits the team\n"
        "\n**⚠️ Not verified**\n"
        "- Covers three vendors — only the model's own judgement\n"
        "- Reads naturally — not run (model_check_not_run)\n"
        "- Has a summary — did not pass (model_assessment)")
    assert "**👀 要你看一眼的**" in acceptance_sheet.render(*_sample(), "zh")
    keys = {key for key in runtime_messages.MESSAGES["en"] if key.startswith("sheet_")}
    assert len(keys) == 10
    for locale, words in runtime_messages.MESSAGES.items():
        assert keys <= set(words), locale


def test_a_file_saved_check_names_the_file_it_found(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "report.md").write_text("done")
    check = AcceptanceCheck.model_validate({"id": "criterion-1", "description": "Saved", "evaluator": "deterministic",
                                            "rule": {"kind": "file_saved", "target": "report.md", "minimum": 1}})
    context = {"roots": [home.resolve()], "workspace": home.resolve(), "since": time.time() - 60}
    result = task_validation.evaluate(check, "", [], [], context)
    assert (result["status"], result["code"], result["path"]) == ("passed", "file_saved_assertion",
                                                                   str((home / "report.md").resolve()))
    (home / "empty.md").write_text("")
    empty = AcceptanceCheck.model_validate({"id": "criterion-2", "description": "Saved", "evaluator": "deterministic",
                                            "rule": {"kind": "file_saved", "target": "empty.md", "minimum": 1}})
    assert "path" not in task_validation.evaluate(empty, "", [], [], context)


# -- 6: the outcome ----------------------------------------------------------------------------------------------

def test_only_a_glance_open_reads_done_only_beside_the_models_own_passed_checks():
    review = ("waiting_user", "acceptance_review_required")
    a = {"answer-delivered": "passed", "criterion-1": "passed", "glance-2": "not_run"}
    assert background_jobs.outcome_of(review[0], a, review[1], glances={"glance-2"}) == "done"
    b = {"answer-delivered": "passed", "glance-1": "not_run", "glance-2": "not_run"}       # the answer is no check
    assert background_jobs.outcome_of(review[0], b, review[1], glances={"glance-1", "glance-2"}) == "partial"
    c = {"answer-delivered": "passed", "criterion-1": "failed", "glance-2": "not_run"}
    assert background_jobs.outcome_of("waiting_user", c, "task_validation_failed", glances={"glance-2"}) != "done"
    assert background_jobs.outcome_of("waiting_user", c, review[1], glances={"glance-2"}) != "done"
    assert background_jobs.outcome_of("waiting_user", a, "task_checks_not_run", glances={"glance-2"}) != "done"


def _glance_criteria():
    return [{"description": f"The result says {PHRASE}", "kind": "mentions", "target": PHRASE},
            {"description": "The tone suits the team", "kind": "glance"}]


async def _finished(frames, criteria, monkeypatch, text=f"Done: {PHRASE}", outside_seen=False):  # noqa: F811
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: JobAdapter(text=text))
    monkeypatch.setattr(runtime_messages, "selected_locale", lambda: _en())
    job = await background_jobs.start(CID, "Write the team note", criteria, outside_seen=outside_seen)
    await _wait(lambda: job.phase == "finished")
    await _wait(_spoken(frames, job))
    return job


async def _en():
    return "en"


async def _messages(execution_db):
    async with execution_db() as db:
        return (await db.scalars(select(ArslanMessage).where(ArslanMessage.conversation_id == CID)
                                 .order_by(ArslanMessage.id))).all()


async def test_a_job_with_one_passed_check_and_a_glance_is_done_and_posts_one_message_with_its_sheet(
        execution_db, active, frames, monkeypatch):  # noqa: F811
    job = await _finished(frames, _glance_criteria(), monkeypatch)
    assert job.outcome == "done", (job.detail, job.results)
    async with execution_db() as db:
        row = await db.get(CompanionTask, job.job_id)
        assert (row.phase, row.pause_reason) == ("waiting_user", "acceptance_review_required")
    [message] = await _messages(execution_db)
    assert message.job_outcome == "done"
    assert message.content.startswith(f"Done: {PHRASE}\n\n**✅ Checked**\n")
    assert "**👀 For you to look at**\n- The tone suits the team" in message.content
    assert f"- The result says {PHRASE} — `{PHRASE}` (text_assertion)" in message.content
    event = desktop_status.snapshot()["events"][-1]
    assert (event["kind"], event["outcome"], event["glance"]) == ("turn_finished", "ok", 1)


async def test_a_job_whose_criteria_are_all_glances_stays_partial(execution_db, active, frames, monkeypatch):  # noqa: F811
    job = await _finished(frames, [{"description": "Looks right", "kind": "glance"},
                                   {"description": "Tone fits", "kind": "glance"}], monkeypatch)
    assert job.outcome == "partial", (job.detail, job.results)


async def test_a_failed_check_beside_a_glance_is_not_done(execution_db, active, frames, monkeypatch):  # noqa: F811
    job = await _finished(frames, _glance_criteria(), monkeypatch, text="I made a start.")
    assert job.outcome != "done"
    [message] = await _messages(execution_db)
    assert f"- The result says {PHRASE} — did not pass" in message.content


async def test_accepting_the_review_closes_a_done_jobs_row_and_its_glance_stops_waiting(
        execution_db, active, frames, monkeypatch):  # noqa: F811
    job = await _finished(frames, _glance_criteria(), monkeypatch)
    async with execution_db() as db:
        assert await progress.waiting_reasons(db) == {CID: "glance"}
    async with repository() as repo:
        row = await repo.get(job.job_id)
        accepted = await repo.accept_review(job.job_id, row.version)
    assert accepted["state"]["phase"] == "succeeded"
    async with execution_db() as db:
        assert (await progress.waiting_on_user(db)).count == 0


# -- 5: 👀 reaches the badge ----------------------------------------------------------------------------------------

async def test_an_open_glance_waits_on_you_until_you_look(execution_db, active, frames, monkeypatch):  # noqa: F811
    await _finished(frames, _glance_criteria(), monkeypatch)
    async with execution_db() as db:
        waiting = await progress.waiting_on_user(db)
        assert (waiting.count, waiting.conversations) == (1, {CID})
        await conversation_seen.mark(db, CID)
        assert (await progress.waiting_on_user(db)).count == 0


async def test_a_glance_from_the_moment_you_looked_counts_as_seen(execution_db, active, frames, monkeypatch):  # noqa: F811
    job = await _finished(frames, _glance_criteria(), monkeypatch)
    async with execution_db() as db:
        row = await db.get(CompanionTask, job.job_id)
        db.add(ConversationSeen(conversation_id=CID, seen_message_id=0, seen_at=row.updated_at))
        await db.commit()
        assert (await progress.waiting_on_user(db)).count == 0
        row.updated_at = row.updated_at + timedelta(seconds=1)              # newer than the look: waits again
        await db.commit()
        assert await progress.waiting_reasons(db) == {CID: "glance"}
        row.updated_at = row.updated_at - timedelta(hours=progress.AWAY_HOURS + 1)   # older than a day: expired
        await db.commit()
        assert (await progress.waiting_on_user(db)).count == 0


async def test_a_glance_ranks_after_an_away_entry_and_before_a_reminder(execution_db, active, frames, monkeypatch):  # noqa: F811
    await _finished(frames, _glance_criteria(), monkeypatch)
    async with execution_db() as db:
        db.add(ProactiveItem(kind="job_followup", fingerprint="fp:1", source_key="job:1", title_key="t",
                             evidence=[], status="new", conversation_id=CID))
        await db.commit()
        assert await progress.waiting_reasons(db) == {CID: "glance"}
    assert progress._FIRST == ("card", "away", "glance", "reminder")


async def test_a_job_with_no_glance_adds_nothing_to_what_waits(execution_db, active, frames, monkeypatch):  # noqa: F811
    job = await _finished(frames, [{"description": f"Says {PHRASE}", "kind": "mentions", "target": PHRASE}],
                          monkeypatch)
    assert job.outcome == "done"
    async with execution_db() as db:
        assert (await progress.waiting_on_user(db)).count == 0
    assert "glance" not in desktop_status.snapshot()["events"][-1]


# -- 8: outside content -----------------------------------------------------------------------------------------

async def test_the_sheet_is_framed_with_the_result_and_shown_plain(execution_db, active, frames, monkeypatch):  # noqa: F811
    job = await _finished(frames, _glance_criteria(), monkeypatch, outside_seen=True)
    [message] = await _messages(execution_db)
    shown = message.display_content
    assert shown.startswith(f"Done: {PHRASE}\n\n**✅ Checked**") and "The tone suits the team" in shown
    assert message.content == untrusted.job_result(shown)              # one frame around the result and its sheet
    assert untrusted.JOB_RESULT_FROM_OUTSIDE not in shown
    posted = [f for f in frames if f.get("type") == "message" and f.get("job_id") == job.job_id]
    assert [f["content"] for f in posted] == [shown]


# -- sub-sessions and summaries -------------------------------------------------------------------------------------

async def test_a_sub_sessions_sheet_is_its_answer_and_files_and_a_summary_has_none(execution_db, monkeypatch):
    monkeypatch.setattr(runtime_messages, "selected_locale", lambda: _en())
    child = background_jobs.Job(job_id="job-child", conversation_id="sub-child", goal="g",
                                acceptance=background_jobs.criteria_to_acceptance([]), parent_id="root",
                                outside_seen=False, outcome="done", results={"answer-delivered": "passed"},
                                files=["/Users/me/notes/a.md"])
    posted = await background_jobs._report(child, "Wrote the notes.")
    assert posted == "Wrote the notes."                     # what its commander hears: the answer, no sheet
    summary = background_jobs.Job(job_id="summary-x", conversation_id="root", goal="g",
                                  acceptance=background_jobs.criteria_to_acceptance([]), outside_seen=False,
                                  outcome="done", results={"answer-delivered": "passed"}, reports="[reports]")
    await background_jobs._report(summary, "All three are done.")
    async with execution_db() as db:
        rows = {m.conversation_id: m.content for m in (await db.scalars(select(ArslanMessage))).all()}
    assert rows["sub-child"] == ("Wrote the notes.\n\n**✅ Checked**\n- An answer was delivered\n"
                                 "\n**⚠️ Not verified**\n- `/Users/me/notes/a.md` — saved; contents not checked")
    assert rows["root"] == "All three are done."


# -- 4: a turn the user is present for has no sheet ----------------------------------------------------------------
from tests.server.test_run_command_confirm_flow import _collect_until, app_client  # noqa: E402,F401


def test_a_chat_turn_posts_no_sheet(app_client, monkeypatch):  # noqa: F811
    from arslan.models import LLMResponse
    from server.services import personal_context as pc, task_context
    import uuid

    class Adapter:
        async def chat(self, system, user, history=None, tools=None, temperature=0.7):
            return LLMResponse(content="Hello! I'm here.", tool_calls=[], usage={})

    async def load(cid, **kwargs):
        identity = str(uuid.uuid4())
        return pc.TaskMemoryContext(task_id=identity, run_id=f"turn-{identity}", conversation_id=cid,
                                    no_memory=True, no_learning=True, query=kwargs.get("user_message", ""))
    monkeypatch.setattr(task_context, "load", load)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "hi"})
        _collect_until(ws, "stream_end", max_frames=400)

    async def stored():
        async with app_client.db_maker() as db:
            return [m.content for m in (await db.scalars(select(ArslanMessage).where(
                ArslanMessage.role == "arslan"))).all()]
    replies = app_client.portal.call(stored)
    assert replies and all("Hello" in r and "✅" not in r and "👀" not in r and "⚠️" not in r for r in replies)


def test_the_sheet_module_is_posted_only_by_a_background_job():
    """A turn the user is present for (`run_turn` without `_acceptance`) and a scheduled fire (INB9-b) post none: the
    one place that renders a sheet is the job's own report."""
    root = Path(__file__).resolve().parents[2] / "server"
    imports = re.compile(r"^\s*from server\.services(?:\.acceptance_sheet)? import[^\n]*\bacceptance_sheet\b|"
                         r"^\s*from server\.services\.acceptance_sheet import", re.MULTILINE)
    users = sorted(str(p.relative_to(root)) for p in root.rglob("*.py")
                   if imports.search(p.read_text(encoding="utf-8")) and p.name != "acceptance_sheet.py")
    assert users == ["services/background_jobs.py"]
