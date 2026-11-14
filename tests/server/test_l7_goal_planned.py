"""L7's planned tests for the later slices, red until their slice lands (docs/plans/0164/L7-goal-mode.md, Method).

Each is a strict xfail that names its slice. Where the slice's code doesn't exist yet, the test calls the function the
slice is to add, named here (`goal_mode.after_verdict`, `unverifiable`, `record_protected`, `protected_changes`), and
`raises=` limits the xfail to that function being absent. So once the slice lands the test either passes (strict:
XPASS is a failure, and the slice removes the marker) or fails on its assertions; it can't stay quietly expected.
A slice that names a function otherwise renames it here. The behavioural ones (`/goal` in `handle_user_message`,
`resume_turn` refusing a goal row) run today's code and fail on their assertions (`raises=AssertionError`) until the
slice lands.
DELETE-BY: v0.1.64, each marker by its slice (L7-3 to L7-5; L7-2 took its four off).
"""
from __future__ import annotations

import hashlib
import time

import pytest

from arslan.companion.contracts import AcceptanceCheck
from arslan.execution_budget import current as budget
from server.services import goal_mode, personal_context as pc, task_context, task_service, task_validation
from server.services.goal_mode import GoalCheck, GoalProgress, GoalSpec, SeenMeasure
from server.services.task_repository import TaskError, repository

MISSING = (AttributeError,)          # the slice's function isn't there yet


def _check(id="c1", **kw) -> GoalCheck:
    return GoalCheck.model_validate({"id": id, "description": "Check fixture", "kind": "file_saved",
                                     "path": "out.md", **kw})


def _measure(check_id: str, value: str, size: int | None = None) -> SeenMeasure:
    return SeenMeasure(check_id=check_id, digest=hashlib.sha256(value.encode()).hexdigest(), size=size)


def _rounds(spec: GoalSpec, script) -> list[GoalProgress]:
    """Each round's verdict, as L7-2's `after_verdict(spec, progress, met=, measures=)` records it."""
    progress, out = GoalProgress(status="active", unmet=tuple(c.id for c in spec.checks)), []
    for met, measures in script:
        progress = goal_mode.after_verdict(spec, progress, met=frozenset(met), measures=tuple(measures))
        out.append(progress)
    return out


# -- L7-2: the goal round (landed: these four are permanent now) ----------------------------------------------------

def test_l7_2_the_reply_never_counts_only_the_named_file_on_disk(tmp_path):
    check = AcceptanceCheck.model_validate({"id": "c1", "description": "Check fixture", "evaluator": "deterministic",
                                            "rule": {"kind": "file_contains", "target": "notes.md",
                                                     "contains": ["INV-07"]}})
    (tmp_path / "notes.md").write_text("nothing yet")
    context = {"roots": [tmp_path.resolve()], "workspace": tmp_path.resolve(), "since": time.time() - 60}
    reply = "Done: notes.md contains INV-07, so every check is met."
    assert task_validation.evaluate(check, reply, [], [], context)["status"] != "passed"
    (tmp_path / "notes.md").write_text("Reconciled INV-07")
    assert task_validation.evaluate(check, "", [], [], context)["status"] == "passed"


