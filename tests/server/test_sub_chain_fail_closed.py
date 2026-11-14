"""SUB2 follow-up (S5a): a sub-session whose chain can't be read whole runs in "Ask every step", narrowed by any mode
it did read: never the default, never wider than a mode it read. A whole chain reads as before.

SUB2's rule (`sub_sessions`' module docstring): a chain that can't be read (a parent gone, a loop, more layers than
exist) fails closed. The mode is read along the chain at each step (`permissions._chosen`); before this, a broken
chain read the sub-session's own mode, else the default. The default here is "Full access", so falling back to it
shows. Broken chains are made by hand: `create_child` refuses every one of them."""
from __future__ import annotations

import pytest

from server.db import session as db_session
from server.db.companion_models import ConversationContext
from server.services import permission_store, permissions, settings_service, sub_sessions
from server.services.permissions import Context, Request

TOP, CHILD, LEAF = "thread-top", "sub-child", "sub-leaf"
WRITE = ("write_file", {"path": "a.txt", "content": "x"})


class Asker:
    def __init__(self):
        self.frames: list[dict] = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": False, "scope": None, "note": "", "by": "mac"}


@pytest.fixture(autouse=True)
async def _fresh(execution_db, monkeypatch, tmp_path):
    permission_store._reset_for_tests()
    permissions._reset_for_tests()
    sub_sessions._reset_for_tests()
    # No fallback: "Ask only when risky" holds as itself, so only the chain decides what runs as "ask".
    from server.services import command_sandbox
    monkeypatch.setattr(command_sandbox, "available", lambda: True)

    async def folder(db):
        return tmp_path / "work"
    monkeypatch.setattr(settings_service, "workspace_dir_for_run", folder)
    (tmp_path / "work").mkdir()
    async with db_session.AsyncSessionLocal() as db:
        await settings_service.update_settings(db, {"default_permission_mode": "full_access"})
    yield
    sub_sessions._reset_for_tests()


async def _row(cid: str, mode: str | None = None, *, parent: str | None = None, kind: str | None = None) -> None:
    async with db_session.AsyncSessionLocal() as db:
        db.add(ConversationContext(id=cid, permission_mode=mode, parent_id=parent, kind=kind))
        await db.commit()


async def _sub(cid: str, mode: str | None = None, *, parent: str | None) -> None:
    await _row(cid, mode, parent=parent, kind=sub_sessions.SUB)


async def _mode(cid: str) -> tuple[str, str]:
    state = await permissions.mode_for(cid)
    return state.mode, state.chosen


# ── a chain that can't be read whole: "ask" ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("own", [None, "ask_risky", "full_access"])
async def test_a_parent_row_that_is_missing_runs_the_sub_session_in_ask(own):
    await _sub(CHILD, own, parent="thread-gone")
    assert await _mode(CHILD) == ("ask", "ask")


async def test_a_sub_session_that_names_no_parent_runs_in_ask():
    await _sub(CHILD, parent=None)
    assert await _mode(CHILD) == ("ask", "ask")


@pytest.mark.parametrize("kept", [None, "full_access"])
async def test_a_deleted_parent_runs_the_sub_session_in_ask_whatever_its_tombstone_kept(kept):
    """A tombstone keeps the mode the conversation had (`sub_sessions.tombstone` only sets the strict values)."""
    await _row(TOP, kept)
    await _sub(CHILD, parent=TOP)
    async with db_session.AsyncSessionLocal() as db:
        await sub_sessions.tombstone(db, [TOP])
        await db.commit()
    assert await _mode(CHILD) == ("ask", "ask")


@pytest.mark.parametrize("whose", ["the parent's", "its own"])
async def test_a_delete_that_began_here_runs_the_sub_session_in_ask(whose):
    """`sub_sessions.deleted`: a delete marks what goes before its commit, and a commit that fails leaves the mark. The
    sub-session is still one, under a parent with no tombstone: its parent's delete kept it, or its own failed."""
    await _row(TOP, "full_access")
    await _sub(CHILD, parent=TOP)
    async with db_session.AsyncSessionLocal() as db:
        if whose == "its own":
            result = await sub_sessions.before_delete(db, CHILD, choice=None, as_sub_session=True)
        else:
            result = await sub_sessions.before_delete(db, TOP, choice="keep", as_sub_session=False)
        await db.rollback()
    assert result == (([CHILD], []) if whose == "its own" else ([TOP], [CHILD]))
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(ConversationContext, CHILD)
        assert (row.kind, row.parent_id) == (sub_sessions.SUB, TOP)
    assert await _mode(CHILD) == ("ask", "ask")


