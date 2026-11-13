"""ASK1-b (v0.1.64; the user, 2026-11-07): a scheduled task's own fire runs commands again, inside the sandbox.

- The switch is the fire's own signal (`command_gate.scheduled_fire`, set by `scheduler._fire`), not "nobody to ask":
  the heartbeat, a sub-session's turn with nobody to ask and a resumed task keep the refusal.
- A fire runs what "ask only for risky commands" runs with no card, in the sandbox, in Arslan's own folder. One that
  would ask is refused and listed (never waited on); a stored ask_all refuses and lists every command and says where
  to switch; with no sandbox every command is refused. A conversation's grant to leave the sandbox never lets it out.
- `scheduled_tasks.outside_seen` (migration 0097) is what a fire starts from: true runs offline. The schedule tool
  records it from the turn; the API never clears it; rows from before 0097 are true, and an existing install gets
  the one-time note.
- `_FIRE_WRITES = False` (the review's cut-back) starts a fire's command in its run's temp folder.

Stand-in commands and tmp databases only; `terminal_exec.run` is replaced, nothing runs (the real seatbelt run is
tests/server/sbx/test_ask1b_fire_seatbelt.py).
"""
from __future__ import annotations

from datetime import datetime

import pytest
import sqlalchemy as sa

from server.db import session as db_session
from server.db.migrations import runner
from server.db.migrations.versions import _0097_scheduled_outside_seen as m0097
from server.db.models import Base, ScheduledTask, ScheduledTaskRun, Setting
from server.orchestrator import arslan as arslan_mod
from server.orchestrator import command_gate, tool_loop, untrusted
from server.orchestrator.turn_state import ToolTurn
from server.services import command_sandbox, permission_store, permissions, settings_service, storage_boot, terminal_exec
from tests.server.test_s2a3_wire import STAND_IN, unread  # noqa: F401  (the fixture)
from tests.server.test_scheduled_run_no_command import _CallsACommand

CID = "ask1b-fire"
NOTE = "scheduled_commands_note"


@pytest.fixture(autouse=True)
def _fresh(execution_db, monkeypatch, tmp_path):
    permission_store._reset_for_tests()
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(tmp_path / "Arslan"))
    monkeypatch.setattr(command_sandbox, "available", lambda: True)       # as on a Mac; nothing really runs here


@pytest.fixture
def ran(monkeypatch):
    """terminal_exec.run replaced: records (command, sandbox, offline, cwd) for every command that would start."""
    calls: list[tuple] = []

    async def run(command, **kw):
        calls.append((command, kw.get("sandbox"), kw.get("offline"), str(kw.get("cwd"))))
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cwd": str(kw.get("cwd")), "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "run", run)
    return calls


async def _set(**values: str) -> None:
    async with db_session.AsyncSessionLocal() as db:
        for key, value in values.items():
            db.add(Setting(key=key, value=value))
        await db.commit()


async def _dispatch(command: str, *, conversation_id: str = CID, **kw):
    async def tools():
        return [{"key": "run_command", "description": "run_command"}]
    return await tool_loop._run_tool("run_command", {"command": command, **kw}, "", ToolTurn(
        resolve_tools=tools, emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
        conversation_id=conversation_id))


async def _fire(command: str, *, seen: bool = False, fire: str | None = CID, **kw):
    """One command in a turn with nobody to ask, which read outside content when `seen`, inside a fire's signal for
    conversation `fire` (None: no fire)."""
    signal = command_gate.scheduled_fire(fire) if fire else _nothing()
    with untrusted.carried(seen), signal:
        token = untrusted.track_turn()
        try:
            return await _dispatch(command, **kw)
        finally:
            untrusted.end_turn(token)


class _nothing:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


async def _rows():
    async with db_session.AsyncSessionLocal() as db:
        return list(reversed(await permission_store.recent(db)))


def _own(tmp_path) -> str:
    return str((tmp_path / "Arslan").resolve())


# ── what a fire may run ──────────────────────────────────────────────────────

