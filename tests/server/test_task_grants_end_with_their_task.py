"""0.1.61 §A5, PR 2c: a "for this task" grant never outlives its task.

PR 2 forgets a task's grants when its turn or job ends, but only for the tasks this process
registered (`permissions._GRANTED_TASKS`): a grant left by the last run (the process stopped, or
the end-of-task delete failed) stayed until the 24-hour prune. Two holes, closed here:
  A. boot: no task survives a restart, so every task grant goes at startup; conversation grants
     stay, and a failed delete is logged and never blocks boot;
  B. resume: a chat task resumed under its own id (`task_service.prepare_resume`) starts with
     none of the grants it was given before, whatever the registry says.
"""
from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from arslan import execution_checkpoint
from arslan.execution_budget import current as current_budget
from server.db.models import PermissionGrant
from server.orchestrator import arslan
from server.services import permission_store, permissions, personal_context as pc, task_service
from server.services.permissions import Context, Request
from server.services.task_repository import repository


@pytest.fixture(autouse=True)
def _fresh(execution_db):
    permission_store._reset_for_tests()
    permissions._reset_for_tests()
    yield
    permissions._reset_for_tests()


class Asker:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.frames: list[dict] = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return self.answers.pop(0)


def yes(scope):
    return {"approved": True, "scope": scope, "note": "", "by": "mac"}


def notes() -> Request:
    return Request(kind="app", target="com.apple.Notes", title="Use Notes?", always_label="Notes")


async def _grants(maker) -> list[tuple[str, str, str]]:
    async with maker() as db:
        rows = (await db.scalars(select(PermissionGrant).order_by(PermissionGrant.id))).all()
    return [(g.conversation_id, g.task_id, g.target) for g in rows]


async def _store_grants(maker, *rows: tuple[str, str, str]) -> None:
    async with maker() as db:
        for conversation_id, task_id, target in rows:
            db.add(PermissionGrant(conversation_id=conversation_id, task_id=task_id, kind="app",
                                   target=target, created_at=datetime.utcnow()))
        await db.commit()


# ── A. boot ────────────────────────────────────────────────────────────────────

class _BootWentOn(Exception):
    """Raised by the boot step after the one under test: boot got past it."""


def _boot_until_the_seeders(monkeypatch, tmp_path, maker):
    """server.main.lifespan, itself, on the test database, stopped at the registry seeders (the
    first step after the database's own repairs), so no background work starts."""
    from server import auth, config, main, token_bootstrap
    from server.registry import seeder
    from server.services import crypto_boot, native_locale

    async def no_locale_work(_session):
        pass

    async def stop_here():
        raise _BootWentOn

    monkeypatch.setattr(main, "engine", maker.kw["bind"])
    monkeypatch.setattr(config, "settings", SimpleNamespace(db_path=tmp_path / "unused.db",
                                                            spawns_dir=tmp_path / "spawns"))
    monkeypatch.setattr(token_bootstrap, "bootstrap_api_token", lambda _: None)
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-only")
    monkeypatch.setattr(main, "_validate_settings", lambda *a, **k: None)
    monkeypatch.setattr(main, "_log_data_location", lambda _: None)
    monkeypatch.setattr(crypto_boot, "resolve_and_adopt_salt", lambda _: None)
    monkeypatch.setattr(crypto_boot, "migrate_legacy_ciphertext", lambda _: None)
    monkeypatch.setattr(native_locale, "sync", no_locale_work)
    monkeypatch.setattr(seeder, "seed_registry", stop_here)

    async def boot():
        from fastapi import FastAPI
        with pytest.raises(_BootWentOn):
            async with main.lifespan(FastAPI()):
                pytest.fail("must stop at the seeders")
    return boot


async def test_boot_drops_every_task_grant_of_the_last_run_and_keeps_conversation_grants(
        execution_db, tmp_path, monkeypatch):
    await _store_grants(execution_db,
                        ("conv-1", "turn-old", "com.apple.Notes"),     # a chat turn's, never forgotten
                        ("conv-1", "job-old", "com.apple.mail"),       # a job's, its delete failed
                        ("conv-1", "", "com.apple.reminders"),         # the conversation's
                        ("conv-2", "", "com.apple.Notes"))
    boot = _boot_until_the_seeders(monkeypatch, tmp_path, execution_db)
    await boot()
    assert await _grants(execution_db) == [("conv-1", "", "com.apple.reminders"),
                                           ("conv-2", "", "com.apple.Notes")]
    # ...and a conversation grant still answers after the restart.
    with permissions.asking_with(Asker()):
        decision = await permissions.decide(Request(kind="app", target="com.apple.reminders",
                                                    title="Use Reminders?", always_label="Reminders"),
                                            Context(conversation_id="conv-1", task_id="turn-new"))
    assert (decision.allowed, decision.by, decision.scope) == (True, "grant", "conversation")


async def test_a_failing_delete_of_the_task_grants_is_logged_and_boot_goes_on(
        execution_db, tmp_path, monkeypatch, caplog):
    await _store_grants(execution_db, ("conv-1", "turn-old", "com.apple.Notes"))

    async def locked(db):
        raise OperationalError("DELETE FROM permission_grants", {}, Exception("database is locked"))

    monkeypatch.setattr(permission_store, "delete_every_task_grant", locked)
    boot = _boot_until_the_seeders(monkeypatch, tmp_path, execution_db)
    with caplog.at_level(logging.WARNING, logger="server.main"):
        await boot()                                    # reached the step after it
    assert any("task grants" in r.getMessage() and "database is locked" in r.getMessage()
               for r in caplog.records), [r.getMessage() for r in caplog.records]
    assert await _grants(execution_db) == [("conv-1", "turn-old", "com.apple.Notes")]


