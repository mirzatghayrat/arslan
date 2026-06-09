"""Feedback rows are persisted with a quality_signal on every submission."""
from __future__ import annotations

import importlib
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, Feedback
from server.db.session import get_session

AUTH = {"Authorization": "Bearer test-token"}


@dataclass
class FeedbackEnv:
    client: AsyncClient
    maker: async_sessionmaker

    async def seed_spawn(self, name: str = "Guru") -> int:
        await self.client.post("/api/v1/_test/seed_spawn", headers=AUTH, json={"name": name})
        spawns = (await self.client.get("/api/v1/spawns", headers=AUTH)).json()
        return spawns[0]["id"]

    async def post_feedback(self, spawn_id: int, body: dict) -> None:
        resp = await self.client.post(
            f"/api/v1/spawns/{spawn_id}/feedback", headers=AUTH, json=body
        )
        assert resp.status_code == 201, resp.text

    def session(self):
        return self.maker()


@pytest_asyncio.fixture
async def feedback_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "test-token")
    monkeypatch.setenv("ARSLAN_TEST_ROUTES", "1")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'app.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_session():
        async with maker() as s:
            yield s

    from server.main import create_app

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield FeedbackEnv(client=c, maker=maker)
    await engine.dispose()


@pytest.mark.parametrize(
    "action,signal",
    [
        ("thumbs_up", 1),
        ("thumbs_down", -1),
        ("redo", -1),
        ("refine", 0),
        ("edit", 0),
    ],
)
async def test_feedback_sets_quality_signal(feedback_env, action, signal):
    spawn_id = await feedback_env.seed_spawn(name="Guru")
    await feedback_env.post_feedback(spawn_id, {"message_id": 5, "user_action": action})
    async with feedback_env.session() as db:
        rows = (
            await db.execute(select(Feedback).where(Feedback.spawn_id == spawn_id))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].quality_signal == signal
    assert rows[0].message_id == 5
