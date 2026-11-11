"""L7-1: goal mode's types and their defaults (docs/plans/0164/L7-goal-mode.md). Nothing reads them yet.

With no goal set a turn is unchanged: `TurnRequest.goal` is None, a checkpoint's `Progress` is byte for byte as
before L7, the setting is off, and only the one driver dict the card names is new. The behaviour guard is #841's
permanent tests (test_tool_offer_table.py, test_gate_order.py, the test_turn_* files, test_command_gate_refusals.py),
unchanged. The planned tests of the later slices are in test_l7_goal_planned.py.
"""
from __future__ import annotations

import typing

import pytest
from pydantic import ValidationError

from arslan.companion.contracts import TaskState
from arslan.execution_budget import MAX_USD_CAP, TIERS
from server.orchestrator.turn_state import TurnRequest, TurnState
from server.schemas import SettingsIn, SettingsOut
from server.services import goal_mode, settings_service, task_service
from server.services.goal_mode import GoalCheck, GoalProgress, GoalSpec, ProtectedFile, ProtectedSet, SeenMeasure
from server.services.task_repository import Progress, TaskError

SHA = "a" * 64
# Progress() as main wrote it before L7: what a checkpoint stores, and what a resumed turn's recovery text carries.
NO_GOAL_JSON = ('{"schema_version":1,"completed_steps":[],"evidence":[],"artifacts":[],"pending_actions":[],'
                '"continuation_ref":null,"loop_fingerprints":[],"validation_repairs":[]}')


def _check(id="c1", **kw) -> GoalCheck:
    return GoalCheck.model_validate({"id": id, "description": "Check fixture", "kind": "file_saved",
                                     "path": "out.md", **kw})


def _spec(*checks, **kw) -> GoalSpec:
    return GoalSpec(objective="Sort the synthetic invoices", checks=checks or (_check(),), **kw)


async def _resolve():
    return []


# -- no goal: as before L7 -----------------------------------------------------------------------------------------

def test_a_turn_has_no_goal_unless_one_is_set():
    request = TurnRequest(system="s", user_content="u", history=[], emit=lambda e: None, on_chunk=lambda c: None,
                          resolve_tools=_resolve)
    state = TurnState()
    assert request.goal is None and request.steer_key is None
    assert (state.goal_round, state.goal_stall, state.goal_unmet) == (0, 0, ())


def test_progress_without_a_goal_is_byte_for_byte_as_before():
    assert Progress().model_dump_json() == NO_GOAL_JSON
    assert "goal" not in Progress().model_dump(mode="json")
    assert Progress.model_validate_json(NO_GOAL_JSON).goal is None


def test_progress_carries_a_goal_record_through_a_checkpoint():
    record = GoalProgress(status="active", round=2, stall=1, unmet=("c1",), ever_met=("c2",),
                          seen=(SeenMeasure(check_id="c1", digest=SHA, size=3),))
    saved = Progress(goal=record).model_dump(mode="json")
    assert saved["goal"]["seen"] == [{"schema_version": 1, "check_id": "c1", "digest": SHA, "size": 3}]
    assert Progress.model_validate(saved).goal == record


async def test_goal_mode_is_off_by_default_and_only_true_turns_it_on(client):
    from server.db import session as db_session
    assert "goal_mode" in settings_service._PLAIN_KEYS and "goal_mode" in SettingsIn.model_fields
    assert SettingsOut.model_fields["goal_mode"].default == ""
    async with db_session.AsyncSessionLocal() as db:
        assert await settings_service.goal_mode(db) is False
    for value, on in (("true", True), ("false", False), ("yes", False), ("true", True)):
        r = await client.put("/api/v1/settings", json={"goal_mode": value})
        assert r.status_code == 200 and r.json()["goal_mode"] == value
        async with db_session.AsyncSessionLocal() as db:
            assert await settings_service.goal_mode(db) is on


# -- the driver: exactly one new dict ------------------------------------------------------------------------------

def test_a_goal_row_is_a_background_driver_marked_goal():
    driver = {"kind": "background", "goal": True}
    saved = task_service.checked_driver(driver)
    assert saved == driver and saved is not driver


@pytest.mark.parametrize("driver", [
    {"kind": "background", "goal": 1}, {"kind": "background", "goal": 1.0}, {"kind": "background", "goal": False},
    {"kind": "background", "goal": "true"}, {"kind": "host", "goal": True}, {"kind": "goal"},
    {"kind": "background", "goal": True, "id": 3}, {"goal": True}])
def test_no_other_goal_shaped_driver_is_accepted(driver):
    with pytest.raises(TaskError, match="task_invalid_driver"):
        task_service.checked_driver(driver)


# -- frozen: recorded when it happens, replaced whole --------------------------------------------------------------

@pytest.mark.parametrize("value, name, new", [
    (lambda: _spec(), "objective", "Something else"), (lambda: _spec(), "checks", ()),
    (lambda: _check(), "user_confirmed", True), (lambda: GoalProgress(), "stall", 2),
    (lambda: GoalProgress(), "seen", ()), (lambda: ProtectedFile(path="tests/test_a.py", sha256=SHA), "sha256", None),
    (lambda: ProtectedSet(), "files", ())])
