"""INB4 (v0.1.64): "done, not seen" in the window's list.

A chat's last reply that came without an error, or a background job done, newer than the conversation's seen mark reads
`done_unseen`. The window marks it seen when it shows the conversation (`POST /conversations/{id}/seen`): a chat goes back to
`idle`, so a seen chat looks as it does today, and a job to `done`. The mark lives in the database (migration 0083), so a restart
keeps it. Phones keep today's values until the Bridge frame says a phone knows `done_unseen` (INB4's phone half, the user's nod).
"""
import sqlalchemy as sa
from sqlalchemy import select

from server.db.migrations import runner
from server.db.migrations.versions import _0083_conversation_seen as m0083
from server.db.models import ArslanMessage, Base, ConversationSeen, Run
from server.services import conversation_seen


async def _add(client, *rows):
    async with client.db_maker() as db:
        db.add_all(rows)
        await db.commit()


async def _window(client) -> dict[str, str]:
    return {row["conversation_id"]: row["state"] for row in (await client.get("/api/v1/conversations")).json()}


async def _phone(client) -> dict[str, str]:
    body = (await client.get("/api/v1/phone/conversations?limit=50")).json()
    return {row["id"]: row["state"] for row in body["conversations"]}


async def test_a_chat_reply_is_done_unseen_until_the_window_shows_it(client):
    await _add(client, ArslanMessage(conversation_id="trip", role="user", content="plan the week"),
               ArslanMessage(conversation_id="trip", role="arslan", content="planned"))
    assert (await _window(client))["trip"] == "done_unseen"
    assert (await client.post("/api/v1/conversations/trip/seen")).status_code == 200
    assert (await _window(client))["trip"] == "idle"                          # a seen chat looks as it does today
    await _add(client, ArslanMessage(conversation_id="trip", role="user", content="and Friday?"),
               ArslanMessage(conversation_id="trip", role="arslan", content="Friday is free"))
    assert (await _window(client))["trip"] == "done_unseen"                   # a newer reply is unseen again


async def test_a_turn_that_failed_or_got_no_reply_is_not_done(client):
    async with client.db_maker() as db:
        run = Run(conversation_id="broke", spawn_id=None, spawn_name="Arslan", user_message="go", status="error",
                  task_tokens=0, kind="host", error_kind="HostError")
        db.add(run)
        await db.flush()
        db.add_all([ArslanMessage(conversation_id="broke", role="user", content="go"),
                    ArslanMessage(conversation_id="broke", role="arslan", content="the model failed", run_id=run.id),
                    ArslanMessage(conversation_id="asked", role="user", content="still waiting")])
        await db.commit()
    states = await _window(client)
    assert (states["broke"], states["asked"]) == ("idle", "idle")


async def test_a_finished_job_is_done_unseen_then_done(client):
    await _add(client, ArslanMessage(conversation_id="task-ab", role="user", content="sort the invoices"),
               ArslanMessage(conversation_id="task-ab", role="arslan", content="sorted", job_outcome="done"))
    assert (await _window(client))["task-ab"] == "done_unseen"
    await client.post("/api/v1/conversations/task-ab/seen")
    assert (await _window(client))["task-ab"] == "done"


async def test_the_seen_mark_is_kept_in_the_database_and_never_moves_back(client):
    await _add(client, ArslanMessage(conversation_id="trip", role="user", content="hi"),
               ArslanMessage(conversation_id="trip", role="arslan", content="hello"))
    body = (await client.post("/api/v1/conversations/trip/seen")).json()
    async with client.db_maker() as db:
        row = await db.get(ConversationSeen, "trip")
        last = await db.scalar(select(sa.func.max(ArslanMessage.id)).where(ArslanMessage.conversation_id == "trip"))
    assert row.seen_message_id == last == body["seen_message_id"]
    async with client.db_maker() as db:                                       # an older mark never lowers it
        await conversation_seen.mark(db, "trip", last - 1)
    async with client.db_maker() as db:
        assert (await db.get(ConversationSeen, "trip")).seen_message_id == last


async def test_phones_keep_todays_values_whatever_the_kind(client):
    await _add(client, ArslanMessage(conversation_id="trip", role="user", content="plan"),
               ArslanMessage(conversation_id="trip", role="arslan", content="planned"),
               ArslanMessage(conversation_id="task-ab", role="arslan", content="sorted", job_outcome="done"),
               ArslanMessage(conversation_id="pocket", role="user", source="phone", content="copy the files"),
               ArslanMessage(conversation_id="pocket", role="arslan", content="copied", job_outcome="done"))
    window, phone = await _window(client), await _phone(client)
    assert (window["trip"], window["task-ab"]) == ("done_unseen", "done_unseen")
    assert (phone["trip"], phone["task-ab"], phone["pocket"]) == ("idle", "done", "done")      # the pocket's job too (#589 F2)


async def test_quick_questions_keep_todays_values_on_the_phone(client):
    from server.db.companion_models import ConversationContext
    await _add(client, ConversationContext(id="q-1", kind="quick"), ConversationContext(id="q-2", kind="quick"),
               ArslanMessage(conversation_id="q-1", role="user", source="phone", content="what time is it?"),
               ArslanMessage(conversation_id="q-1", role="arslan", content="nine"),
               ArslanMessage(conversation_id="q-2", role="arslan", content="sorted", job_outcome="done"))
    body = (await client.get("/api/v1/phone/conversations?limit=50&kind=quick")).json()
    states = {row["id"]: row["state"] for row in body["conversations"]}
    assert (states["q-1"], states["q-2"]) == ("idle", "done")


async def test_scheduled_and_remote_conversations_keep_their_glyphs(client):
    await _add(client, ArslanMessage(conversation_id="scheduled-3", role="arslan", content="today's news"),
               ArslanMessage(conversation_id="pocket", role="user", source="phone", content="hi"),
               ArslanMessage(conversation_id="pocket", role="arslan", content="hello"))
    window = await _window(client)
    assert (window["scheduled-3"], window["pocket"]) == ("idle", "idle")


async def test_marking_a_conversation_that_does_not_exist_is_refused(client):
    assert (await client.post("/api/v1/conversations/nope/seen")).status_code == 404


def test_an_upgrade_starts_with_every_conversation_seen_up_to_its_newest_message(tmp_path):
    # create_all makes the new table before the migrations run, so 0083 must mark what was there (#589 F1): old replies are
    # not news, and a reply after the upgrade still is.
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for cid, role in (("trip", "user"), ("trip", "arslan"), ("task-ab", "arslan")):
            conn.execute(sa.insert(ArslanMessage.__table__).values(conversation_id=cid, role=role, content="x"))
        m0083.upgrade_sync(conn)
        m0083.upgrade_sync(conn)
        rows = dict(conn.execute(sa.text("SELECT conversation_id, seen_message_id FROM conversation_seen")).all())
        newest = dict(conn.execute(sa.text("SELECT conversation_id, MAX(id) FROM arslan_messages GROUP BY conversation_id")).all())
    assert rows == newest


def test_0083_makes_the_table_once_and_is_in_the_boot_chain(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    with engine.begin() as conn:
        m0083.upgrade_sync(conn)
        m0083.upgrade_sync(conn)
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversation_seen)")}
    assert columns == {"conversation_id", "seen_message_id", "seen_at"}
    assert ("0083", m0083.upgrade_sync) in runner.MIGRATIONS