@pytest.mark.parametrize("policy", [None, "ask_risky", "ask_all"])
@pytest.mark.parametrize("seen", [False, True])
async def test_a_fire_runs_a_harmless_command_in_the_sandbox_under_ask_risky_and_none_under_ask_all(
        ran, tmp_path, policy, seen):
    if policy is not None:
        await _set(shell_confirm_policy=policy)
    out = await _fire("ls", seen=seen)
    if policy == "ask_all":
        assert ran == [] and out["ok"] is False and "nobody to ask" in out["error"]
        assert out["note"] == command_gate.FIRE_ASK_ALL_NOTE and "Ask only for risky commands" in out["note"]
        [row] = await _rows()                                          # listed, once, as the card would have read
        assert (row.kind, row.target, row.decided_by, row.decision) == ("command", "text:ls", "policy", "deny")
        assert permission_store.could_not_ask(row)
    else:
        assert ran == [("ls", True, seen, _own(tmp_path))]             # sandboxed, in Arslan's own folder
        assert out.get("ok") is not False and await _rows() == []


@pytest.mark.parametrize("users_folder", [None, "home"])
async def test_a_command_the_reader_cant_read_runs_offline_in_the_sandbox_with_no_card(
        ran, unread, tmp_path, users_folder):  # noqa: F811 (the fixture)
    """The gate reads the folder the fire's command starts in, Arslan's own, not the user's (here their home)."""
    from pathlib import Path
    if users_folder:
        await _set(workspace_dir=str(Path.home()))
    out = await _fire(f"{STAND_IN} one")
    assert ran == [(f"{STAND_IN} one", True, True, _own(tmp_path))] and await _rows() == []
    assert out.get("ok") is not False


@pytest.mark.parametrize("seen", [False, True])
async def test_a_command_that_would_ask_is_refused_and_listed_not_waited_on(ran, seen):
    out = await _fire("git push origin main", seen=seen)
    assert ran == [] and out["ok"] is False and out["note"] == command_gate.FIRE_REFUSED_NOTE
    [row] = await _rows()
    assert (row.kind, row.target, row.decided_by, row.decision) == ("command", "rules:git-push", "policy", "deny")


async def test_asking_to_leave_the_sandbox_is_refused_and_listed(ran):
    out = await _fire("ls", outside_sandbox=True, why="stand-in reason")
    [row] = await _rows()
    assert ran == [] and out["ok"] is False and row.kind == "outside" and row.decision == "deny"


async def test_a_conversation_grant_to_leave_the_sandbox_never_lets_a_fire_out(ran, tmp_path):
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_grant(db, CID, "", "outside", "*")
        await permission_store.add_grant(db, CID, "", "command", "text:git push origin main")
        await db.commit()
    assert (await _fire("ls")).get("ok") is not False
    assert (await _fire("git push origin main"))["ok"] is False      # nothing stands where nobody can be asked
    assert ran == [("ls", True, False, _own(tmp_path))]


@pytest.mark.parametrize("how", ["switched off", "seatbelt can't start"])
async def test_with_no_sandbox_every_command_is_refused_and_listed(ran, monkeypatch, how):
    if how == "switched off":
        await _set(terminal_sandbox_enabled="false")
    else:
        monkeypatch.setattr(command_sandbox, "available", lambda: False)
    out = await _fire("ls")
    [row] = await _rows()
    assert ran == [] and out["ok"] is False and (row.kind, row.decision) == ("command", "deny")


async def test_the_cut_back_starts_a_fires_command_in_its_runs_temp_folder(ran, monkeypatch, tmp_path):
    from server.services import execution_context, run_temp
    temp = tmp_path / "run-temp"
    monkeypatch.setattr(run_temp, "folder", lambda key: temp if key == 4242 else None)
    monkeypatch.setattr(command_gate, "_FIRE_WRITES", False)
    with execution_context.bind_run(4242):
        await _fire("ls")
    assert ran == [("ls", True, False, str(temp))]
    out = await _fire("ls")                                            # no run: nowhere to start, nothing runs
    assert out["ok"] is False and len(ran) == 1


# ── the switch: only a scheduled task's own fire ─────────────────────────────

async def test_a_run_with_nobody_to_ask_and_no_fire_signal_is_refused(ran):
    out = await _fire("ls", fire=None)
    assert ran == [] and out["ok"] is False and out["note"] == command_gate.SCHEDULED_COMMAND_NOTE