def test_goal_records_are_frozen(value, name, new):
    with pytest.raises(ValidationError):
        setattr(value(), name, new)


def test_a_rounds_record_is_replaced_whole_and_its_sets_are_tuples():
    record = GoalProgress(seen=[SeenMeasure(check_id="c1", digest=SHA)], unmet=["c1"])
    assert isinstance(record.seen, tuple) and isinstance(record.unmet, tuple)
    later = record.model_copy(update={"round": 1})
    assert (record.round, later.round, later.seen) == (0, 1, record.seen)


# -- the parts, as the card specifies them -------------------------------------------------------------------------

def test_each_status_maps_onto_an_existing_phase():
    assert set(goal_mode.STATUS_PHASE) == set(typing.get_args(goal_mode.GoalStatus))
    phases = set(typing.get_args(TaskState.model_fields["phase"].annotation))
    assert {phase for phase, _ in goal_mode.STATUS_PHASE.values()} <= phases
    assert goal_mode.STATUS_PHASE["complete"] == ("succeeded", None)
    assert goal_mode.STATUS_PHASE["review"] == ("waiting_user", "acceptance_review_required")
    assert goal_mode.STATUS_PHASE["budget_limited"] == ("waiting_user", "task_budget_exhausted")
    assert GoalProgress().status == "not_started"         # nothing runs before Start


def test_file_contains_names_a_file_and_its_phrases():
    assert _check(kind="file_contains", phrases=("INV-07",)).path == "out.md"
    for bad in ({"kind": "file_contains", "path": None, "phrases": ("P",)}, {"kind": "file_contains"},
                {"kind": "file_saved", "phrases": ("P",)}, {"kind": "judgement", "minimum": 2}):
        with pytest.raises(ValidationError):
            _check(**bad)


def test_only_the_user_writes_a_check_line_and_declares_its_outputs():
    line = _check(kind="check", path=None, argv=("python3", "tests/run_checks.py"), by_user=True,
                  outputs=("tests/revealed/test_step_*.py",))
    assert line.outputs == ("tests/revealed/test_step_*.py",)
    with pytest.raises(ValidationError):                     # drafting never produces `check:`
        _check(kind="check", path=None, argv=("pytest", "-q"))
    with pytest.raises(ValidationError):                     # nor declares an output
        _check(kind="judgement", outputs=("out/*.md",), by_user=True)
    with pytest.raises(ValidationError):
        _check(kind="check", path=None, by_user=True)


@pytest.mark.parametrize("folder", ["tests/revealed/", "tests/revealed/*", "tests/**", "*", "**"])
def test_a_declared_output_is_never_a_whole_folder(folder):
    with pytest.raises(ValidationError):
        _check(kind="check", path=None, argv=("python3", "c.py"), by_user=True, outputs=(folder,))


def test_a_user_confirmed_check_is_marked_on_the_check():
    looks = _check(kind="judgement", path=None, user_confirmed=True)
    assert looks.user_confirmed and not looks.by_user


def test_a_goal_has_an_objective_up_to_4000_characters_and_up_to_5_criteria():
    assert _spec().tier == "standard"
    with pytest.raises(ValidationError):
        GoalSpec(objective="x" * 4001, checks=(_check(),))
    with pytest.raises(ValidationError):
        GoalSpec(objective="x", checks=())
    six = tuple(_check(id=f"c{n}") for n in range(6))
    with pytest.raises(ValidationError):
        GoalSpec(objective="x", checks=six)
    lines = tuple(_check(id=f"k{n}", kind="check", path=None, argv=("make", "test"), by_user=True) for n in range(5))
    assert len(GoalSpec(objective="x", checks=six[:5] + lines).checks) == 10
    with pytest.raises(ValidationError):
        GoalSpec(objective="x", checks=(_check(), _check()))


def test_a_goal_runs_on_a_job_tier_and_a_cap_no_higher_than_the_settings_maximum():
    assert set(typing.get_args(GoalSpec.model_fields["tier"].annotation)) == set(TIERS)
    assert _spec(usd_cap=MAX_USD_CAP).usd_cap == MAX_USD_CAP and _spec().usd_cap is None
    for cap in (0, MAX_USD_CAP + 1, float("inf")):
        with pytest.raises(ValidationError):
            _spec(usd_cap=cap)


def test_the_streak_stops_at_three_and_the_protected_set_at_50_mb():
    assert goal_mode.BLOCKED_AFTER == 3
    GoalProgress(stall=3)
    with pytest.raises(ValidationError):
        GoalProgress(stall=4)
    half = goal_mode.PROTECTED_BYTES_MAX // 2
    ProtectedSet(files=(ProtectedFile(path="a", size=half), ProtectedFile(path="b", size=half)))
    with pytest.raises(ValidationError):
        ProtectedSet(files=(ProtectedFile(path="a", size=half), ProtectedFile(path="b", size=half + 1)))
    assert _spec(protected=ProtectedSet(files=(ProtectedFile(path="pyproject.toml", sha256=SHA,
                                                             section="tool.pytest.ini_options"),))).protected
