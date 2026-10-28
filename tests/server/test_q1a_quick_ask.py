"""Q1a (v0.1.64, card docs/plans/0164/Q1-quick-ask.md): quick questions on the Mac's side.

A quick question is a new conversation of its own, stored as `kind = quick` (migration 0071). It is shown
and may call exactly four read-only tools, read from that stored kind and never from the frame; it learns
nothing; and it stays out of the ordinary lists, with a list of its own for the phone.
"""
import sqlalchemy as sa

from server.db.migrations import runner
from server.db.migrations.versions import _0071_conversation_kind as m0071


# -- migration 0071: add-only ------------------------------------------------------------------------------

def test_0071_adds_kind_and_parent_once_and_touches_nothing_else(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'contexts.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE conversation_contexts (id VARCHAR(100) PRIMARY KEY, "
                                 "no_learning BOOLEAN NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1)")
            conn.exec_driver_sql("INSERT INTO conversation_contexts (id, no_learning, version) VALUES ('c-1', 1, 3)")
            m0071.upgrade_sync(conn)
            m0071.upgrade_sync(conn)
            columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversation_contexts)")]
            row = conn.exec_driver_sql("SELECT id, no_learning, version, kind, parent_id FROM conversation_contexts").one()
    finally:
        engine.dispose()
    assert columns == ["id", "no_learning", "version", "kind", "parent_id"]
    assert tuple(row) == ("c-1", 1, 3, None, None)