async def test_a_sub_session_with_nobody_to_ask_is_refused_even_inside_a_fire(ran, monkeypatch):
    out = await _fire("ls", conversation_id="ask1b-child")             # another conversation: the signal isn't its
    assert ran == [] and out["ok"] is False
    monkeypatch.setattr(settings_service, "run_sub_folder", lambda: ("stand-in",))
    out = await _fire("ls")                                            # the fire's own conversation, as a sub-session
    assert ran == [] and out["ok"] is False


async def test_someone_to_ask_is_never_a_fire(ran):
    async def ask(frame):
        raise AssertionError("no card in this test")
    with command_gate.scheduled_fire(CID), permissions.asking_with(ask):
        assert command_gate.fire_runs_commands(CID) is False


async def test_a_resumed_task_starts_with_no_fire_signal(monkeypatch):
    from server.services import task_service
    seen = []

    async def prepare(*_a, **_k):
        return {}, None, None, None

    async def launch(*_a, **_k):
        seen.append(command_gate._FIRE.get())
    monkeypatch.setattr(task_service, "prepare_resume", prepare)
    monkeypatch.setattr(task_service, "_launch", launch)
    await task_service.resume_entry("t", 1, CID, "x", lambda e: None, None, ctx=None)
    assert seen == [None]


async def _task(name: str, *, seen: bool = False) -> ScheduledTask:
    async with db_session.AsyncSessionLocal() as db:
        task = ScheduledTask(name=name, prompt="list the folder", conversation_id=CID, target="arslan",
                             schedule_kind="interval", interval_s=3600, enabled=True, consecutive_failures=0,
                             next_due_at=datetime.utcnow(), outside_seen=seen)
        db.add(task)
        await db.commit()
        return task


@pytest.mark.parametrize("heartbeat", [False, True], ids=["a task's own fire", "the heartbeat"])
async def test_the_schedulers_fire_runs_the_command_and_the_heartbeat_does_not(ran, monkeypatch, tmp_path, heartbeat):
    """The scheduler's own path end to end (scheduler._fire), with a model that asks for `ls` once."""
    from server.services import heartbeat as heartbeat_mod, scheduler
    model = _CallsACommand()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    task = await _task(heartbeat_mod.TASK_NAME if heartbeat else "list it")
    await scheduler._fire(task)
    assert len(model.inputs) == 2
    assert ("run_command" in model.offered[0]) is not heartbeat
    note = arslan_mod.UNATTENDED_NOTE if heartbeat else arslan_mod.SCHEDULED_NOTE
    assert untrusted_text(note) in model.inputs[0]                     # told before it tries
    if heartbeat:
        assert ran == [] and "nobody to ask" in model.inputs[1]
        [row] = await _rows()
        assert (row.kind, row.target, row.decision) == ("command", "text:ls", "deny")
    else:
        assert ran == [("ls", True, False, _own(tmp_path))] and await _rows() == []
    async with db_session.AsyncSessionLocal() as db:
        run = (await db.execute(sa.select(ScheduledTaskRun))).scalar_one()
    assert run.run_id is not None                                      # the run it made is recorded (INB6)


def untrusted_text(note: str) -> str:
    import json
    return json.dumps(note)[1:-1]


@pytest.mark.parametrize("seen", [False, True])
async def test_a_fire_starts_from_its_tasks_outside_seen(ran, monkeypatch, seen):
    from server.services import scheduler
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _CallsACommand())
    await scheduler._fire(await _task("list it", seen=seen))
    [(command, sandbox, offline, _cwd)] = ran
    assert (command, sandbox, offline) == ("ls", True, seen)


# ── outside_seen: recorded, sticky ───────────────────────────────────────────

@pytest.mark.parametrize("seen", [False, True])
async def test_the_schedule_tool_records_whether_its_turn_had_read_outside_content(seen):
    from server.registry.schedule_tools import ScheduleTaskExecutor
    token = untrusted.track_turn()
    try:
        if seen:
            untrusted.mark_external()
        out = await ScheduleTaskExecutor().execute({"name": "n", "prompt": "p", "when": "every: 3600"})
    finally:
        untrusted.end_turn(token)
    async with db_session.AsyncSessionLocal() as db:
        assert (await db.get(ScheduledTask, out["task_id"])).outside_seen is seen