async def test_forgetting_every_task_grant_keeps_conversation_grants_and_clears_the_registry(execution_db):
    asker = Asker(yes("task"), yes("conversation"))
    with permissions.asking_with(asker):
        await permissions.decide(notes(), Context(conversation_id="conv-1", task_id="turn-a"))
        await permissions.decide(Request(kind="app", target="com.apple.mail", title="Use Mail?",
                                         always_label="Mail"),
                                 Context(conversation_id="conv-1", task_id="turn-a"))
    assert "turn-a" in permissions._GRANTED_TASKS
    assert await permissions.forget_every_task_grant() == 1
    assert await _grants(execution_db) == [("conv-1", "", "com.apple.mail")]
    assert not permissions._GRANTED_TASKS


# ── B. resume ──────────────────────────────────────────────────────────────────

class Crash(BaseException):
    """Simulated process loss."""


async def _a_task_given_notes_for_this_task_then_lost(execution_db, monkeypatch, how: str) -> int:
    """A chat task ("live-task") is given "For this task" on Notes and is then interrupted. Its
    grant outlives it: the process restarted (the registry is empty), or its end-of-task delete
    failed. Returns the version to resume it at."""
    async def function(conversation, message, emit):
        with permissions.asking_with(Asker(yes("task"))):
            decision = await permissions.decide(notes(), Context(conversation_id="live"))
        assert (decision.allowed, decision.scope) == (True, "task")
        current_budget().tool()
        await execution_checkpoint.save("progress")
        raise Crash()

    with pytest.raises(Crash):
        with pc.bind(pc.TaskMemoryContext(task_id="live-task", run_id="initial", conversation_id="live")):
            await task_service.run_turn(function, "live", "Tidy my notes", lambda event: None)
    assert await _grants(execution_db) == [("live", "live-task", "com.apple.Notes")]
    if how == "restarted":
        permissions._reset_for_tests()                    # a new process: nothing registered
    else:
        real = permission_store.delete_task_grants

        async def locked(db, task_id):
            raise OperationalError("DELETE FROM permission_grants", {}, Exception("database is locked"))
        monkeypatch.setattr(permission_store, "delete_task_grants", locked)
        with pytest.raises(OperationalError):
            await permissions.forget_task("live-task")
        monkeypatch.setattr(permission_store, "delete_task_grants", real)
    assert await _grants(execution_db) == [("live", "live-task", "com.apple.Notes")]
    await task_service.recover_interrupted()
    async with repository() as repo:
        return (await repo.get("live-task")).version


@pytest.mark.parametrize("how", ["restarted", "forget_failed"])
async def test_a_resumed_task_is_asked_again_for_what_it_was_given_before(execution_db, monkeypatch, how):
    version = await _a_task_given_notes_for_this_task_then_lost(execution_db, monkeypatch, how)
    asker, seen = Asker(yes("task")), []

    async def answer(conversation, message, emit, **kwargs):
        seen.append(pc.current().task_id)
        with permissions.asking_with(asker):
            seen.append(await permissions.decide(notes(), Context(conversation_id="live")))
        return "continued"

    monkeypatch.setattr(arslan, "_handle_answer", answer)
    assert await task_service.resume_turn("live-task", version, "live", lambda event: None) == "continued"
    task_id, decision = seen
    assert task_id == "live-task"                        # the same task, resumed under its own id
    assert len(asker.frames) == 1, "the stale grant answered for the resumed task"
    assert (decision.allowed, decision.by, decision.scope) == (True, "user", "task")


async def test_a_resume_drops_only_its_own_tasks_grants(execution_db, monkeypatch):
    version = await _a_task_given_notes_for_this_task_then_lost(execution_db, monkeypatch, "restarted")
    await _store_grants(execution_db, ("live", "", "com.apple.mail"),          # the conversation's
                        ("live", "other-task", "com.apple.Notes"))             # another task's

    async def answer(conversation, message, emit, **kwargs):
        return "continued"

    monkeypatch.setattr(arslan, "_handle_answer", answer)
    assert await task_service.resume_turn("live-task", version, "live", lambda event: None) == "continued"
    assert sorted(await _grants(execution_db)) == [("live", "", "com.apple.mail"),
                                                   ("live", "other-task", "com.apple.Notes")]


async def test_a_resume_that_cannot_start_keeps_the_grants_it_did_not_get_to_drop(execution_db, monkeypatch):
    """The drop is part of the resume's own transaction: a resume refused (here, a stale version)
    changes nothing — the next resume, or the next boot, drops them."""
    from server.services.task_repository import TaskError
    version = await _a_task_given_notes_for_this_task_then_lost(execution_db, monkeypatch, "restarted")
    with pytest.raises(TaskError):
        await task_service.resume_turn("live-task", version + 1, "live", lambda event: None)
    assert await _grants(execution_db) == [("live", "live-task", "com.apple.Notes")]
    async with execution_db() as db:
        assert await db.scalar(sa.select(sa.func.count()).select_from(PermissionGrant)) == 1
