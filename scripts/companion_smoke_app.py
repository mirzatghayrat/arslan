"""Offline UI harness: real app/migrations/APIs, synthetic model and private temp data.

Never point this at a user's data. This module refuses non-temporary directories.
It is not part of production startup or release packaging.
"""
from contextlib import asynccontextmanager
from pathlib import Path
import os
import tempfile
import httpx

data = Path(os.environ.get("ARSLAN_DATA_DIR", "")).resolve()
if not data.is_relative_to(Path(tempfile.gettempdir()).resolve()) or "companion-ui" not in data.name:
    raise RuntimeError("The companion UI harness requires its own companion-ui temporary data directory")

from scripts.smoke_app import app  # noqa: E402
from arslan.llm.locality import loopback_endpoint  # noqa: E402
from server.services import llm_test  # noqa: E402


async def synthetic_connection(*args, **kwargs):
    return {"ok": True, "error": None, "latency_ms": 0}


llm_test.test_connection = synthetic_connection
_original_send = httpx.AsyncClient.send


async def local_only_send(self, request, *args, **kwargs):
    if not loopback_endpoint(str(request.url)):
        raise RuntimeError("External requests are disabled in the offline UI harness")
    return await _original_send(self, request, *args, **kwargs)


httpx.AsyncClient.send = local_only_send

original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    async with original_lifespan(application):
        from sqlalchemy import select
        from server import crypto
        from server.db import session
        from server.db.models import Project, ProviderConfig
        from server.services.memory_activation import activate_sync
        from server.services.memory_repository import repository
        from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
        async with session.engine.begin() as connection:
            await connection.run_sync(activate_sync)
        async with session.AsyncSessionLocal() as db:
            if await db.get(Project, "sample-project") is None:
                db.add(Project(id="sample-project", name="Arslan 桌面应用", kind="software",
                               summary="梳理工作目标、应用资料与发布检查。所有示例均为合成数据。"))
            if not await db.scalar(select(ProviderConfig.id)):
                db.add(ProviderConfig(label="Offline synthetic adapter", provider="openai", model="offline-test",
                                      api_key=crypto.encrypt("synthetic-not-a-real-key"), base_url="", is_primary=True))
            await db.commit()
        async with repository() as repo:
            await repo.create(MemoryWrite(content="报告先给结论，再列依据。", scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
            await repo.create(MemoryWrite(content="这个项目的界面偏好温暖的橙色点缀。", scope=MemoryScope(kind="project", id="sample-project")),
                              MemoryActor(origin="extractor", project_id="sample-project"))
        yield


app.router.lifespan_context = lifespan
