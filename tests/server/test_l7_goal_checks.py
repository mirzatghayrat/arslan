"""L7-5: a goal's `check:` lines run by the host through `_run_tool`, in place, and the protected set (docs/plans/0164/
L7-goal-mode.md, "Check files are protected from Start: verify, then run in place", "Fit with LOOP1").

The gate parity tests run the same command once as the model's call and once as the host's `check:` run, through the
real command gate, and compare what each answered, which cards each showed and whether the executor ran.
"""
from __future__ import annotations

import json
import shlex
import types

import pytest

from arslan.execution_budget import Budget, scope
from arslan.models import LLMResponse
from server.orchestrator import command_gate, goal_checks, tool_gates, tool_loop
from server.orchestrator.turn_state import ToolTurn
from server.registry import executors
from server.services import command_sandbox, goal_mode, permissions, task_service, terminal_exec
from server.services.goal_mode import GoalCheck, GoalProgress, GoalSpec
from tests.server.scripted_turn import booted_db_fixture, turn_db_fixture  # noqa: F401 — the fixtures
from tests.server.test_l7_goal_start import active  # noqa: F401 — a fixture


def _line(command: str, **kw) -> GoalCheck:
    return GoalCheck(id="check-1", description=f"check: {command}", kind="check", argv=tuple(shlex.split(command)),
                     by_user=True, **kw)


def _changes(protected, root, **kw):
    return goal_mode.protected_changes(protected, root, **kw)[0]


# -- gate parity: a check: command is the model's command, gate for gate ---------------------------------------------

def _settings(monkeypatch):
    """As test_gate_order: the settings read one way, so both calls reach the same gates."""
    async def no():
        return False

    async def yes():
        return True

    async def nothing(*_args, **_own):
        return {}

    async def no_grant(*_args, **_own):
        return None
    monkeypatch.setattr(tool_gates, "_writing_in_own_folder", no)
    monkeypatch.setattr(command_gate, "_asks_for_everything", no)
    monkeypatch.setattr(command_gate, "_sandbox_enabled", yes)
    monkeypatch.setattr(command_gate, "_network_after_outside_content", nothing)
    monkeypatch.setattr(command_gate, "_outside_grant", no_grant)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(permissions, "current_asker", lambda: object())


@pytest.fixture
def _a_mac_with_a_sandbox(monkeypatch, turn_db):
    _settings(monkeypatch)
    monkeypatch.setattr(task_service, "current", lambda: None)


@pytest.fixture
def _a_goal_job(monkeypatch, execution_db):
    _settings(monkeypatch)


class _Calls:
    def __init__(self, monkeypatch, answer: bool):
        self.cards, self.ran, self.frames, self.answer = [], [], [], answer

        async def execute(args):
            self.ran.append(args["command"])
            return {"ok": True, "exit_code": 0, "stdout": "ran", "stderr": ""}
        monkeypatch.setitem(executors.EXECUTORS, "run_command", types.SimpleNamespace(key="run_command",
                                                                                      execute=execute))

    async def card(self, *args, **own):
        self.cards.append(json.dumps([args, own], default=str))
        return self.answer

    async def resolve(self):
        return [{"key": "run_command", "description": "d"}]


async def _as_the_model(command, calls):
    turn = ToolTurn(resolve_tools=calls.resolve, emit=calls.frames.append, tool_timeout_s=5, tool_trace=[],
                    convo=[], confirm_command=calls.card, mcp_fail_counts={}, conversation_id="c1")
    with scope(Budget()):
        return await tool_loop._run_tool("run_command", {"command": command}, "{}", turn)


async def _as_the_host(command, calls, tmp_path, monkeypatch):
    line = _line(command)
    goal = GoalSpec(objective="Make the check pass", checks=(line,),
                    protected=goal_mode.record_protected(tmp_path, (line,)))

    async def folder():
        return tmp_path
    monkeypatch.setattr(goal_checks, "_working_folder", folder)
    request = types.SimpleNamespace(goal=goal, emit=calls.frames.append, tool_timeout_s=5, confirm_command=calls.card,
                                    confirm_workspace_write=None, confirm_schedule=None, conversation_id="c1",
                                    log_events=False, caller=None)
    worker_trace, worker_convo = [], []
    state = types.SimpleNamespace(resolve_tools=calls.resolve, tool_trace=worker_trace, convo=worker_convo,
                                  mcp_fail_counts={}, mcp_hint_logged=set(), adapter=None, resolve_callable=None,
                                  acceptance_runtime=types.SimpleNamespace(progress=types.SimpleNamespace(goal=None)))
    with scope(Budget()):
        host = await goal_checks.run(request, state)
    assert worker_trace == [] and worker_convo == []          # the worker's records never hold the host's run
    assert host.changed == () and len(host.runs) == 1
    return host.runs[0]["result"]


