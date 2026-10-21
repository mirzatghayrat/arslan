"""Dispatcher: clean context isolation + dual persistence (display vs memory)."""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import ArslanMessage, Base, ChatMessage, Spawn
from tests.server.conftest import boot_schema


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with m() as s:
        s.add(
            Spawn(
                id=7,
                name="beauty-guru",
                domain_category="content-creator",
                capabilities=["content-generation"],
                system_prompt="You are a beauty expert.",
            )
        )
        await s.commit()

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest_asyncio.fixture
async def maker_v2(tmp_path, monkeypatch):
    """The same spawn on memory v2, as a launch leaves it, with one "about you" entry (in view
    whatever the task brief is). C2a: `maker` stays on v1 for the evolution-rules test, whose
    suffix dispatcher appends only without memory v2 (C2a-2 deletes that branch)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d2.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(boot_schema)
    async with m() as s:
        s.add(Spawn(id=7, name="beauty-guru", domain_category="content-creator",
                    capabilities=["content-generation"], system_prompt="You are a beauty expert."))
        await s.commit()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
    from server.services.memory_repository import repository
    async with repository() as repo:
        await repo.create(MemoryWrite(content="prefers data-driven tone", kind="preference",
                                      scope=MemoryScope(kind="global"), core="about_you"),
                          MemoryActor(origin="user"))
    return m


@pytest.mark.asyncio
async def test_dispatch_isolation_and_persistence(maker_v2, monkeypatch):
    from server.orchestrator import dispatcher

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            captured["system"] = system
            captured["user"] = user
            captured["history"] = history
            for piece in ["Post 1. ", "Post 2."]:
                yield piece

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())

    from server.services import personal_context as pc
    chunks = []
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", model_is_local=True)):  # a turn's memory scope
        result = await dispatcher.dispatch(
            "main", spawn_id=7, task_brief="draft 2 posts", on_chunk=lambda c: chunks.append(c)
        )

    # streamed the full output
    assert "".join(chunks) == "Post 1. Post 2."
    assert result["full_output"] == "Post 1. Post 2."
    assert result["spawn_name"] == "beauty-guru"

    # clean context: the user side is the task_brief; facts injected into system; NO Arslan thread
    assert captured["user"] == "draft 2 posts"
    assert "data-driven tone" in captured["system"]
    assert "beauty expert" in captured["system"]

    async with db_session.AsyncSessionLocal() as s:
        cms = (await s.execute(select(ChatMessage).order_by(ChatMessage.id))).scalars().all()
        ams = (await s.execute(select(ArslanMessage))).scalars().all()

    # spawn memory: task_brief (user) + full output (assistant)
    assert [c.role for c in cms] == ["user", "assistant"]
    assert cms[0].content == "draft 2 posts"
    assert cms[1].content == "Post 1. Post 2."
    assert all(c.spawn_id == 7 for c in cms)

    # arslan memory row: content = 1-line summary, display_content = full output
    assert len(ams) == 1
    assert ams[0].role == "spawn_summary"
    assert ams[0].display_content == "Post 1. Post 2."
    assert "beauty-guru" in ams[0].content and "Post 1. Post 2." not in ams[0].content


@pytest.mark.asyncio
async def test_dispatch_returns_assistant_message_id(maker, monkeypatch):
    from server.orchestrator import dispatcher

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            yield "done"

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())

    out = await dispatcher.dispatch("main", spawn_id=7, task_brief="do X")
    assert "assistant_message_id" in out and isinstance(out["assistant_message_id"], int)
    assert "summary_message_id" in out
    # the assistant id must point at the chat_messages assistant row, not the arslan summary row
    assert out["assistant_message_id"] != out["summary_message_id"]


@pytest.mark.asyncio
async def test_dispatch_system_forbids_fabrication(maker, monkeypatch):
    from server.orchestrator import dispatcher

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            captured["system"] = system
            yield "ok"

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())

    await dispatcher.dispatch("main", spawn_id=7, task_brief="do X")

    s = captured["system"].lower()
    assert "do not invent" in s or "fabricat" in s


@pytest.mark.asyncio
async def test_dispatch_refinement_includes_prior_output(maker, monkeypatch):
    from server.orchestrator import dispatcher

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            captured["user"] = user
            yield "revised"

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())

    await dispatcher.dispatch(
        "main",
        spawn_id=7,
        task_brief="write 5 tips",
        prior_output="1. a\n2. b",
        instruction="make point 2 livelier",
    )
    assert "make point 2 livelier" in captured["user"]
    assert "1. a" in captured["user"]