def test_0071_leaves_a_database_without_the_table_alone(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bare.db'}")
    try:
        with engine.begin() as conn:
            m0071.upgrade_sync(conn)
            assert conn.exec_driver_sql("SELECT name FROM sqlite_master").all() == []
    finally:
        engine.dispose()


def test_0071_runs_after_0070_and_before_0074():
    order = [version for version, _ in runner.MIGRATIONS]
    assert order.index("0070") < order.index("0071") < order.index("0074")


# -- four read-only tools, from the stored kind ---------------------------------------------------------------

import pytest  # noqa: E402

from server.db.companion_models import ConversationContext  # noqa: E402
from server.orchestrator import arslan, tool_loop  # noqa: E402

QUICK = ["conversation_search", "recall", "web_extract", "web_search"]


async def _store(db, conversation_id, kind):
    async with db() as session:
        session.add(ConversationContext(id=conversation_id, kind=kind, no_learning=kind == "quick"))
        await session.commit()


def _capture(monkeypatch) -> dict:
    """What the chat turn hands the tool loop: the tools shown, the tools it may call, and the turn's notes."""
    seen = {}

    async def run_native(*, system, user_content, on_chunk, resolve_tools, resolve_callable, turn_notes=None, **kw):
        seen["shown"] = sorted(tool["key"] for tool in await resolve_tools())
        seen["callable"] = sorted(tool["key"] for tool in await resolve_callable())
        seen["notes"] = list(turn_notes or [])
        on_chunk("ok")
        return {"final": "ok", "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", run_native)
    return seen


@pytest.mark.parametrize("all_resident", [False, True], ids=["on-demand", "tools_all_resident"])
async def test_a_stored_quick_question_is_shown_and_may_call_exactly_four_tools(execution_db, monkeypatch,
                                                                                all_resident):
    async def resident():
        return all_resident
    monkeypatch.setattr(arslan, "_all_resident", resident)
    await _store(execution_db, "phone-0b7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b", "quick")
    seen = _capture(monkeypatch)
    await arslan._handle_answer("phone-0b7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b", "weather in Kashgar?", lambda e: None,
                                source="phone")
    assert seen["shown"] == QUICK and seen["callable"] == QUICK
    assert arslan.QUICK_NOTE in seen["notes"] and arslan.PHONE_NOTE not in seen["notes"]


async def test_the_same_message_in_an_ordinary_conversation_gets_every_tool(execution_db, monkeypatch):
    seen = _capture(monkeypatch)
    await arslan._handle_answer("c-plain", "weather in Kashgar?", lambda e: None, source="phone")
    assert {"find_tools", "use_tool", "run_command", "remember"} <= set(seen["shown"])
    assert set(QUICK) < set(seen["callable"]) and "run_command" in seen["callable"]
    assert arslan.PHONE_NOTE in seen["notes"] and arslan.QUICK_NOTE not in seen["notes"]


async def test_a_kind_that_cannot_be_read_gets_the_four_tools_never_every_tool(execution_db, monkeypatch):
    """Fails closed (card, rule 4): an unreadable row narrows the tools; it does not say "quick question"."""
    async def unreadable(conversation_id):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(arslan, "_stored_kind", unreadable)
    seen = _capture(monkeypatch)
    await arslan._handle_answer("c-plain", "weather in Kashgar?", lambda e: None)
    assert seen["shown"] == QUICK and seen["callable"] == QUICK and arslan.QUICK_NOTE not in seen["notes"]


async def test_only_the_stored_kind_counts_never_what_a_frame_says(execution_db, monkeypatch):
    """A conversation turned back into a chat, or never stored as quick, gets every tool, whatever the phone's
    frame carried: the server reads the conversation's own row (card, rule 3)."""
    await _store(execution_db, "phone-2b7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b", "chat")
    seen = _capture(monkeypatch)
    await arslan._handle_answer("phone-2b7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b", "go on", lambda e: None, source="phone")
    assert "run_command" in seen["callable"]


# -- learns nothing: the row's no_learning, read by both after-turn paths ---------------------------------------

@pytest.mark.parametrize("kind,looked", [("quick", False), (None, True)], ids=["quick", "ordinary"])
async def test_a_quick_question_extracts_no_facts_after_its_turn(execution_db, monkeypatch, kind, looked):
    from server.services import turn_facts
    cid = "phone-3b7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b"
    if kind:
        await _store(execution_db, cid, kind)
    asked = []

    async def capture(conversation_id, user_message, emit, recheck=None):
        asked.append(conversation_id)
        return 0

    async def compact(*args, **kwargs):
        return None
    monkeypatch.setattr(turn_facts, "capture", capture)
    monkeypatch.setattr(arslan.memory, "maybe_compact", compact)
    from server.services import task_context
    turn = await task_context.load(cid, user_message="I live in Kashgar")      # the turn's context, as a chat turn has
    await arslan._after_turn(cid, "I live in Kashgar", lambda e: None, turn, budget=1000, reply_id=None, after=None)
    assert bool(asked) is looked


# -- the phone's endpoints ------------------------------------------------------------------------------------

from datetime import datetime  # noqa: E402


from server.db.models import ArslanMessage  # noqa: E402
from server.services import run_registry  # noqa: E402

Q1 = "phone-4b7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b"
Q2 = "phone-5b7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b"


async def _row(client, conversation_id):
    async with client.db_maker() as db:
        return await db.get(ConversationContext, conversation_id)


async def _say(client, conversation_id, text, at):
    async with client.db_maker() as db:
        db.add(ArslanMessage(conversation_id=conversation_id, role="user", content=text,
                             timestamp=datetime.fromisoformat(at)))
        await db.commit()


async def test_a_new_quick_question_is_stored_quick_and_learns_nothing(client):
    async with client.db_maker() as db:
        db.add(ConversationContext(id=Q1, no_memory=True))          # a switch already set stays as it was
        await db.commit()
    got = await client.post(f"/api/v1/phone/conversations/{Q1}/quick")
    assert got.status_code == 200 and got.json() == {"conversation_id": Q1, "kind": "quick"}
    row = await _row(client, Q1)
    assert (row.kind, row.no_learning, row.no_memory) == ("quick", True, True)
    assert (await client.post(f"/api/v1/phone/conversations/{Q1}/quick")).status_code == 200    # a retry
    fresh = await client.post(f"/api/v1/phone/conversations/{Q2}/quick")
    assert fresh.status_code == 200 and (await _row(client, Q2)).no_memory is False


@pytest.mark.parametrize("conversation_id", ["trip", "phone-not-a-uuid", "phone-4B7C9A2E-1C1D-4F5E-9A8B-3C2D1E0F9A8B",
                                             "pocket"])
async def test_only_a_phone_shaped_new_id_can_become_a_quick_question(client, conversation_id):
    got = await client.post(f"/api/v1/phone/conversations/{conversation_id}/quick")
    assert got.status_code == 400 and got.json()["detail"] == "bad_request"
    assert await _row(client, conversation_id) is None


async def test_a_conversation_that_already_has_messages_never_becomes_quick(client):
    """Its first turn would have run with every tool already (card, risks)."""
    await _say(client, Q1, "hello", "2026-10-29T08:00:00")
    got = await client.post(f"/api/v1/phone/conversations/{Q1}/quick")
    assert got.status_code == 409 and got.json()["detail"] == "conversation_exists"
    assert await _row(client, Q1) is None


async def test_converting_a_quick_question_makes_it_an_ordinary_chat(client):
    await client.post(f"/api/v1/phone/conversations/{Q1}/quick")
    await _say(client, Q1, "weather?", "2026-10-29T08:00:00")
    got = await client.post(f"/api/v1/phone/conversations/{Q1}/update", json={"kind": "chat"})
    assert got.status_code == 200 and got.json() == {"conversation_id": Q1, "kind": "chat"}
    row = await _row(client, Q1)
    # Whether it starts learning is the user's open question (card, #3); until then it doesn't.
    assert (row.kind, row.no_learning) == ("chat", True)


async def test_converting_refuses_while_a_turn_runs_an_unknown_conversation_or_another_kind(client, monkeypatch):
    await client.post(f"/api/v1/phone/conversations/{Q1}/quick")
    assert (await client.post(f"/api/v1/phone/conversations/{Q1}/update", json={"kind": "quick"})).json()["detail"] == "bad_request"
    unknown = await client.post(f"/api/v1/phone/conversations/{Q2}/update", json={"kind": "chat"})
    assert unknown.status_code == 404 and unknown.json()["detail"] == "not_found"
    monkeypatch.setattr(run_registry, "active_for", lambda cid: cid == Q1)
    busy = await client.post(f"/api/v1/phone/conversations/{Q1}/update", json={"kind": "chat"})
    assert busy.status_code == 409 and busy.json()["detail"] == "mac_busy"
    assert (await _row(client, Q1)).kind == "quick"


async def test_quick_questions_have_a_list_of_their_own_and_stay_out_of_every_other(client):
    await client.post(f"/api/v1/phone/conversations/{Q1}/quick")
    await _say(client, Q1, "weather?", "2026-10-29T08:00:00")
    await _say(client, "trip", "Plan a trip", "2026-10-29T07:00:00")
    plain = (await client.get("/api/v1/phone/conversations")).json()["conversations"]
    assert [c["id"] for c in plain] == ["trip"]
    assert [c["conversation_id"] for c in (await client.get("/api/v1/conversations")).json()] == ["trip"]
    quick = (await client.get("/api/v1/phone/conversations?kind=quick")).json()
    assert [(c["id"], c["kind"]) for c in quick["conversations"]] == [(Q1, "quick")] and quick["has_more"] is False
    assert (await client.get("/api/v1/phone/conversations?kind=task")).json()["detail"] == "bad_request"


async def test_before_pages_back_through_strictly_older_conversations(client):
    for n, at in enumerate(("2026-10-29T08:00:03", "2026-10-29T08:00:02", "2026-10-29T08:00:01")):
        await _say(client, f"c-{n}", f"question {n}", at)
    first = (await client.get("/api/v1/phone/conversations?limit=2")).json()
    assert [c["id"] for c in first["conversations"]] == ["c-0", "c-1"] and first["has_more"] is True
    rest = (await client.get(f"/api/v1/phone/conversations?limit=2&before={first['conversations'][-1]['updated_at']}")).json()
    assert [c["id"] for c in rest["conversations"]] == ["c-2"] and rest["has_more"] is False