@pytest.mark.parametrize("command,answer,how", [
    ("rm -rf /", True, "refused"),                     # _never_runs: before any card
    ("osascript -l JavaScript -e x", True, "refused"),
    ("git push origin main", False, "carded"),         # _card: the card shown, and declined
    ("git push origin main", True, "carded"),          # the card shown, and accepted: it runs
    ("ls", True, "ran"),                               # no card: it runs in the sandbox
])
async def test_a_check_command_is_refused_or_carded_exactly_as_the_models(
        command, answer, how, _a_mac_with_a_sandbox, monkeypatch, tmp_path):
    model, host = _Calls(monkeypatch, answer), None
    model_result = await _as_the_model(command, model)
    host = _Calls(monkeypatch, answer)
    host_result = await _as_the_host(command, host, tmp_path, monkeypatch)
    assert host_result == model_result
    assert host.cards == model.cards and host.ran == model.ran
    assert [f["type"] for f in host.frames] == [f["type"] for f in model.frames]
    assert bool(model.cards) is (how == "carded")
    assert bool(model.ran) is (how == "ran" or answer and how == "carded")


async def test_a_check_on_a_turn_that_cant_run_commands_is_refused_as_the_models(
        _a_mac_with_a_sandbox, monkeypatch, tmp_path):
    model, host = _Calls(monkeypatch, True), _Calls(monkeypatch, True)

    async def none():
        return []
    model.resolve = host.resolve = none                 # run_command isn't offered: `_admit` refuses it
    assert await _as_the_host("ls", host, tmp_path, monkeypatch) == await _as_the_model("ls", model)
    assert host.ran == model.ran == []


# -- the protected set ------------------------------------------------------------------------------------------------

def _layout(root):
    (root / "tests").mkdir()
    (root / "tests" / "run_checks.py").write_text("print('stage 1')\n")
    (root / "rules.dat").write_text("rule-1\n")
    (root / "app.py").write_text("def add(a, b):\n    return a - b\n")
    return root


def test_an_edited_argv_file_stops_the_goal_and_the_work_never_does(tmp_path):
    root = _layout(tmp_path)
    line = _line("python3 validate.py --rules=rules.dat clean/orders.csv")
    (root / "validate.py").write_text("ok\n")
    protected = goal_mode.record_protected(root, (line,))
    assert {"validate.py", "rules.dat"} <= {f.path for f in protected.files if f.sha256}
    assert [f.sha256 for f in protected.files if f.path == "clean/orders.csv"] == [None]    # the work: a warning only
    (root / "clean").mkdir()
    (root / "clean" / "orders.csv").write_text("id\n1\n")
    (root / "app.py").write_text("fixed\n")
    assert _changes(protected, root) == ()
    (root / "rules.dat").write_text("rule-1 relaxed\n")
    assert _changes(protected, root) == ("rules.dat",)
    (root / "rules.dat").unlink()
    assert _changes(protected, root) == ("rules.dat",)


def test_only_the_users_output_unprotects_an_argv_file_never_a_drafted_one(tmp_path):
    root = _layout(tmp_path)
    (root / "out.csv").write_text("old\n")
    line = _line("python3 check.py out.csv")
    drafted = GoalCheck(id="c1", description="Save out.csv", kind="file_saved", path="out.csv")
    assert "out.csv" in {f.path for f in goal_mode.record_protected(root, (drafted, line)).files}
    users = drafted.model_copy(update={"by_user": True})
    assert "out.csv" not in {f.path for f in goal_mode.record_protected(root, (users, line)).files}


