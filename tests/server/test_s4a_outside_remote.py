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
    # The command did not run: the grant wrote no row for it (⓪Plan, S4a Q2).
    assert [(x.kind, x.decided_by) for x in await _rows()] == [("network", "user")]


# ── the grant's row is written only for a command that runs (⓪Plan, S4a Q2) ──

class _Cards:
    """The tool loop's confirm callback, played by the test: answers each command card with `yes`."""

    def __init__(self, yes):
        self.yes, self.calls = yes, []

    async def __call__(self, command, argv, **kw):
        self.calls.append(kw)
        return self.yes


@pytest.mark.parametrize("yes", [True, False])
async def test_a_layer_two_card_still_asks_under_the_grant_and_a_no_writes_no_grant_row(
        execution_db, monkeypatch, yes):
    await _give_outside_grant("c1")
    cards, ex = _Cards(yes), _Exec(stop=False)
    with permissions.asking_with(_Asker()):
        await _dispatch(monkeypatch, {"command": "git push origin main"}, executor=ex, cards=cards, cid="c1")
    assert [c.get("sandbox") for c in cards.calls] == [None]          # its own card, whatever the grant
    assert ex.outside == ([True] if yes else [])
    assert [(x.kind, x.decided_by) for x in await _rows()] == ([("outside", "grant")] if yes else [])


async def test_nothing_stands_with_nobody_to_ask_whatever_is_stored(execution_db):
    """The S1b invariant through the new door: a scheduled run reads no grant, however it asks."""
    await _give_outside_grant("c1")
    req = permissions.Request(kind="outside", target="*", title="t")
    assert await permissions.standing(req, permissions.Context("c1")) is None
    with permissions.asking_with(_Asker()):
        found = await permissions.standing(req, permissions.Context("c1"))
    assert found is not None and (found.decision.by, found.decision.scope) == ("grant", "conversation")
    assert await _rows() == []                                         # a lookup writes nothing


async def test_an_outside_rule_is_never_read(execution_db):
    """No "Always" lets every command out for good: a stray `outside` rule row stands for nothing."""
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_rule(db, "outside", "*", label="every command")
        await db.commit()
    with permissions.asking_with(_Asker()):
        assert await permissions.standing(permissions.Request(kind="outside", target="*", title="t"),
                                          permissions.Context("c1")) is None
    assert permissions.options_for(permissions.Request(kind="outside", target="*", title="t",
                                                       always_label="every command")) == ["once", "conversation"]


# ── with the sandbox switched off (⓪Plan, S4a Q3) ────────────────────────────

async def _sandbox_off(monkeypatch):
    async def off():
        return False
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", off)


async def test_with_the_sandbox_off_the_grant_answers_the_layer_three_card(execution_db, monkeypatch):
    await _sandbox_off(monkeypatch)
    await _give_outside_grant("c1")
    cards, ex = _Cards(False), _Exec(stop=False)
    with permissions.asking_with(_Asker()):
        r = await _dispatch(monkeypatch, {"command": "ls"}, executor=ex, cards=cards, cid="c1")
    assert cards.calls == [] and r["ok"] is True
    assert [(x.kind, x.decided_by) for x in await _rows()] == [("outside", "grant")]
    # Without the grant, the same command asks (layer ③ with no sandbox to run it in).
    cards, ex = _Cards(False), _Exec(stop=False)
    with permissions.asking_with(_Asker()):
        await _dispatch(monkeypatch, {"command": "ls"}, executor=ex, cards=cards, cid="c2")
    assert len(cards.calls) == 1 and ex.outside == []


async def test_with_the_sandbox_off_ask_for_every_command_still_asks_under_the_grant(execution_db, monkeypatch):
    await _sandbox_off(monkeypatch)

    async def yes():
        return True
    monkeypatch.setattr(tool_loop, "_asks_for_everything", yes)
    await _give_outside_grant("c1")
    cards, ex = _Cards(False), _Exec(stop=False)
    with permissions.asking_with(_Asker()):
        await _dispatch(monkeypatch, {"command": "ls"}, executor=ex, cards=cards, cid="c1")
    assert len(cards.calls) == 1 and ex.outside == []
    assert await _rows() == []


# ── another machine ──────────────────────────────────────────────────────────

async def test_the_remote_card_is_this_time_only_and_writes_a_row_each_time(execution_db):
    asker = _Asker(scope="conversation")
    ladder = command_confirm.Confirmations("c1")
    with permissions.asking_with(asker):
        for _ in range(2):
            assert await ladder.command("uptime", [], remote_host="studio (me@10.0.0.2)",
                                        fingerprints=["SHA256:x"], host="10.0.0.2") is True
    assert [f["perm_kind"] for f in asker.frames] == ["remote", "remote"]
    assert all(f["options"] == ["once"] and f["remote_host"] == "studio (me@10.0.0.2)"
               and f["title"] == "Run `uptime` on studio (me@10.0.0.2)?" for f in asker.frames)
    assert await _grants() == []
    # ⓪Plan Q7: one machine, one target — its address, whatever the card calls it.
    assert [(r.kind, r.target, r.decided_by, r.scope) for r in await _rows()] == [
        ("remote", "remote:10.0.0.2", "user", "once")] * 2