@pytest.mark.parametrize("loop", ["itself", "two"])
async def test_a_loop_runs_in_ask(loop):
    if loop == "itself":
        await _sub(CHILD, parent=CHILD)
    else:
        await _sub(CHILD, parent=LEAF)
        await _sub(LEAF, "full_access", parent=CHILD)
    assert await _mode(CHILD) == ("ask", "ask")


async def test_more_layers_than_exist_run_in_ask():
    """`sub_sessions.MAX_DEPTH` layers is a whole chain; one more is more layers than exist (as `_chain` reads it)."""
    await _row(TOP, "full_access")
    ids = [f"sub-{n}" for n in range(1, sub_sessions.MAX_DEPTH + 1)]
    for parent, cid in zip([TOP, *ids], ids):
        await _sub(cid, parent=parent)
    assert await _mode(ids[-2]) == ("full_access", "full_access")
    assert await _mode(ids[-1]) == ("ask", "ask")


async def test_a_chain_that_cant_be_read_runs_in_ask(monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession
    await _row(TOP, "full_access")
    await _sub(CHILD, parent=TOP)
    real = AsyncSession.get

    async def get(self, model, ident, *a, **kw):
        if ident == TOP:
            raise OSError("stand-in read error")
        return await real(self, model, ident, *a, **kw)
    monkeypatch.setattr(AsyncSession, "get", get)
    assert await _mode(CHILD) == ("ask", "ask")


async def test_each_reader_of_the_mode_sees_ask():
    """The window's mode route, the command gate's two ask-all checks, and a card the mode would have answered."""
    from server.api.conversations import _permission_mode_out
    from server.orchestrator import command_gate
    await _sub(CHILD, parent="thread-gone")
    async with db_session.AsyncSessionLocal() as db:
        shown = await _permission_mode_out(db, CHILD)
    assert (shown["own"], shown["chosen"], shown["mode"], shown["fallback"]) == (None, "ask", "ask", "")
    token = command_gate._CONVERSATION.set(CHILD)
    try:
        assert await command_gate._asks_for_everything()
    finally:
        command_gate._CONVERSATION.reset(token)
    assert await command_gate._chose_ask_every_step(CHILD)
    asker = Asker()
    with permissions.asking_with(asker):
        decision = await permissions.decide(Request(kind="app", target="com.apple.Notes", title="app?"),
                                            Context(CHILD, task_id="t"))
    assert asker.frames and decision.by != "mode"
    assert await permissions.plan_refusal(*WRITE, CHILD) is None


# ── narrowed by what it read ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("broken", ["missing", "deleted"])
async def test_a_plan_on_the_part_it_could_read_still_holds(broken):
    await _sub(CHILD, "plan", parent=TOP)
    await _sub(LEAF, "full_access", parent=CHILD)
    if broken == "deleted":
        await _row(TOP, "full_access")
        async with db_session.AsyncSessionLocal() as db:
            await sub_sessions.tombstone(db, [TOP])
            await db.commit()
    assert await _mode(LEAF) == ("plan", "plan")
    refused = await permissions.plan_refusal(*WRITE, LEAF)
    assert refused is not None and refused["code"] == "plan_mode"


# ── a whole chain: as before ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("top, child, leaf, expected", [
    (None, None, None, "full_access"),                  # the default, read through the whole chain
    ("ask_risky", None, None, "ask_risky"),
    ("full_access", "ask", None, "ask"),
    ("ask", "full_access", "full_access", "ask"),
    ("full_access", None, "plan", "plan"),
])
async def test_a_whole_chain_reads_as_before(top, child, leaf, expected):
    async with db_session.AsyncSessionLocal() as db:
        await sub_sessions.create_child(db, TOP, CHILD)       # makes the parent's row too, as an ordinary chat has none
        await sub_sessions.create_child(db, CHILD, LEAF)
        for cid, mode in ((TOP, top), (CHILD, child), (LEAF, leaf)):
            (await db.get(ConversationContext, cid)).permission_mode = mode
        await db.commit()
    assert await _mode(LEAF) == (expected, expected)


async def test_an_ordinary_conversation_reads_as_before():
    assert await _mode("thread-new") == ("full_access", "full_access")          # no row: the default
    await _row(TOP, "plan")
    assert await _mode(TOP) == ("plan", "plan")
