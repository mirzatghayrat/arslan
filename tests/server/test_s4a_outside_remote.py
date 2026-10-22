"""S4a: the card that lets a command out of the sandbox (kind `outside`) and the card for another
machine (kind `remote`) are decided by `permissions.decide`: each writes a ledger row and a scheduled
run's refusal is listed in the Inbox. "In this conversation" on the outside card is a stored
conversation grant (it was a set in memory): it survives a restart, and a background job of that
conversation honours it — a scheduled run does not (S1)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import PermissionGrant
from server.orchestrator import tool_loop
from server.services import (approvals, command_confirm, command_sandbox, permission_store, permissions,
                             terminal_exec)


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    command_sandbox._reset_for_tests()
    permissions._reset_for_tests()
    approvals._reset_for_tests()

    async def no():
        return False

    async def yes():
        return True
    monkeypatch.setattr(tool_loop, "_asks_for_everything", no)
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", yes)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    yield
    command_sandbox._reset_for_tests()
    permissions._reset_for_tests()
    approvals._reset_for_tests()


class _Exec:
    """Stand-in executor: 'stopped by the sandbox' unless the loop let it out."""
    key = "run_command"

    def __init__(self, stop=True):
        self.stop = stop
        self.outside: list[bool] = []

    async def execute(self, args):
        out = terminal_exec.OUTSIDE_SANDBOX.get()
        self.outside.append(out)
        if self.stop and not out:
            return {"ok": False, "exit_code": 1, "stdout": "", "stderr": "operation not permitted: /x",
                    "sandbox": "workspace", "sandbox_denied": True, "note": "stopped"}
        return {"ok": True, "exit_code": 0, "stdout": "done", "stderr": "", "sandbox": "off" if out else "workspace"}


class _Asker:
    """A card surface that records every card and answers each with `answer` (by the asking window)."""

    def __init__(self, approved=True, scope="once", by="mac"):
        self.frames: list[dict] = []
        self.reply = {"approved": approved, "scope": scope, "note": "", "by": by}

    async def __call__(self, frame):
        self.frames.append(frame)
        return {**self.reply, "call_id": frame["call_id"]}


async def _resolve():
    return [{"key": "run_command", "description": "run"}]


async def _dispatch(monkeypatch, args, *, executor, cards, cid):
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", executor)
    return await tool_loop._dispatch_tool(
        "run_command", args, "{}", resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5,
        tool_trace=[], convo=[], confirm_command=cards, conversation_id=cid)


async def _rows():
    async with db_session.AsyncSessionLocal() as db:
        return list(reversed(await permission_store.recent(db)))


async def _grants():
    async with db_session.AsyncSessionLocal() as db:
        return [(g.conversation_id, g.task_id, g.kind, g.target)
                for g in (await db.execute(select(PermissionGrant))).scalars().all()]


async def _give_outside_grant(cid="c1"):
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_grant(db, cid, "", "outside", "*", call_id="card-1")
        await db.commit()


# ── the outside card is a decide() card ──────────────────────────────────────

async def test_the_outside_card_offers_this_time_or_this_conversation_and_writes_a_row(execution_db):
    asker = _Asker(scope="conversation")
    with permissions.asking_with(asker):
        assert await command_confirm.Confirmations("c1").command("mv a ~/b", [], sandbox="outside", why="w") is True
    frame = asker.frames[0]
    assert frame["perm_kind"] == "outside" and frame["options"] == ["once", "conversation"]
    assert frame["sandbox"] == "outside" and frame["always_label"] == ""
    assert await _grants() == [("c1", "", "outside", "*")]
    [row] = await _rows()
    assert (row.kind, row.target, row.decided_by, row.decision, row.scope) == (
        "outside", "*", "user", "allow", "conversation")


async def test_the_retry_card_is_the_same_request(execution_db):
    asker = _Asker(scope="conversation")
    with permissions.asking_with(asker):
        assert await command_confirm.Confirmations("c1").command("mv a ~/b", [], sandbox="retry") is True
    assert asker.frames[0]["perm_kind"] == "outside" and asker.frames[0]["sandbox"] == "retry"
    assert await _grants() == [("c1", "", "outside", "*")]


async def test_once_stores_nothing(execution_db):
    with permissions.asking_with(_Asker(scope="once")):
        assert await command_confirm.Confirmations("c1").command("mv a ~/b", [], sandbox="outside") is True
    assert await _grants() == []
    assert [(r.decided_by, r.scope) for r in await _rows()] == [("user", "once")]


@pytest.mark.parametrize("source", ["phone", "island"])
async def test_the_phone_and_the_island_never_give_the_grant(execution_db, source):
    with permissions.asking_with(_Asker(scope="conversation", by=source)):
        assert await command_confirm.Confirmations("c1").command("mv a ~/b", [], sandbox="outside") is True
    assert await _grants() == []


async def test_an_unanswered_outside_card_is_expired_not_refused(execution_db):
    with permissions.asking_with(_Asker(approved=False, scope=None, by=None)):
        assert await command_confirm.Confirmations("c1").command("mv a ~/b", [], sandbox="outside") is False
    [row] = await _rows()
    assert (row.kind, row.decided_by, row.decision) == ("outside", "expired", "expired")
    assert approvals.LAST_OUTCOME.get() == "expired"


async def test_a_jobs_outside_card_offers_this_conversation_and_its_answer_is_the_conversations(
        execution_db, monkeypatch):
    job = approvals.JobConfirmations("c1", job_id="job-1")
    asker = _Asker(scope="conversation")
    monkeypatch.setattr(job, "asker", asker)
    assert await job.command("mv a ~/b", [], sandbox="retry") is True
    assert asker.frames[0]["options"] == ["once", "conversation"]
    assert await _grants() == [("c1", "", "outside", "*")]
    [row] = await _rows()
    assert row.job_id == "job-1"


# ── the stored grant ─────────────────────────────────────────────────────────

async def test_the_grant_lets_the_next_command_out_with_no_card_and_a_grant_row(execution_db, monkeypatch):
    await _give_outside_grant("c1")
    asker = _Asker()
    ex = _Exec()
    with permissions.asking_with(asker):
        r = await _dispatch(monkeypatch, {"command": "ls"}, executor=ex,
                            cards=command_confirm.Confirmations("c1").command, cid="c1")
    assert ex.outside == [True] and r["ran_outside_sandbox"] is True and asker.frames == []
    [row] = await _rows()
    assert (row.kind, row.target, row.decided_by, row.decision, row.scope, row.conversation_id, row.detail) == (
        "outside", "*", "grant", "allow", "conversation", "c1", "ls")


async def test_the_grant_is_one_conversations(execution_db, monkeypatch):
    await _give_outside_grant("c1")
    ex = _Exec()
    asker = _Asker(approved=False)
    with permissions.asking_with(asker):
        await _dispatch(monkeypatch, {"command": "ls"}, executor=ex,
                        cards=command_confirm.Confirmations("c2").command, cid="c2")
    assert ex.outside == [False] and [f["sandbox"] for f in asker.frames] == ["retry"]


async def test_the_grant_survives_a_restart(execution_db, monkeypatch):
    with permissions.asking_with(_Asker(scope="conversation")):
        await command_confirm.Confirmations("c1").command("mv a ~/b", [], sandbox="outside")
    # A restart: every in-memory registry starts empty; the database stays.
    command_sandbox._reset_for_tests()
    permissions._reset_for_tests()
    approvals._reset_for_tests()
    ex = _Exec()
    with permissions.asking_with(_Asker(approved=False)):
        await _dispatch(monkeypatch, {"command": "ls"}, executor=ex,
                        cards=command_confirm.Confirmations("c1").command, cid="c1")
    assert ex.outside == [True]


async def test_a_background_job_honours_its_conversations_grant(execution_db, monkeypatch):
    from server.services import background_jobs
    await _give_outside_grant("c1")
    job = approvals.JobConfirmations("c1", job_id="job-1")
    asker = _Asker(approved=False)
    monkeypatch.setattr(job, "asker", asker)
    token = background_jobs._inside_job.set("job-1")
    try:
        with permissions.asking_with(asker):
            ex = _Exec()
            r = await _dispatch(monkeypatch, {"command": "ls", "outside_sandbox": True}, executor=ex,
                                cards=job.command, cid="c1")
    finally:
        background_jobs._inside_job.reset(token)
    assert ex.outside == [True] and r["ran_outside_sandbox"] is True and asker.frames == []
    [row] = await _rows()
    assert (row.decided_by, row.job_id) == ("grant", "job-1")


async def test_a_scheduled_run_never_honours_the_grant_and_its_refusal_is_listed(execution_db, monkeypatch):
    await _give_outside_grant("c1")
    ex = _Exec(stop=False)
    r = await _dispatch(monkeypatch, {"command": "ls"}, executor=ex, cards=None, cid="c1")
    assert ex.outside == [False] and "ran_outside_sandbox" not in r
    ex = _Exec(stop=False)
    r = await _dispatch(monkeypatch, {"command": "ls", "outside_sandbox": True}, executor=ex, cards=None, cid="c1")
    assert ex.outside == [] and r["ok"] is False
    rows = await _rows()
    assert [(x.kind, x.target, x.decided_by, x.decision) for x in rows] == [("outside", "*", "policy", "deny")]
    async with db_session.AsyncSessionLocal() as db:
        listed = await permission_store.refused_groups(db, datetime.utcnow() - timedelta(hours=1))
    assert [(row.kind, count) for row, count, _ in listed] == [("outside", 1)]


async def test_the_in_memory_grant_is_gone():
    assert not hasattr(command_sandbox, "grant") and not hasattr(command_sandbox, "granted")


async def test_under_the_grant_the_network_card_is_this_time_only_and_a_network_grant_does_not_answer_it(
        execution_db, monkeypatch):
    """S2a-1 piece 2, with S4a's stored grant: outside the sandbox the user's secrets are readable, so
    the network card after outside content is once only, and a `network:*` conversation grant is no
    answer to it."""
    from server.orchestrator import untrusted
    await _give_outside_grant("c1")
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_grant(db, "c1", "", "network", "network:*", call_id="card-2")
        await db.commit()
    monkeypatch.setattr(untrusted, "external_seen", lambda: True)
    asker = _Asker(approved=False)
    ex = _Exec(stop=False)
    with permissions.asking_with(asker):
        r = await _dispatch(monkeypatch, {"command": "ls", "network": True}, executor=ex,
                            cards=command_confirm.Confirmations("c1").command, cid="c1")
    assert ex.outside == [] and r["ok"] is False
    net = [f for f in asker.frames if f.get("perm_kind") == "network"]
    assert len(net) == 1 and net[0]["options"] == ["once"]


# ── another machine ──────────────────────────────────────────────────────────

async def test_the_remote_card_is_this_time_only_and_writes_a_row_each_time(execution_db):
    asker = _Asker(scope="conversation")
    ladder = command_confirm.Confirmations("c1")
    with permissions.asking_with(asker):
        for _ in range(2):
            assert await ladder.command("uptime", [], remote_host="studio (me@10.0.0.2)",
                                        fingerprints=["SHA256:x"]) is True
    assert [f["perm_kind"] for f in asker.frames] == ["remote", "remote"]
    assert all(f["options"] == ["once"] and f["remote_host"] == "studio (me@10.0.0.2)" for f in asker.frames)
    assert await _grants() == []
    assert [(r.kind, r.target, r.decided_by, r.scope) for r in await _rows()] == [
        ("remote", "studio (me@10.0.0.2)", "user", "once")] * 2


async def test_a_declined_remote_card_is_a_deny_row(execution_db):
    with permissions.asking_with(_Asker(approved=False)):
        assert await command_confirm.Confirmations("c1").command(
            "uptime", [], remote_host="me@10.0.0.2", fingerprints=[]) is False
    assert [(r.kind, r.decided_by, r.decision) for r in await _rows()] == [("remote", "user", "deny")]