def test_conventional_tests_snapshots_and_configs_are_protected_for_a_runner_check(tmp_path):
    root = _layout(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "__snapshots__").mkdir()
    (root / "src" / "__snapshots__" / "view.snap").write_text("snap\n")
    (root / "src" / "view.test.ts").write_text("test\n")
    (root / "fixtures").mkdir()
    (root / "fixtures" / "in.json").write_text("{}\n")
    (root / "pytest.ini").write_text("[pytest]\n")
    protected = goal_mode.record_protected(root, (_line("pytest -q"),))
    for rel, edit in [("src/__snapshots__/view.snap", "changed"), ("src/view.test.ts", "changed"),
                      ("fixtures/in.json", "[]"), ("pytest.ini", "[pytest]\naddopts = -k nothing\n")]:
        before = (root / rel).read_text()
        (root / rel).write_text(edit)
        assert _changes(protected, root) == (rel,), rel
        (root / rel).write_text(before)
    (root / "src" / "__snapshots__" / "view.snap").unlink()
    assert _changes(protected, root) == ("src/__snapshots__/view.snap",)


def test_only_the_test_sections_of_pyproject_and_package_json_count(tmp_path):
    root = _layout(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n[tool.pytest.ini_options]\naddopts = "-q"\n')
    (root / "package.json").write_text(json.dumps({"name": "x", "scripts": {"test": "jest"}}))
    protected = goal_mode.record_protected(root, (_line("pytest -q"),))
    (root / "pyproject.toml").write_text('[project]\nname = "y"\n[tool.pytest.ini_options]\naddopts = "-q"\n')
    (root / "package.json").write_text(json.dumps({"name": "y", "scripts": {"test": "jest"}}))
    assert _changes(protected, root) == ()
    (root / "pyproject.toml").write_text('[project]\nname = "y"\n[tool.pytest.ini_options]\naddopts = "-k no"\n')
    (root / "package.json").write_text(json.dumps({"name": "y", "scripts": {"test": "exit 0"}}))
    assert _changes(protected, root) == ("package.json", "pyproject.toml")


def test_where_the_runner_config_points_is_protected(tmp_path):
    root = _layout(tmp_path)
    (root / "checks").mkdir()
    (root / "checks" / "probe_math.py").write_text("def test_x(): pass\n")
    (root / "e2e").mkdir()
    (root / "e2e" / "flow.e2e.js").write_text("it()\n")
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = checks\npython_files = probe_*.py\n")
    (root / "package.json").write_text(json.dumps({"jest": {"testMatch": ["**/*.e2e.js"]}}))
    protected = goal_mode.record_protected(root, (_line("pytest"),))
    assert {"checks/probe_math.py", "e2e/flow.e2e.js"} <= {f.path for f in protected.files}
    (root / "checks" / "probe_math.py").write_text("def test_x(): assert True\n")
    assert _changes(protected, root) == ("checks/probe_math.py",)
    (root / "checks" / "probe_math.py").write_text("def test_x(): pass\n")
    (root / "checks" / "probe_new.py").write_text("")                      # a new file where testpaths point
    assert _changes(protected, root) == ("checks/probe_new.py",)


@pytest.mark.parametrize("argv", ["npm run test:unit", "npm test", "make check", "make"])
def test_the_callees_of_whatever_the_argv_invokes_are_protected_in_turn(argv, tmp_path):
    """The build-slice item: `npm run test:unit` and `make check`, not only the `test` script and recipe, and what
    those call in turn (a script that calls a script, a make prerequisite)."""
    root = _layout(tmp_path)
    (root / "scripts").mkdir()
    for name, body in [("unit.sh", "set -e\nbash scripts/helper.sh && echo done\n"), ("helper.sh", "exit 1\n"),
                       ("pre.sh", "true\n"), ("lint.sh", "true\n"), ("plain.sh", "true\n")]:
        (root / "scripts" / name).write_text(body)
    (root / "package.json").write_text(json.dumps({"scripts": {
        "test:unit": "CI=1 bash scripts/unit.sh", "pretest:unit": "sh scripts/pre.sh",
        "test": "npm run test:unit -- --ci"}}))
    (root / "Makefile").write_text("all: check\n\ncheck: lint\n\t@bash scripts/unit.sh\n\nlint:\n"
                                   "\t$(MAKE) style\n\nstyle:\n\t-sh scripts/lint.sh\n")
    protected = goal_mode.record_protected(root, (_line(argv),))
    files = {f.path for f in protected.files if f.sha256}
    assert {"scripts/unit.sh", "scripts/helper.sh"} <= files and "scripts/plain.sh" not in files
    if argv.startswith("npm"):
        assert "scripts/pre.sh" in files
    else:
        assert "scripts/lint.sh" in files            # check's prerequisite, then a recursive make
    (root / "scripts" / "helper.sh").write_text("exit 0\n")
    assert _changes(protected, root) == ("scripts/helper.sh",)


def test_a_new_test_or_config_file_stops_the_goal_and_bytecode_caches_dont(tmp_path):
    root = _layout(tmp_path)
    protected = goal_mode.record_protected(root, (_line("python3 tests/run_checks.py"),))
    (root / "tests" / "__pycache__").mkdir()
    (root / "tests" / "__pycache__" / "run_checks.cpython-311.pyc").write_bytes(b"\x00")
    (root / "app.pyc").write_bytes(b"\x00")
    (root / "tests" / "run_checks.cpython-311.pyc").write_bytes(b"\x00")     # a cache written another way
    assert _changes(protected, root) == ()
    for rel in ("conftest.py", "tests/test_extra.py", "lib/jest.config.js"):
        (root / rel).parent.mkdir(exist_ok=True)
        (root / rel).write_text("")
        assert _changes(protected, root) == (rel,), rel
        (root / rel).unlink()
    (root / "tests" / "linked").symlink_to(root / "app.py")
    assert _changes(protected, root) == ("tests/linked",)


def test_a_new_conftest_in_a_parent_folder_stops_the_goal(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    _layout(root)
    protected = goal_mode.record_protected(root, (_line("pytest"),))
    (tmp_path / "conftest.py").write_text("import pytest\n")
    assert _changes(protected, root) == ("../conftest.py",)


def test_declared_outputs_are_accepted_only_from_a_host_run_and_never_as_config(tmp_path):
    root = _layout(tmp_path)
    (root / "tests" / "revealed").mkdir()
    line = _line("python3 tests/run_checks.py", outputs=("tests/revealed/test_step_*.py",))
    protected = goal_mode.record_protected(root, (line,))
    (root / "tests" / "revealed" / "test_step_2.py").write_text("")
    assert _changes(protected, root) == ("tests/revealed/test_step_2.py",)       # between runs: the worker's
    changed, accepted = goal_mode.protected_changes(protected, root, outputs=line.outputs)
    assert changed == () and [a.path for a in accepted] == ["tests/revealed/test_step_2.py"]
    assert _changes(protected, root, accepted=accepted) == ()
    (root / "tests" / "revealed" / "test_step_2.py").write_text("def test(): pass\n")
    assert _changes(protected, root, accepted=accepted) == ("tests/revealed/test_step_2.py",)
    out = _line("python3 tests/run_checks.py", outputs=("tests/revealed/*.py",))
    (root / "tests" / "revealed" / "conftest.py").write_text("")
    assert goal_mode.protected_changes(protected, root, outputs=out.outputs)[0][0] == "tests/revealed/conftest.py"


def test_a_protected_set_over_its_limits_refuses(tmp_path, monkeypatch):
    root = _layout(tmp_path)
    (root / "tests" / "test_two.py").write_text("")
    monkeypatch.setattr(goal_mode, "PROTECTED_FILES_MAX", 1)
    with pytest.raises(ValueError):
        goal_mode.record_protected(root, (_line("pytest"),))


# -- the verdict through a whole turn: run in place, verify before and after -------------------------------------------

async def _check_turn(_gates, monkeypatch, tmp_path, replies, run, *, outputs=(), more=()):
    """A goal job's turn with one `check:` line whose host run `run(n)` answers (and may write files first)."""
    from arslan.companion.contracts import TaskSpec
    from server.services import task_validation
    from server.services.task_repository import repository
    line = _line("python3 tests/run_checks.py", outputs=outputs)
    goal = GoalSpec(objective="Make the staged check pass", checks=(*more, line),
                    protected=goal_mode.record_protected(tmp_path, (line,)))
    calls = {"turn": [], "host": []}

    async def disk(started_at):
        return {"roots": [tmp_path.resolve()], "workspace": tmp_path.resolve(), "since": None}

    async def folder():
        return tmp_path

    async def card(*_args, **_own):
        return True

    async def execute(args):
        calls["host"].append(args["command"])
        return run(len(calls["host"]))

    class Adapter:
        async def chat(self, system, user, **kw):
            if "one step for the user" in system:
                return LLMResponse(usage={}, content="{}")
            calls["turn"].append(json.dumps([user, kw.get("history")], default=str))
            return LLMResponse(usage={}, content=replies(len(calls["turn"])))

    async def tools():
        return [{"key": "run_command", "description": "d"}]
    monkeypatch.setattr(task_validation, "_disk_context", disk)
    monkeypatch.setattr(goal_checks, "_working_folder", folder)
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)
    monkeypatch.setitem(executors.EXECUTORS, "run_command", types.SimpleNamespace(key="run_command", execute=execute))

    async def body(emit):
        return await tool_loop.run_native(system="Goal fixture", user_content=goal.objective, history=[],
                                          resolve_tools=tools, emit=emit, on_chunk=lambda text: None,
                                          allow_escalation=False, goal=goal, confirm_command=card)
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
    return result, task, record, calls


def _exit(code, out="", err=""):
    return {"ok": code == 0, "exit_code": code, "stdout": out, "stderr": err}     # as terminal_exec answers


async def test_the_hosts_run_in_place_meets_the_check_and_its_output_reaches_the_next_round(
        _a_goal_job, monkeypatch, tmp_path):
    _layout(tmp_path)
    result, task, record, calls = await _check_turn(
        _a_goal_job, monkeypatch, tmp_path, lambda n: "Working on it.",
        lambda n: _exit(0, "all stages pass") if n == 2 else _exit(1, "FAILED stage 1: rounding mode"))
    assert calls["host"] == ["python3 tests/run_checks.py"] * 2
    assert "FAILED stage 1: rounding mode" in calls["turn"][1]          # what the check printed, framed, next round
    assert task.phase == "succeeded" and (record.status, record.round) == ("complete", 2)


@pytest.mark.parametrize("when", ["between rounds", "during the run"])
async def test_a_protected_file_changed_stops_the_goal_at_review_never_complete(
        when, _a_goal_job, monkeypatch, tmp_path):
    """Laundering: work code that rewrites the check's own runner while the check runs, or the worker before it."""
    _layout(tmp_path)
    runner = tmp_path / "tests" / "run_checks.py"

    def replies(n):
        if when == "between rounds" and n == 2:
            runner.write_text("print('ok')\n")
        return "Done."

    def run(n):
        if when == "during the run":
            runner.write_text("print('ok')\n")
        return _exit(0, "ok")
    result, task, record, calls = await _check_turn(_a_goal_job, monkeypatch, tmp_path, replies,
                                                    run if when == "during the run" else lambda n: _exit(1, "F"))
    assert task.phase == "waiting_user" and task.pause_reason == "acceptance_review_required"
    assert record.status == "review" and "tests/run_checks.py" in result["final"]
    assert calls["host"] == ["python3 tests/run_checks.py"]          # never run again once the set had changed


async def test_a_declared_output_the_check_writes_is_accepted_and_protected_after(
        _a_goal_job, monkeypatch, tmp_path):
    _layout(tmp_path)
    (tmp_path / "tests" / "revealed").mkdir()
    stage = tmp_path / "tests" / "revealed" / "test_step_2.py"

    def run(n):
        if n == 1:
            stage.write_text("def test_step_2(): ...\n")              # the runner reveals the next stage
            return _exit(1, "new tests were added")
        return _exit(0, "all stages pass")
    result, task, record, calls = await _check_turn(_a_goal_job, monkeypatch, tmp_path, lambda n: "Next stage.",
                                                    run, outputs=("tests/revealed/test_step_*.py",))
    assert task.phase == "succeeded" and [a.path for a in record.accepted] == ["tests/revealed/test_step_2.py"]


async def test_a_passing_check_run_again_meets_the_journals_fence_as_the_workers_would(
        _a_goal_job, monkeypatch, tmp_path):
    """No bypass: the task journal runs an identical external write once, so the host's second run of a check that
    passed is answered as the worker's identical second call is, and the goal is never complete on the old run."""
    _layout(tmp_path)
    notes = GoalCheck(id="c1", description="The notes name INV-07", kind="file_contains", path="notes.md",
                      phrases=("INV-07",))

    def replies(n):
        if n == 2:
            (tmp_path / "notes.md").write_text("INV-07")
        return "Working on it."
    result, task, record, calls = await _check_turn(_a_goal_job, monkeypatch, tmp_path, replies,
                                                    lambda n: _exit(0, "pass"), more=(notes,))
    assert calls["host"] == ["python3 tests/run_checks.py"]
    assert "This exact action already succeeded in this task" in calls["turn"][2]
    assert task.phase != "succeeded" and record.status != "complete" and "check-1" in record.unmet


async def test_a_declared_output_the_worker_writes_between_runs_stops_the_goal(_a_goal_job, monkeypatch, tmp_path):
    _layout(tmp_path)
    (tmp_path / "tests" / "revealed").mkdir()

    def replies(n):
        if n == 2:
            (tmp_path / "tests" / "revealed" / "test_step_9.py").write_text("")    # the worker's, not the check's
        return "Next stage."
    result, task, record, calls = await _check_turn(_a_goal_job, monkeypatch, tmp_path, replies,
                                                    lambda n: _exit(1, "F"), outputs=("tests/revealed/test_step_*.py",))
    assert record.status == "review" and "tests/revealed/test_step_9.py" in result["final"]
    assert record.accepted == () and calls["host"] == ["python3 tests/run_checks.py"]


# -- bytecode caches: a goal job's commands keep them apart -----------------------------------------------------------

@pytest.mark.parametrize("apart", [True, False])
async def test_a_goal_jobs_python_writes_no_pycache_beside_the_protected_tests(apart, tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "helper.py").write_text("VALUE = 1\n")
    token = terminal_exec.PYCACHE_APART.set(apart)
    try:
        result = await terminal_exec.run(
            "python3 -c 'import sys; sys.path.insert(0, \"tests\"); import helper; print(sys.pycache_prefix)'",
            cwd=tmp_path, timeout_s=30)
    finally:
        terminal_exec.PYCACHE_APART.reset(token)
    assert result["exit_code"] == 0, result
    assert (tmp_path / "tests" / "__pycache__").exists() is not apart
    if apart:
        assert "goal-pycache" in result["stdout"]
        assert list((tmp_path / "data" / "goal-pycache").iterdir()) == []        # removed after the command


async def test_a_goal_jobs_commands_run_apart_and_a_plain_jobs_dont(execution_db, monkeypatch):
    from server.services import background_jobs
    seen = {}

    async def execute(job):
        seen[job.job_id] = terminal_exec.PYCACHE_APART.get()
        return "", "failed", "task_execution_failed"
    monkeypatch.setattr(background_jobs, "_execute", execute)
    background_jobs._reset_for_tests()
    try:
        goal = GoalSpec(objective="Make the check pass", checks=(_line("pytest -q"),))
        jobs = [background_jobs.start_goal("goal-chat", "job-goal", goal),
                background_jobs.start_placed("goal-chat", "A plain job", [], (None, None), outside_seen=False)]
        for job in jobs:
            await job.task
    finally:
        background_jobs._reset_for_tests()
    assert seen == {"job-goal": True, jobs[1].job_id: False} and terminal_exec.PYCACHE_APART.get() is False


# -- Start records the set once; Resume reads it from the row -----------------------------------------------------

async def test_start_records_the_protected_set_on_the_row_and_refuses_one_over_its_limits(
        execution_db, active, monkeypatch, tmp_path):  # noqa: F811 — the fixture
    from server.services import settings_service
    from tests.server import test_l7_goal_start as start
    _layout(tmp_path)

    async def workspace(db):
        return tmp_path
    monkeypatch.setattr(settings_service, "workspace_dir", workspace)
    adapter, queued = start.Model(), []

    async def run(job):
        queued.append(job)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setattr(start.background_jobs, "_run", run)
    start.background_jobs._reset_for_tests()
    try:
        await start._say(f"/goal {start.PROMPT}\n{start.CHECK}")
        monkeypatch.setattr(goal_mode, "PROTECTED_FILES_MAX", 0)
        assert "couldn’t be recorded" in await start._say("/goal start confirm") and queued == []
        monkeypatch.setattr(goal_mode, "PROTECTED_FILES_MAX", 2000)
        assert (await start._say("/goal start confirm")).startswith("Goal started") and len(queued) == 1
        protected = queued[0].goal_spec.protected
        assert protected is not None and [f.path for f in protected.files if f.sha256] == ["tests/run_checks.py"]
        row = await start._row(execution_db)
        assert GoalSpec.model_validate(row.privacy["goal_spec"]).protected == protected
    finally:
        start.background_jobs._reset_for_tests()