async def test_an_edit_never_clears_it():
    from server.api.scheduled_tasks import update_scheduled_task
    from server.schemas import ScheduledTaskUpdateIn
    assert "outside_seen" not in ScheduledTaskUpdateIn.model_fields
    task = await _task("list it", seen=True)
    await update_scheduled_task(task.id, ScheduledTaskUpdateIn(prompt="a new prompt", name="renamed"))
    async with db_session.AsyncSessionLocal() as db:
        assert (await db.get(ScheduledTask, task.id)).outside_seen is True


# ── migration 0097 ───────────────────────────────────────────────────────────

async def _boot(db_path) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await storage_boot.initialize(engine)
    finally:
        await engine.dispose()


def _sql(db_path, statement: str, **params):
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            result = conn.execute(sa.text(statement), params)
            return result.all() if result.returns_rows else None
    finally:
        engine.dispose()


def _before_0097(db_path) -> None:
    """An install from before ASK1-b: no outside_seen column, two tasks, every migration but 0097 recorded."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            Base.metadata.create_all(conn)
            conn.execute(sa.text("ALTER TABLE scheduled_tasks DROP COLUMN outside_seen"))
            for name in ("a", "b"):
                conn.execute(sa.text("INSERT INTO scheduled_tasks (name, prompt, target, schedule_kind, interval_s, "
                                     "enabled, consecutive_failures) VALUES (:n, 'p', 'arslan', 'interval', 3600, 1, 0)"),
                             {"n": name})
            runner._ensure_table(conn)
            for vid, _ in runner.MIGRATIONS:
                if vid != "0097":
                    conn.execute(sa.text("INSERT INTO schema_version(version, applied_at) VALUES (:v, 'then')"),
                                 {"v": vid})
    finally:
        engine.dispose()


def _note(db_path):
    rows = _sql(db_path, "SELECT value FROM settings WHERE key = :k", k=NOTE)
    return rows[0][0] if rows else None


async def test_on_an_upgrade_existing_tasks_become_outside_seen_and_the_note_is_pending_once(tmp_path):
    db = tmp_path / "old.db"
    _before_0097(db)
    await _boot(db)
    assert _sql(db, "SELECT name, outside_seen FROM scheduled_tasks ORDER BY name") == [("a", 1), ("b", 1)]
    assert _note(db) == "pending"
    _sql(db, "UPDATE settings SET value = 'seen' WHERE key = :k", k=NOTE)          # the window saw it
    _sql(db, "INSERT INTO scheduled_tasks (name, prompt, target, schedule_kind, interval_s, enabled, "
             "consecutive_failures) VALUES ('c', 'p', 'arslan', 'interval', 3600, 1, 0)")
    await _boot(db)                                    # a restart: 0097 is recorded and never runs again
    assert _note(db) == "seen"
    assert _sql(db, "SELECT name, outside_seen FROM scheduled_tasks ORDER BY name") == [("a", 1), ("b", 1), ("c", 0)]


async def test_a_new_install_has_the_column_and_no_note(tmp_path):
    db = tmp_path / "new.db"
    await _boot(db)
    await _boot(db)
    assert _note(db) is None
    _sql(db, "INSERT INTO scheduled_tasks (name, prompt, target, schedule_kind, interval_s, enabled, "
             "consecutive_failures) VALUES ('c', 'p', 'arslan', 'interval', 3600, 1, 0)")
    assert _sql(db, "SELECT outside_seen FROM scheduled_tasks") == [(0,)]


@pytest.mark.parametrize("before", [None, "seen"])
def test_the_migration_run_twice_changes_nothing_the_second_time(tmp_path, before):
    db = tmp_path / "twice.db"
    _before_0097(db)
    if before:
        _sql(db, "INSERT INTO settings (key, value) VALUES (:k, :v)", k=NOTE, v=before)
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        for _ in range(2):
            with engine.begin() as conn:
                m0097.upgrade_sync(conn)
                conn.execute(sa.text("UPDATE scheduled_tasks SET outside_seen = 0 WHERE name = 'b'"))
    finally:
        engine.dispose()
    assert _sql(db, "SELECT name, outside_seen FROM scheduled_tasks ORDER BY name") == [("a", 1), ("b", 0)]
    assert _note(db) == (before or "pending")