async def test_a_declined_remote_card_is_a_deny_row(execution_db):
    with permissions.asking_with(_Asker(approved=False)):
        assert await command_confirm.Confirmations("c1").command(
            "uptime", [], remote_host="me@10.0.0.2", fingerprints=[], host="10.0.0.2") is False
    assert [(r.kind, r.target, r.decided_by, r.decision) for r in await _rows()] == [
        ("remote", "remote:10.0.0.2", "user", "deny")]


async def test_a_scheduled_runs_remote_refusal_has_the_same_target(execution_db, monkeypatch):
    async def tools():
        return [{"key": "ssh_run", "description": "ssh"}]
    r = await tool_loop._dispatch_tool(
        "ssh_run", {"host": "10.0.0.2", "command": "uptime"}, "{}", resolve_tools=tools, emit=lambda e: None,
        tool_timeout_s=5, tool_trace=[], convo=[], confirm_command=None, conversation_id="c1")
    assert r["ok"] is False
    assert [(x.kind, x.target, x.decided_by) for x in await _rows()] == [("remote", "remote:10.0.0.2", "policy")]


# ── taking the grant back (⓪Plan, S4a Q5) ────────────────────────────────────

@pytest.fixture
async def api(execution_db, monkeypatch):
    import httpx
    from fastapi import FastAPI

    from server import auth
    from server.api.permissions import router
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-grants-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-grants-token"}) as client:
        yield client


async def test_the_outside_grants_are_listed_by_conversation_and_can_be_taken_back(api, execution_db, monkeypatch):
    from server.db.models import ArslanMessage
    async with db_session.AsyncSessionLocal() as db:
        db.add_all([ArslanMessage(conversation_id="c1", role="assistant", content="Hello"),
                    ArslanMessage(conversation_id="c1", role="user", content="tidy   my\nDownloads"),
                    ArslanMessage(conversation_id="c1", role="user", content="and the Desktop")])
        await permission_store.add_grant(db, "c1", "", "outside", "*", call_id="card-1")
        await permission_store.add_grant(db, "c1", "", "network", "network:*", call_id="card-2")
        await permission_store.add_grant(db, "c1", "turn-1", "outside", "*", call_id="card-3")  # a task's
        await db.commit()
    listed = (await api.get("/api/v1/permissions/grants", params={"kind": "outside"})).json()
    assert [(g["conversation_id"], g["title"], g["kind"], g["target"]) for g in listed] == [
        ("c1", "tidy my Downloads", "outside", "*")]
    assert {g["kind"] for g in (await api.get("/api/v1/permissions/grants")).json()} == {"outside", "network"}
    # Taken back: the next command of that conversation starts in the sandbox again.
    assert (await api.delete(f"/api/v1/permissions/grants/{listed[0]['id']}")).json() == {"ok": True}
    ex, asker = _Exec(), _Asker(approved=False)
    with permissions.asking_with(asker):
        await _dispatch(monkeypatch, {"command": "ls"}, executor=ex,
                        cards=command_confirm.Confirmations("c1").command, cid="c1")
    assert ex.outside == [False] and [f["sandbox"] for f in asker.frames] == ["retry"]
    assert (await api.get("/api/v1/permissions/grants", params={"kind": "outside"})).json() == []
    assert (await api.delete(f"/api/v1/permissions/grants/{listed[0]['id']}")).status_code == 404


async def test_a_tasks_grant_is_not_taken_back_here(api, execution_db):
    async with db_session.AsyncSessionLocal() as db:
        task = await permission_store.add_grant(db, "c1", "turn-1", "outside", "*", call_id="card-3")
        await db.commit()
    assert (await api.delete(f"/api/v1/permissions/grants/{task.id}")).status_code == 404
    assert await _grants() == [("c1", "turn-1", "outside", "*")]


async def test_the_grants_need_the_token(api):
    for call in (api.get("/api/v1/permissions/grants", headers={"Authorization": "Bearer wrong"}),
                 api.delete("/api/v1/permissions/grants/1", headers={"Authorization": "Bearer wrong"})):
        assert (await call).status_code == 401


# ── the old "remember" tick is unreachable (⓪Plan, S4a Q6) ───────────────────

@pytest.mark.parametrize("ask_all", [False, True])
async def test_every_command_card_carries_its_choices(execution_db, monkeypatch, ask_all):
    """Every `propose_run_command` frame is built by the one ladder and shown through decide, which stamps
    the choices: the web's old tick (shown for a frame without `options`) has nothing left to show on."""
    from unittest.mock import AsyncMock

    from server.services import settings_service
    monkeypatch.setattr(settings_service, "shell_confirm_policy",
                        AsyncMock(return_value="ask_all" if ask_all else "ask_risky"))
    asker = _Asker(approved=False)
    ladder = command_confirm.Confirmations("c1")
    with permissions.asking_with(asker):
        await ladder.command("git push origin main", [])                       # layer ②
        await ladder.command("ls", [])                                         # layer ③ / ask for everything
        await ladder.command("curl https://example.com", [], network=True)     # with the network
        await ladder.command("mv a ~/b", [], sandbox="outside", why="w")       # leave the sandbox
        await ladder.command("mv a ~/b", [], sandbox="retry")                  # stopped by it
        await ladder.command("uptime", [], remote_host="me@10.0.0.2", host="10.0.0.2", fingerprints=[])
    assert [f["type"] for f in asker.frames] == ["propose_run_command"] * 6
    assert all(f.get("options") for f in asker.frames)
