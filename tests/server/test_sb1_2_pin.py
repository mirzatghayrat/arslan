"""SB1-2 (v0.1.64, card docs/plans/0164/SB1-sidebar.md): a conversation pinned to the top of the sidebar, stored
on its context row (migration 0079), set by its own route, `PUT /conversations/{id}/pin`: allowed while the
conversation runs, upserting a row many conversations don't have, touching nothing but `pinned` (never
`version`), and read back in `GET /conversations`."""
import sqlalchemy as sa

from server.db.companion_models import ConversationContext
from server.db.migrations import runner
from server.db.migrations.versions import _0079_conversation_pinned as m0079
from server.db.models import ArslanMessage
from server.ws import arslan as ws_arslan


# -- migration 0079: add-only ----------------------------------------------------------------------------

def test_0079_adds_the_pin_once_and_touches_nothing_else(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'contexts.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE conversation_contexts (id VARCHAR(100) PRIMARY KEY, "
                                 "version INTEGER NOT NULL DEFAULT 1)")
            conn.exec_driver_sql("INSERT INTO conversation_contexts (id, version) VALUES ('c-1', 3)")
            m0079.upgrade_sync(conn)
            m0079.upgrade_sync(conn)
            columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversation_contexts)")]
            row = conn.exec_driver_sql("SELECT * FROM conversation_contexts").one()
    finally:
        engine.dispose()
    assert columns == ["id", "version", "pinned"]
    assert tuple(row) == ("c-1", 3, 0)


def test_0079_leaves_a_database_without_the_table_alone(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bare.db'}")
    try:
        with engine.begin() as conn:
            m0079.upgrade_sync(conn)
            assert conn.exec_driver_sql("SELECT name FROM sqlite_master").all() == []
    finally:
        engine.dispose()


def test_0079_runs_after_0078_and_before_0080():
    order = [version for version, _ in runner.MIGRATIONS]
    assert order.index("0078") < order.index("0079") < order.index("0080")


# -- the route ---------------------------------------------------------------------------------------------

async def _say(client, conversation_id, text="hi"):
    async with client.db_maker() as db:
        db.add(ArslanMessage(conversation_id=conversation_id, role="user", content=text))
        await db.commit()


async def _row(client, conversation_id):
    async with client.db_maker() as db:
        return await db.get(ConversationContext, conversation_id)


async def _listed(client) -> dict:
    return {c["conversation_id"]: c["pinned"] for c in (await client.get("/api/v1/conversations")).json()}


async def test_a_pin_is_set_cleared_and_read_back_in_the_list(client):
    await _say(client, "c1")
    await _say(client, "c2")
    assert await _listed(client) == {"c1": False, "c2": False}
    put = await client.put("/api/v1/conversations/c1/pin", json={"pinned": True})
    assert put.status_code == 200 and put.json() == {"conversation_id": "c1", "pinned": True}
    assert await _listed(client) == {"c1": True, "c2": False}                  # a reload reads it back
    await client.put("/api/v1/conversations/c1/pin", json={"pinned": False})
    assert await _listed(client) == {"c1": False, "c2": False}


async def test_it_makes_the_row_a_conversation_lacks_and_never_moves_its_version(client):
    await _say(client, "c1")
    assert await _row(client, "c1") is None                                    # many conversations have none
    await client.put("/api/v1/conversations/c1/pin", json={"pinned": True})
    row = await _row(client, "c1")
    assert row.pinned is True and row.version == 1 and row.no_memory is False and row.project_id is None
    # A settings edit made against that version still goes through, and keeps the pin.
    saved = await client.put("/api/v1/conversations/c1/context", json={"expected_version": 1, "no_memory": True})
    assert saved.status_code == 200, saved.json()
    row = await _row(client, "c1")
    assert row.pinned is True and row.version == 2
    await client.put("/api/v1/conversations/c1/pin", json={"pinned": False})
    assert (await _row(client, "c1")).version == 2                             # the pin never bumps it


async def test_it_works_while_the_conversation_runs(client):
    await _say(client, "c1")
    lock = ws_arslan._turn_lock("c1")
    await lock.acquire()                                                       # a turn holds it
    try:
        refused = await client.put("/api/v1/conversations/c1/context", json={"expected_version": 0})
        assert refused.status_code == 409                                      # the context PUT waits for it
        put = await client.put("/api/v1/conversations/c1/pin", json={"pinned": True})
        assert put.status_code == 200
    finally:
        lock.release()
    assert await _listed(client) == {"c1": True}


async def test_a_pinned_quick_question_is_still_left_out_of_the_list(client):
    await _say(client, "c1")
    await _say(client, "q1")
    async with client.db_maker() as db:
        db.add(ConversationContext(id="q1", owner_id="local", kind="quick", no_learning=True))
        await db.commit()
    await client.put("/api/v1/conversations/q1/pin", json={"pinned": True})
    assert await _listed(client) == {"c1": False}


async def test_a_bad_body_or_id_is_refused(client):
    assert (await client.put("/api/v1/conversations/c1/pin", json={"pinned": "yes"})).status_code == 422
    assert (await client.put("/api/v1/conversations/c1/pin", json={})).status_code == 422
    assert (await client.put(f"/api/v1/conversations/{'x' * 101}/pin", json={"pinned": True})).status_code == 422
