"""L7-2: the goal round in `turn_answer.finish` (docs/plans/0164/L7-goal-mode.md: "How it continues", "The reply never
counts", "How done is decided", "No progress", "Checks Arslan can't verify").

A round is one answer. Its verdict comes from each check's own condition, read by the host (the file on disk, the host's
own run of a `check:` line, the judge over the named file's content), never from the answer. With no goal set, the
turn is unchanged: the z3 guard tests (test_tool_offer_table, test_gate_order, test_turn_*, test_command_gate_refusals)
cover that, unchanged.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from arslan.companion.contracts import AcceptanceCheck, TaskSpec
from arslan.models import LLMResponse
from server.db.task_models import TaskEvent
from server.orchestrator import tool_loop
from server.services import goal_mode, task_service, task_validation
from server.services.goal_mode import GoalCheck, GoalProgress, GoalSpec, SeenMeasure
from server.services.task_repository import repository

PHRASE = "INV-07"
CLAIM = f"Done: notes.md contains {PHRASE}, and every check of the goal is met."


def _check(id="c1", **kw) -> GoalCheck:
    return GoalCheck.model_validate({"id": id, "description": "The notes name the invoice", "kind": "file_contains",
                                     "path": "notes.md", "phrases": (PHRASE,), **kw})


def _goal(*checks) -> GoalSpec:
    return GoalSpec(objective="Reconcile the synthetic invoices into notes.md", checks=checks or (_check(),))


def _rule(kind, **rule) -> AcceptanceCheck:
    return AcceptanceCheck.model_validate({"id": "c1", "description": "Check fixture", "evaluator": "deterministic",
                                           "rule": {"kind": kind, **rule}})


def _context(tmp_path, **kw) -> dict:
    return {"roots": [tmp_path.resolve()], "workspace": tmp_path.resolve(), "since": None, "goal": True, **kw}


# -- the verdict: each check's own condition, never the reply --------------------------------------------------------

def test_a_goal_never_counts_a_text_rule_except_answer_delivered(tmp_path):
    rule = _rule("text", contains=[PHRASE])
    assert task_validation.evaluate(rule, CLAIM, [], [], _context(tmp_path))["status"] == "failed"
    assert task_validation.evaluate(rule, CLAIM, [], [], {})["status"] == "passed"         # no goal: as before
    delivered = AcceptanceCheck.model_validate(task_service.ANSWER_DELIVERED)
    assert task_validation.evaluate(delivered, CLAIM, [], [], _context(tmp_path))["status"] == "passed"


def test_a_goal_command_check_reads_only_the_hosts_run_never_the_workers(tmp_path):
    rule = _rule("code_test", target="python3 tests/run_checks.py", argv=["python3", "tests/run_checks.py"])
    run = {"tool": "run_command", "args": {"command": "python3 tests/run_checks.py",
                                           "argv": ["python3", "tests/run_checks.py"]},
           "result": {"ok": True, "exit_code": 0, "stdout": "all passed", "stderr": ""}}
    assert task_validation.evaluate(rule, "", [], [run], {})["status"] == "passed"         # no goal: as before
    worker = task_validation.evaluate(rule, "", [], [run], _context(tmp_path))
    assert worker["status"] == "not_run" and "measure" not in worker
    host = task_validation.evaluate(rule, "", [], [], _context(tmp_path, host_runs=[run]))
    assert host["status"] == "passed"
    failing = {**run, "result": {"ok": True, "exit_code": 1, "stdout": "FAILED test_rounding", "stderr": ""}}
    again = {**run, "result": {"ok": True, "exit_code": 1, "stdout": "FAILED test_dates", "stderr": ""}}
    first, same, other = (task_validation.evaluate(rule, "", [], [], _context(tmp_path, host_runs=[item]))
                          for item in (failing, failing, again))
    assert first["status"] == "failed" and first["measure"] == same["measure"] != other["measure"]


def test_a_file_contains_measure_is_the_phrases_found_not_the_files_bytes(tmp_path):
    rule = _rule("file_contains", target="notes.md", contains=["INV-07", "INV-08"])
    notes = tmp_path / "notes.md"
    notes.write_text("INV-07 reconciled")
    first = task_validation.evaluate(rule, "", [], [], _context(tmp_path))
    notes.write_text("INV-07 reconciled, again, with new bytes!")
    rewritten = task_validation.evaluate(rule, "", [], [], _context(tmp_path))
    assert first["status"] == rewritten["status"] == "failed"
    assert first["measure"] == rewritten["measure"] and first["measure"]["size"] == 1
    notes.write_text("INV-07 and INV-08 reconciled")
    assert task_validation.evaluate(rule, "", [], [], _context(tmp_path))["status"] == "passed"
    notes.unlink()
    assert task_validation.evaluate(rule, "", [], [], _context(tmp_path))["status"] == "failed"


def test_a_folder_count_and_the_sources_read_are_measured(tmp_path):
    (tmp_path / "summaries").mkdir()
    (tmp_path / "summaries" / "n01.md").write_text("one")
    folder = task_validation.evaluate(_rule("file_saved", target="summaries", minimum=3), "", [], [],
                                      _context(tmp_path))
    assert folder["status"] == "failed" and folder["measure"]["size"] == 1
    read = lambda path: {"tool": "read_file", "args": {"path": path}, "result": {"ok": True, "path": path}}  # noqa: E731
    sources = _rule("sources_read", target="notes/", minimum=3)
    trace = [read("/w/notes/n01.md"), read("/w/other.md"), read("/w/notes/n01.md")]
    assert task_validation.evaluate(sources, "", [], trace, _context(tmp_path))["measure"]["size"] == 1


# -- the progress rule -------------------------------------------------------------------------------------------------

def _measure(check_id: str, value: str, size: int | None = None) -> SeenMeasure:
    import hashlib
    return SeenMeasure(check_id=check_id, digest=hashlib.sha256(value.encode()).hexdigest(), size=size)


def _after(spec, progress, met=(), measures=()):
    return goal_mode.after_verdict(spec, progress, met=frozenset(met), measures=tuple(measures))


def test_a_set_measure_counts_only_when_it_grows():
    spec = _goal(_check(phrases=("INV-07", "INV-08")))
    start = GoalProgress(status="active", unmet=("c1",))
    one = _after(spec, start, measures=[_measure("c1", "INV-07", 1)])
    swapped = _after(spec, one, measures=[_measure("c1", "INV-08", 1)])        # new, but not larger
    assert (one.stall, swapped.stall) == (1, 2)
    assert _after(spec, swapped, measures=[_measure("c1", "INV-07 INV-08", 2)]).stall == 0


def test_user_confirmed_checks_are_never_met_by_arslan_and_end_the_goal_at_review():
    spec = _goal(_check(), _check(id="happy", kind="judgement", path=None, phrases=(), user_confirmed=True,
                                  description="the user is happy"))
    start = GoalProgress(status="active", unmet=("c1",))
    claimed = _after(spec, start, met=("happy",))
    assert claimed.status == "active" and claimed.stall == 1 and "happy" not in claimed.ever_met
    assert _after(spec, start, met=("c1", "happy")).status == "review"
    assert _after(spec, start, met=("c1",)).status == "review"
    assert _after(_goal(), start, met=("c1",)).status == "complete"


# -- the round, through a whole turn ---------------------------------------------------------------------------------

STEP = "Add invoice INV-07 to notes.md, or send a note with where it is."


async def _goal_turn(goal, monkeypatch, tmp_path, replies, *, judge=lambda user: '{"passed": false}',
                     step=lambda user: json.dumps({"steps": [STEP]}), **kwargs):
    """One goal job's turn on a scripted model. `replies(n)` is the n-th answer, and may change files first (the
    work). The judge's and the blocked step's requests are told apart by their system text."""
    async def disk(started_at):
        return {"roots": [tmp_path.resolve()], "workspace": tmp_path.resolve(), "since": None}
    monkeypatch.setattr(task_validation, "_disk_context", disk)
    calls = {"turn": [], "judge": [], "step": []}

    class Adapter:
        async def chat(self, system, user, **kw):
            if system.startswith("Assess only"):
                calls["judge"].append(user)
                return LLMResponse(usage={}, content=judge(user))
            if "one step for the user" in system:
                calls["step"].append(user)
                return LLMResponse(usage={}, content=step(user))
            calls["turn"].append(json.dumps([system, user, kw.get("history")], default=str))
            return LLMResponse(usage={}, content=replies(len(calls["turn"])))
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)

    async def tools():
        return []

    async def body(emit):
        return await tool_loop.run_native(system="Goal fixture", user_content=goal.objective, history=[],
                                          resolve_tools=tools, emit=emit, on_chunk=lambda text: None,
                                          allow_escalation=False, goal=goal, **kwargs)
    spec = TaskSpec.model_validate({"id": "goal-task", "instruction": goal.objective, "locale": "en",
                                    "scope": {"kind": "task", "owner_id": "local", "task_id": "goal-task"},
                                    "acceptance": goal_mode.acceptance(goal)})
    async with repository() as repo:
        created = await repo.create(spec, "goal")
        started = await repo.start(spec.id, created["version"])
    result = await task_service._launch(started, lambda event: None, body)
    async with repository() as repo:
        task = await repo.get("goal-task")
        record = GoalProgress.model_validate((await repo.latest_checkpoint(task.id))["progress"]["goal"])
        rounds = await repo.db.scalar(select(func.count()).select_from(TaskEvent).where(
            TaskEvent.task_id == task.id, TaskEvent.kind == "goal_round"))
    return result, task, record, rounds, calls


async def test_a_goal_met_in_round_1_completes_with_no_further_round(execution_db, monkeypatch, tmp_path):
    (tmp_path / "notes.md").write_text(f"Reconciled {PHRASE}")
    result, task, record, rounds, calls = await _goal_turn(_goal(), monkeypatch, tmp_path, lambda n: "Reconciled.")
    assert len(calls["turn"]) == 1 and task.phase == "succeeded"
    assert (record.status, record.round, record.ever_met, rounds) == ("complete", 1, ("c1",), 1)
    assert result["final"] == "Reconciled."


async def test_an_unmet_check_goes_back_as_a_goal_round_and_is_met_in_the_next(execution_db, monkeypatch, tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("nothing yet")

    def replies(n):
        if n == 2:
            notes.write_text(f"Reconciled {PHRASE}")          # the second round's work
        return "Here is where the reconciliation stands."
    result, task, record, rounds, calls = await _goal_turn(_goal(), monkeypatch, tmp_path, replies)
    assert len(calls["turn"]) == 2 and "Goal round 1. Not met: c1" in calls["turn"][1]
    assert "Keep the full objective" in calls["turn"][1]
    assert task.phase == "succeeded" and (record.status, record.round, rounds) == ("complete", 2, 2)


@pytest.mark.parametrize("step,shown", [
    (lambda user: json.dumps({"steps": [STEP]}), STEP),
    (lambda user: json.dumps({"steps": []}), None),
    (lambda user: json.dumps({"steps": [STEP, "Also rewrite the check."]}), None),
    (lambda user: "not JSON", None),
], ids=["one step", "none: the fixed line", "two: the fixed line", "unreadable: the fixed line"])
async def test_a_goal_that_only_claims_is_blocked_after_round_3_with_one_user_step(
        step, shown, execution_db, monkeypatch, tmp_path):
    (tmp_path / "notes.md").write_text("nothing yet")
    result, task, record, rounds, calls = await _goal_turn(_goal(), monkeypatch, tmp_path, lambda n: CLAIM, step=step)
    assert len(calls["turn"]) == 3 and len(calls["step"]) == 1
    assert task.phase == "waiting_user" and task.pause_reason == "goal_blocked"
    assert (record.status, record.round, record.stall, record.ever_met, rounds) == ("blocked", 3, 3, (), 3)
    final = result["final"]
    assert final.startswith(CLAIM)
    if shown is not None:
        assert final.rstrip().endswith(shown)
    else:
        assert STEP not in final and "Also rewrite" not in final and "c1" in final.split(CLAIM, 1)[1]
    assert CLAIM not in calls["step"][0]                       # the step is written from receipts, not the reply


async def test_when_only_user_confirmed_checks_are_left_the_goal_stops_at_review(execution_db, monkeypatch, tmp_path):
    (tmp_path / "notes.md").write_text(f"Reconciled {PHRASE}")
    goal = _goal(_check(), _check(id="happy", kind="judgement", path=None, phrases=(), user_confirmed=True,
                                  description="the user is happy with it"))
    result, task, record, rounds, calls = await _goal_turn(goal, monkeypatch, tmp_path, lambda n: "Reconciled.")
    assert len(calls["turn"]) == 1 and calls["judge"] == []
    assert task.phase == "waiting_user" and task.pause_reason == "acceptance_review_required"
    assert record.status == "review" and "happy" in result["final"]


async def test_a_forced_step_has_no_goal_round_and_the_goal_is_budget_limited(execution_db, monkeypatch, tmp_path):
    (tmp_path / "notes.md").write_text("nothing yet")
    result, task, record, rounds, calls = await _goal_turn(_goal(), monkeypatch, tmp_path, lambda n: "Out of room.",
                                                           max_tool_calls=0)
    assert len(calls["turn"]) == 1 and task.phase == "waiting_user"
    assert task.pause_reason == "task_budget_exhausted"
    assert (record.status, rounds) == ("budget_limited", 1)


async def test_the_judge_reads_the_named_file_on_disk_and_never_the_answer(execution_db, monkeypatch, tmp_path):
    (tmp_path / "report.md").write_text("one line")
    goal = _goal(_check(kind="judgement", path="report.md", phrases=(), by_user=True,
                        description="The report explains every reconciled invoice"))
    rich = "report.md now has RICH-SECTION-ALPHA, a full table and every invoice explained."
    result, task, record, rounds, calls = await _goal_turn(goal, monkeypatch, tmp_path, lambda n: rich)
    assert len(calls["judge"]) == 3
    assert all("one line" in user and "RICH-SECTION-ALPHA" not in user for user in calls["judge"])
    assert record.status == "blocked" and record.ever_met == ()


async def test_a_judgement_over_a_file_the_host_cant_read_is_not_met_and_never_judged(
        execution_db, monkeypatch, tmp_path):
    goal = _goal(_check(kind="judgement", path="missing.md", phrases=(), by_user=True,
                        description="The report explains every reconciled invoice"))
    result, task, record, rounds, calls = await _goal_turn(goal, monkeypatch, tmp_path, lambda n: CLAIM,
                                                           judge=lambda user: '{"passed": true}')
    assert calls["judge"] == [] and record.status == "blocked"


async def test_wrap_up_past_the_soft_limit_has_no_goal_round_and_the_goal_is_budget_limited(
        execution_db, monkeypatch, tmp_path):
    # Card: "No goal round on a forced step or in wrap-up", so the soft limit stays where a goal stops and the 1.5x
    # hard limit never becomes the real one. Wrap-up is `Budget.soft_reached()`, with no forced step yet.
    from arslan.execution_budget import Budget
    monkeypatch.setattr(Budget, "soft_reached", lambda self: True)
    (tmp_path / "notes.md").write_text("nothing yet")
    result, task, record, rounds, calls = await _goal_turn(_goal(), monkeypatch, tmp_path, lambda n: CLAIM)
    assert len(calls["turn"]) == 1 and calls["step"] == []
    assert task.phase == "waiting_user" and task.pause_reason == "task_budget_exhausted"
    assert (record.status, record.round, rounds) == ("budget_limited", 1, 1)


async def test_a_no_progress_stop_on_a_forced_step_ends_the_goal_blocked_not_budget_limited(
        execution_db, monkeypatch, tmp_path):
    from arslan.runtime_policy import ProgressPolicy
    monkeypatch.setattr(ProgressPolicy, "stopped", property(lambda self: True))
    (tmp_path / "notes.md").write_text("nothing yet")
    result, task, record, rounds, calls = await _goal_turn(_goal(), monkeypatch, tmp_path, lambda n: CLAIM)
    assert len(calls["turn"]) == 1 and len(calls["step"]) == 1
    assert task.phase == "waiting_user" and task.pause_reason == "goal_blocked"
    assert (record.status, record.round, rounds) == ("blocked", 1, 1)


async def test_a_file_that_gains_a_phrase_each_round_is_progress_and_the_goal_completes(
        execution_db, monkeypatch, tmp_path):
    # Measures counted through a real turn: without them a steady goal would be blocked at round 3.
    phrases = tuple(f"A{i}" for i in range(1, 7))
    notes = tmp_path / "notes.md"
    notes.write_text("A1")

    def replies(n):
        notes.write_text(" ".join(phrases[:n + 1]))     # round n's work: one more phrase
        return CLAIM
    result, task, record, rounds, calls = await _goal_turn(_goal(_check(phrases=phrases)), monkeypatch, tmp_path,
                                                           replies)
    assert len(calls["turn"]) == 5 and task.phase == "succeeded"
    assert (record.status, record.round, record.stall, rounds) == ("complete", 5, 0, 5)


def test_a_check_already_met_that_grows_is_no_progress_for_the_goal():
    spec = _goal(_check(), _check(id="c2", kind="sources_read", path="notes/", phrases=(), minimum=1,
                                  description="Read the notes"))
    before = GoalProgress(status="active", round=1, stall=1, unmet=("c1",), ever_met=("c2",),
                          seen=(_measure("c2", "n01", 1),))
    after = _after(spec, before, met=("c2",), measures=[_measure("c2", "n01 n02", 2)])
    assert (after.status, after.stall, after.unmet) == ("active", 2, ("c1",))


async def test_a_goal_judges_its_judgement_checks_even_when_a_deterministic_check_fails(
        execution_db, monkeypatch, tmp_path):
    (tmp_path / "report.md").write_text("one line")
    goal = _goal(_check(), _check(id="c2", kind="judgement", path="report.md", phrases=(), by_user=True,
                                  description="The report explains every reconciled invoice"))
    (tmp_path / "notes.md").write_text("nothing yet")
    result, task, record, rounds, calls = await _goal_turn(goal, monkeypatch, tmp_path, lambda n: CLAIM,
                                                           judge=lambda user: '{"passed": true}')
    assert len(calls["judge"]) >= 1 and "c2" in record.ever_met and record.unmet == ("c1",)


async def test_the_judge_gets_at_most_20000_characters_of_the_named_file(execution_db, monkeypatch, tmp_path):
    (tmp_path / "report.md").write_text("x" * 20_000 + "TAIL-PAST-THE-CAP")
    goal = _goal(_check(kind="judgement", path="report.md", phrases=(), by_user=True,
                        description="The report explains every reconciled invoice"))
    result, task, record, rounds, calls = await _goal_turn(goal, monkeypatch, tmp_path, lambda n: CLAIM)
    assert calls["judge"] and all("x" * 1000 in user and "TAIL-PAST-THE-CAP" not in user for user in calls["judge"])
