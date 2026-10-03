"""0.1.52 S3: conversation_search — original words with date and link; temporary and
no-memory conversations never searched; the index follows edits and deletes."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, text, update

from server.db.companion_models import ConversationContext
from server.db.models import ArslanMessage
from server.registry.memory_executors import ConversationSearchExecutor
from server.services import conversation_search, personal_context as pc


@pytest.fixture
async def history(execution_db):
    from server.db.migrations.versions._0059_messages_fts import upgrade_sync
    old = datetime.utcnow() - timedelta(days=30)
    async with execution_db() as db:
        db.add_all([
            ArslanMessage(conversation_id="c-old", role="user", content="我的周报每周五下午交给王经理", timestamp=old),
            ArslanMessage(conversation_id="c-old", role="arslan", content="好的，记下了周报的时间。", timestamp=old),
            ArslanMessage(conversation_id="c-new", role="user", content="Call the landlord about the heater on Monday",
                          timestamp=datetime.utcnow() - timedelta(days=1)),
            ArslanMessage(conversation_id="c-tmp", role="user", content="周报 secret temporary chat"),
            ArslanMessage(conversation_id="c-off", role="user", content="周报 in a no-memory chat"),
            ConversationContext(id="c-tmp", temporary=True, no_memory=True, no_learning=True),
            ConversationContext(id="c-off", no_memory=True),
        ])
        await db.commit()
    async with execution_db.kw["bind"].begin() as conn:
        await conn.run_sync(upgrade_sync)                      # builds the index over existing rows
    return execution_db


async def test_finds_the_original_words_with_date_and_link(history):
    out = await conversation_search.search("周报每周五")
    assert len(out) == 1 and out[0]["conversation_id"] == "c-old" and out[0]["who"] == "you"
    assert "周报每周五下午" in out[0]["snippet"] and out[0]["link"] == "#conversation=c-old"
    assert out[0]["when"] == (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")[:10] + out[0]["when"][10:]
    assert out[0]["conversation"] == "我的周报每周五下午交给王经理"[:60]


async def test_temporary_and_no_memory_conversations_are_never_searched(history):
    found = {r["conversation_id"] for r in await conversation_search.search("周报")}
    assert found == {"c-old"}


async def test_time_range_and_current_conversation(history):
    recent = await conversation_search.search("landlord", since=datetime.utcnow() - timedelta(days=7))
    assert [r["conversation_id"] for r in recent] == ["c-new"]
    assert await conversation_search.search("landlord", until=datetime.utcnow() - timedelta(days=7)) == []
    assert await conversation_search.search("landlord", exclude_conversation="c-new") == []
    assert await conversation_search.search("周报", since=datetime.utcnow() - timedelta(days=7)) == []   # 30 days old
    assert len(await conversation_search.search("周报", since=datetime.utcnow() - timedelta(days=40))) == 2


async def test_the_index_follows_new_edited_and_deleted_messages(history):
    async with history() as db:
        db.add(ArslanMessage(conversation_id="c-new", role="user", content="新加的提醒：交水电费"))
        await db.commit()
    assert len(await conversation_search.search("交水电费")) == 1
    async with history() as db:
        await db.execute(update(ArslanMessage).where(ArslanMessage.content.like("%交水电费%"))
                         .values(content="改成：交燃气费"))
        await db.commit()
    assert await conversation_search.search("交水电费") == [] and len(await conversation_search.search("交燃气费")) == 1
    async with history() as db:
        await db.execute(delete(ArslanMessage).where(ArslanMessage.content.like("%燃气费%")))
        await db.commit()
    assert await conversation_search.search("交燃气费") == []
    async with history() as db:      # FTS really used: the match goes through the index table
        hits = (await db.execute(text("SELECT count(*) FROM arslan_messages_fts WHERE arslan_messages_fts MATCH :q"),
                                 {"q": '"landlord"'})).scalar()
    assert hits == 1


async def test_short_queries_and_a_missing_index_fall_back_to_like(execution_db):
    async with execution_db() as db:
        db.add(ArslanMessage(conversation_id="c1", role="user", content="去趟银行"))
        await db.commit()
    assert [r["snippet"] for r in await conversation_search.search("银行")] == ["去趟银行"]   # 2 chars, no index


async def test_the_tool_follows_the_memory_permissions(history):
    ex = ConversationSearchExecutor()
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c-new", no_memory=True)):
        assert (await ex.execute({"query": "周报"}))["ok"] is False
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c-new", model_is_local=False)):
        assert "turned off" in (await ex.execute({"query": "周报"}))["error"]
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c-new", model_is_local=False,
                                      cloud_memory_default=True)):
        out = await ex.execute({"query": "周报", "since": "2000-01-01"})
    assert out["ok"] is True and out["count"] == 2 and "external" not in out     # results stay untrusted data
    assert {r["who"] for r in out["results"]} == {"you", "Arslan"}
    assert {r["conversation_id"] for r in out["results"]} == {"c-old"}
    assert (await ex.execute({"query": " "}))["ok"] is False
