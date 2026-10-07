"""0.1.55 §13: memory usage counted from turn receipts, and the Memory page's stats."""
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server import auth
from server.api.companion import router
from server.services.memory_repository import repository

USER = MemoryActor(origin="user")
GLOBAL = MemoryScope(kind="global")


@pytest.fixture
async def api(execution_db, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-stats-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-stats-token"}) as client:
        yield client


async def _receipt(db, identity, used, *, conversation="c", owner="local", age=timedelta(hours=1)):
    from server.db.models import ContextReceiptRecord
    db.add(ContextReceiptRecord(id=identity, owner_id=owner, conversation_id=conversation, task_id="t",
                                run_id="r", created_at=datetime.utcnow() - age, receipt={"used": used}))


def _mem(entry, revision=1):
    return {"id": entry["id"], "kind": "memory", "revision": revision}


async def test_list_counts_turns_that_carried_each_entry_this_week(api, execution_db):
    async with repository() as repo:
        a = await repo.create(MemoryWrite(content="Prefers short replies", scope=GLOBAL), USER)
        b = await repo.create(MemoryWrite(content="Uses metric units", scope=GLOBAL), USER)
    async with execution_db() as db:
        # Same entry named twice in one turn (core + relevant) is still one turn.
        await _receipt(db, "r1", [_mem(a), _mem(a)], age=timedelta(hours=3))
        await _receipt(db, "r2", [_mem(a)], conversation="c2", age=timedelta(hours=2))
        await _receipt(db, "r3", [_mem(a)], age=timedelta(minutes=5))
        await _receipt(db, "old", [_mem(a), _mem(b)], age=timedelta(days=10))      # outside the week
        await _receipt(db, "foreign", [_mem(b)], owner="other")                      # someone else's turn
        await _receipt(db, "material", [{"id": b["id"], "kind": "material"}])       # not a memory ref
        await db.commit()
    rows = {row["id"]: row for row in (await api.get("/api/v1/memory/entries")).json()}
    assert rows[a["id"]]["uses_this_week"] == 3
    assert rows[b["id"]]["uses_this_week"] == 0
    assert rows[b["id"]]["last_used_at"] is None
    newest = datetime.fromisoformat(rows[a["id"]]["last_used_at"].rstrip("Z"))
    assert datetime.utcnow() - newest < timedelta(minutes=10)   # the 5-minute-old turn, not the 3-hour one


async def test_stats_totals_edits_and_core_budgets(api, execution_db):
    async with repository() as repo:
        core = await repo.create(MemoryWrite(content="Lives by the sea", kind="preference", core="about_you",
                                             scope=GLOBAL), USER)
        plain = await repo.create(MemoryWrite(content="Likes tables", scope=GLOBAL), USER)
        await repo.revise(plain["id"], 1, MemoryWrite(content="Likes tables with totals", scope=GLOBAL), USER)
        # Pausing and resuming are status changes, not edits of what was remembered.
        await repo.set_status(plain["id"], 2, "paused", USER)
        await repo.set_status(plain["id"], 3, "active", USER)
    async with execution_db() as db:
        await _receipt(db, "r1", [_mem(core)], conversation="c1")
        await _receipt(db, "r2", [_mem(core), _mem(plain, 2)], conversation="c2")
        await _receipt(db, "r3", [], conversation="c3")                 # a turn with no memory
        await db.commit()
    stats = (await api.get("/api/v1/memory/stats")).json()
    assert stats["days"] == 7
    assert stats["retrievals"] == 2 and stats["conversations"] == 2
    assert stats["new_entries"] == 2
    assert stats["user_edits"] == 1
    about = stats["core"]["about_you"]
    assert about == {"used": len("Lives by the sea"), "cap": 1500, "entries": 1, "left_out": 0}
    assert stats["core"]["notes"]["entries"] == 0 and stats["core"]["notes"]["cap"] == 2500
    assert stats["remember_in_conversations"] is True
    assert stats["materials"] == {"count": 0, "latest": None}
    assert stats["notes"]["count"] == 0


async def test_core_budget_reports_what_did_not_fit(api):
    async with repository() as repo:
        for index in range(3):
            await repo.create(MemoryWrite(content=f"{index} " + "x" * 700, kind="preference", core="about_you",
                                          scope=GLOBAL), USER)
    about = (await api.get("/api/v1/memory/stats")).json()["core"]["about_you"]
    assert about["entries"] == 2 and about["left_out"] == 1
    assert about["used"] <= about["cap"]


async def test_stats_window_and_auth(api):
    assert (await api.get("/api/v1/memory/stats?days=0")).status_code == 422
    assert (await api.get("/api/v1/memory/stats?days=91")).status_code == 422
    assert (await api.get("/api/v1/memory/stats", headers={"Authorization": "Bearer wrong"})).status_code == 401