def test_l7_2_a_long_but_steady_goal_is_never_blocked():
    """Progress only from a new measure or a check first met: the measure grows in rounds 2, 4, 6, ..., met at 12."""
    spec = GoalSpec(objective="Summarise every note", checks=(_check(kind="file_saved", path="summaries",
                                                                     minimum=12),))
    script = [((), [_measure("c1", f"count-{r // 2}", r // 2)]) for r in range(1, 12)] + [(("c1",), [])]
    rounds = _rounds(spec, script)
    assert all(r.status != "blocked" for r in rounds) and rounds[-1].status == "complete"


def test_l7_2_a_busy_goal_without_progress_is_blocked_right_after_round_3():
    spec = GoalSpec(objective="Make the check pass", checks=(
        _check(kind="check", path=None, argv=("python3", "tests/run_checks.py"), by_user=True),))
    same = [((), [_measure("c1", "exit=1 FAILED test_rounding")])] * 4
    rounds = _rounds(spec, same)
    assert [r.status for r in rounds[:3]] == ["active", "active", "blocked"]
    assert [r.stall for r in rounds[:3]] == [1, 2, 3]


def test_l7_2_a_check_met_again_or_a_measure_seen_before_is_not_progress():
    spec = GoalSpec(objective="Keep both files right", checks=(_check(), _check(id="c2", path="b.md")))
    rounds = _rounds(spec, [(("c1",), []), ((), [_measure("c2", "x")]), (("c1",), [_measure("c2", "x")])])
    assert [r.stall for r in rounds] == [0, 0, 1]
    assert rounds[-1].ever_met == ("c1",)


# -- L7-3: `/goal`, drafting and the flag for checks Arslan can't verify ----------------------------------------------

@pytest.mark.xfail(strict=True, raises=MISSING, reason="L7-3 adds the flag for checks Arslan can't verify")
def test_l7_3_checks_arslan_cant_verify_are_flagged():
    spec = GoalSpec(objective="Make report.md look nice", checks=(
        _check(id="nice", kind="judgement", path=None, description="looks nice"),
        _check(id="drafted", kind="judgement", path="report.md"),               # a path drafting added
        _check(id="named", kind="judgement", path="report.md", by_user=True),
        _check(id="saved"),
        _check(id="happy", kind="judgement", path=None, description="the user is happy", user_confirmed=True),
        _check(id="run", kind="check", path=None, argv=("pytest", "-q"), by_user=True)))
    assert set(goal_mode.unverifiable(spec)) == {"nice", "drafted"}


async def _message_reaches_the_turn(execution_db, monkeypatch, *, on: bool) -> tuple[list, list]:
    from server.orchestrator import arslan
    from server.services import settings_service
    answered, events = [], []

    async def answer(conversation_id, user_message, emit, **kwargs):
        answered.append(user_message)

    async def flag(db):
        return on
    monkeypatch.setattr(arslan, "_handle_answer", answer)
    monkeypatch.setattr(arslan, "_after_turn_later", lambda *a, **k: None)
    monkeypatch.setattr(settings_service, "goal_mode", flag)
    await arslan.handle_user_message("goal-chat", "/goal status", events.append)
    return answered, events


async def test_with_goal_mode_off_slash_goal_is_plain_text(execution_db, monkeypatch):
    """Permanent: the flag off, `/goal` goes to the turn as the user's words, unchanged."""
    answered, _ = await _message_reaches_the_turn(execution_db, monkeypatch, on=False)
    assert answered == ["/goal status"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="L7-3 parses /goal in handle_user_message")
async def test_l7_3_slash_goal_is_parsed_in_handle_user_message_before_any_model_call(execution_db, monkeypatch):
    answered, events = await _message_reaches_the_turn(execution_db, monkeypatch, on=True)
    assert answered == [] and events


# -- L7-4: resume -------------------------------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="L7-4 makes resume_turn refuse a goal row (Resume re-queues the job)")
async def test_l7_4_resume_turn_refuses_a_goal_row(execution_db, monkeypatch):
    async def load(cid, **kwargs):
        return pc.TaskMemoryContext(task_id="goal-task", run_id="initial", conversation_id=cid, no_learning=True)

    async def attempt(emit):
        budget().tool()
        task_service.current().pause_reason = "task_no_progress"
        return "Partial evidence, not completion"
    monkeypatch.setattr(task_context, "load", load)
    await task_context.execute_entry("goal-chat", "Sort the synthetic invoices", lambda event: None, attempt,
                                     driver={"kind": "background", "goal": True})
    async with repository() as repo:
        row = await repo.get("goal-task")
        assert row.privacy["driver"] == {"kind": "background", "goal": True}
    from server.orchestrator import arslan
    answered = []

    async def answer(conversation_id, user_message, emit, **kwargs):
        answered.append(user_message)
        return "Resumed."
    monkeypatch.setattr(arslan, "_handle_answer", answer)
    try:
        await task_service.resume_turn("goal-task", row.version, "goal-chat", lambda event: None)
        refused = False
    except TaskError:
        refused = True
    assert refused and answered == []


# -- L7-5: the protected set ---------------------------------------------------------------------------------------

def _flat(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a - b\n")
    return tmp_path


@pytest.mark.xfail(strict=True, raises=MISSING, reason="L7-5 records and verifies the protected set")
def test_l7_5_a_protected_test_changed_stops_the_goal_and_the_work_never_does(tmp_path):
    root = _flat(tmp_path)
    line = _check(kind="check", path=None, argv=("pytest", "-q"), by_user=True)     # no file in its argv
    protected = goal_mode.record_protected(root, (line,))
    (root / "app.py").write_text("def add(a, b):\n    return a + b\n")
    assert goal_mode.protected_changes(protected, root) == ((), ())
    (root / "tests" / "test_app.py").write_text("def test_add():\n    assert True\n")
    assert goal_mode.protected_changes(protected, root)[0] == ("tests/test_app.py",)


@pytest.mark.xfail(strict=True, raises=MISSING, reason="L7-5 leaves bytecode caches out of the scan")
def test_l7_5_a_pycache_beside_the_protected_tests_doesnt_stop_the_goal(tmp_path):
    root = _flat(tmp_path)
    protected = goal_mode.record_protected(root, (_check(kind="check", path=None, argv=("pytest", "-q"), by_user=True),))
    (root / "tests" / "__pycache__").mkdir()
    (root / "tests" / "__pycache__" / "test_app.cpython-311-pytest-8.pyc").write_bytes(b"\x00cache")
    assert goal_mode.protected_changes(protected, root) == ((), ())
    (root / "tests" / "test_extra.py").write_text("def test_extra():\n    pass\n")
    assert goal_mode.protected_changes(protected, root)[0] == ("tests/test_extra.py",)


@pytest.mark.xfail(strict=True, raises=MISSING, reason="L7-5 accepts only the declared output patterns")
def test_l7_5_only_a_declared_output_pattern_is_accepted(tmp_path):
    root = _flat(tmp_path)
    (root / "tests" / "revealed").mkdir()
    line = _check(kind="check", path=None, argv=("python3", "tests/run_checks.py"), by_user=True,
                  outputs=("tests/revealed/test_step_*.py",))
    protected = goal_mode.record_protected(root, (line,))
    (root / "tests" / "revealed" / "test_step_2.py").write_text("def test_step_2():\n    pass\n")
    changed, accepted = goal_mode.protected_changes(protected, root, outputs=line.outputs)
    assert changed == () and [item.path for item in accepted] == ["tests/revealed/test_step_2.py"]
    (root / "tests" / "revealed" / "__init__.py").write_text("")
    assert goal_mode.protected_changes(protected, root, outputs=line.outputs)[0] == ("tests/revealed/__init__.py",)
