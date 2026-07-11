"""S3-M4 Task 3: scheduled-tasks API (CRUD + pause/resume/fire-now + history).

Contract under test (validation delegates to server/services/scheduler.py's
primitives — parse_cron / MIN_INTERVAL_S / MAX_ENABLED / compute_next_due — the
API never re-implements scheduling rules):
  - GET /scheduled-tasks lists tasks with spawn_name (join), schedule display
    fields, last_fired/next_due/paused_reason/consecutive_failures and the latest
    run outcome (per-task latest scheduled_task_run);
  - POST validates: name/prompt non-blank (422), spawn exists (422),
    interval_s >= MIN_INTERVAL_S (422), cron parses (422 carrying the parse_cron
    ValueError message), enabled count < MAX_ENABLED (409); on create the task is
    enabled and next_due_at = compute_next_due(...) is persisted;
  - PUT applies partial updates with the same validations; a schedule change
    recomputes next_due_at, a non-schedule change leaves it untouched;
  - pause is MANUAL: enabled=False + next_due_at=None, paused_reason stays None
    (a non-null reason always means auto-pause); resume re-enables, clears
    paused_reason + consecutive_failures and recomputes next_due FORWARD from now
    — a stale interval task fires ~immediately (DELIBERATE, review S7) — and
    respects the MAX_ENABLED quota;
  - fire-now respects single-flight (in-flight row -> 409 "already running"),
    otherwise dispatches the exact same supervised _fire path the loop uses (202);
  - DELETE removes the task and its runs rows CASCADE via the FK (the fixture
    engine runs PRAGMA foreign_keys=ON exactly like production build_engine);
  - GET /{id}/runs returns execution history newest first, limit 50;
  - everything sits behind router-level require_auth.
"""
from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import server.db.session as db_session
from server.db.models import Base, ScheduledTask, ScheduledTaskRun, Spawn
from server.services import scheduler

AUTH = {"Authorization": "Bearer test-token"}


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "test-token")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "sched.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))

    import server.config as config

    importlib.reload(config)

    # build_engine (NOT a bare create_async_engine): the DELETE-cascade contract
    # relies on PRAGMA foreign_keys=ON, which production sets on every connection.
    engine = db_session.build_engine(f"sqlite+aiosqlite:///{tmp_path / 'sched.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    for t in list(scheduler._tasks):
        t.cancel()
    scheduler._tasks.clear()
    await engine.dispose()


async def _seed_spawn(name: str = "调研员") -> int:
    async with db_session.AsyncSessionLocal() as db:
        spawn = Spawn(name=name, domain_category="general", system_prompt="sp")
        db.add(spawn)
        await db.commit()
        await db.refresh(spawn)
        return spawn.id


async def _seed_task(spawn_id: int, **overrides) -> int:
    fields = dict(name="早报", prompt="做每日早报", spawn_id=spawn_id,
                  schedule_kind="interval", interval_s=3600, enabled=True,
                  consecutive_failures=0)
    fields.update(overrides)
    async with db_session.AsyncSessionLocal() as db:
        task = ScheduledTask(**fields)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task.id


async def _seed_run(task_id: int, **overrides) -> int:
    fields = dict(task_id=task_id, started_at=datetime.utcnow())
    fields.update(overrides)
    async with db_session.AsyncSessionLocal() as db:
        row = ScheduledTaskRun(**fields)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _get_task(task_id: int) -> ScheduledTask | None:
    async with db_session.AsyncSessionLocal() as db:
        return await db.get(ScheduledTask, task_id)


def _body(spawn_id: int, **overrides) -> dict:
    body = {"name": "早报", "prompt": "做每日早报", "spawn_id": spawn_id,
            "schedule_kind": "interval", "interval_s": 3600}
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

async def test_scheduled_tasks_requires_auth(client):
    assert (await client.get("/api/v1/scheduled-tasks")).status_code in (401, 403)
    r = await client.post("/api/v1/scheduled-tasks", json=_body(1))
    assert r.status_code in (401, 403)
    r = await client.post("/api/v1/scheduled-tasks/1/fire-now")
    assert r.status_code in (401, 403)
    assert (await client.get("/api/v1/scheduled-tasks/1/runs")).status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /scheduled-tasks + GET /scheduled-tasks round trip
# ---------------------------------------------------------------------------

async def test_create_interval_round_trip(client):
    spawn_id = await _seed_spawn()
    before = datetime.utcnow()
    r = await client.post("/api/v1/scheduled-tasks", json=_body(spawn_id), headers=AUTH)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "早报"
    assert body["prompt"] == "做每日早报"
    assert body["spawn_id"] == spawn_id
    assert body["spawn_name"] == "调研员"
    assert body["schedule_kind"] == "interval"
    assert body["interval_s"] == 3600
    assert body["enabled"] is True
    assert body["consecutive_failures"] == 0
    assert body["paused_reason"] is None
    assert body["last_outcome"] is None
    # next_due_at persisted via compute_next_due: no last_fired -> ~now+3600
    due = datetime.fromisoformat(body["next_due_at"])
    assert timedelta(seconds=3500) < (due - before) < timedelta(seconds=3700)
    row = await _get_task(body["id"])
    assert row is not None and row.next_due_at is not None

    r = await client.get("/api/v1/scheduled-tasks", headers=AUTH)
    assert r.status_code == 200
    listed = {t["id"]: t for t in r.json()}
    assert listed[body["id"]]["spawn_name"] == "调研员"
    assert listed[body["id"]]["next_due_at"] == body["next_due_at"]


async def test_create_cron_persists_next_due(client):
    spawn_id = await _seed_spawn()
    r = await client.post("/api/v1/scheduled-tasks",
                          json=_body(spawn_id, schedule_kind="cron", cron="0 9 * * *",
                                     interval_s=None),
                          headers=AUTH)
    assert r.status_code == 201
    body = r.json()
    assert body["cron"] == "0 9 * * *"
    assert body["next_due_at"] is not None


async def test_list_includes_latest_outcome(client):
    spawn_id = await _seed_spawn()
    tid = await _seed_task(spawn_id)
    now = datetime.utcnow()
    await _seed_run(tid, outcome="error", reason="boom",
                    finished_at=now - timedelta(hours=2),
                    started_at=now - timedelta(hours=2))
    await _seed_run(tid, outcome="ok", finished_at=now, started_at=now)
    r = await client.get("/api/v1/scheduled-tasks", headers=AUTH)
    task = {t["id"]: t for t in r.json()}[tid]
    assert task["last_outcome"] == "ok"


# ---------------------------------------------------------------------------
# POST validation branches
# ---------------------------------------------------------------------------

async def test_create_rejects_blank_name_and_prompt(client):
    spawn_id = await _seed_spawn()
    r = await client.post("/api/v1/scheduled-tasks", json=_body(spawn_id, name=""),
                          headers=AUTH)
    assert r.status_code == 422
    r = await client.post("/api/v1/scheduled-tasks", json=_body(spawn_id, prompt="   "),
                          headers=AUTH)
    assert r.status_code == 422


async def test_create_rejects_short_interval(client):
    spawn_id = await _seed_spawn()
    r = await client.post("/api/v1/scheduled-tasks", json=_body(spawn_id, interval_s=899),
                          headers=AUTH)
    assert r.status_code == 422
    assert str(scheduler.MIN_INTERVAL_S) in r.text
    # interval kind without interval_s at all is equally invalid
    r = await client.post("/api/v1/scheduled-tasks",
                          json=_body(spawn_id, interval_s=None), headers=AUTH)
    assert r.status_code == 422


async def test_create_rejects_bad_cron_with_parse_message(client):
    spawn_id = await _seed_spawn()
    r = await client.post("/api/v1/scheduled-tasks",
                          json=_body(spawn_id, schedule_kind="cron", cron="61 * * * *",
                                     interval_s=None),
                          headers=AUTH)
    assert r.status_code == 422
    assert "out of range" in r.text          # parse_cron's ValueError message surfaces
    r = await client.post("/api/v1/scheduled-tasks",
                          json=_body(spawn_id, schedule_kind="cron", cron="* * *",
                                     interval_s=None),
                          headers=AUTH)
    assert r.status_code == 422
    assert "5 fields" in r.text
    # cron kind without a cron expression is invalid too
    r = await client.post("/api/v1/scheduled-tasks",
                          json=_body(spawn_id, schedule_kind="cron", interval_s=None),
                          headers=AUTH)
    assert r.status_code == 422


async def test_create_rejects_missing_spawn(client):
    r = await client.post("/api/v1/scheduled-tasks", json=_body(9999), headers=AUTH)
    assert r.status_code == 422
    assert "spawn" in r.text


async def test_create_caps_enabled_tasks_and_resume_respects_quota(client):
    spawn_id = await _seed_spawn()
    for i in range(scheduler.MAX_ENABLED):
        await _seed_task(spawn_id, name=f"t{i}")
    r = await client.post("/api/v1/scheduled-tasks",
                          json=_body(spawn_id, name="第11个"), headers=AUTH)
    assert r.status_code == 409
    # resume on a disabled task while the quota is full is the same 409
    disabled = await _seed_task(spawn_id, name="停用", enabled=False)
    r = await client.post(f"/api/v1/scheduled-tasks/{disabled}/resume", headers=AUTH)
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# PUT /scheduled-tasks/{id}
# ---------------------------------------------------------------------------

async def test_put_non_schedule_change_keeps_next_due(client):
    spawn_id = await _seed_spawn()
    created = (await client.post("/api/v1/scheduled-tasks", json=_body(spawn_id),
                                 headers=AUTH)).json()
    r = await client.put(f"/api/v1/scheduled-tasks/{created['id']}",
                         json={"name": "晚报", "prompt": "做每日晚报"}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "晚报"
    assert body["prompt"] == "做每日晚报"
    assert body["next_due_at"] == created["next_due_at"]   # schedule untouched


async def test_put_schedule_change_recomputes_next_due(client):
    spawn_id = await _seed_spawn()
    created = (await client.post("/api/v1/scheduled-tasks", json=_body(spawn_id),
                                 headers=AUTH)).json()
    before = datetime.utcnow()
    r = await client.put(f"/api/v1/scheduled-tasks/{created['id']}",
                         json={"interval_s": 7200}, headers=AUTH)
    assert r.status_code == 200
    due = datetime.fromisoformat(r.json()["next_due_at"])
    assert timedelta(seconds=7100) < (due - before) < timedelta(seconds=7300)
    # switch to cron: cron validated + next_due recomputed
    r = await client.put(f"/api/v1/scheduled-tasks/{created['id']}",
                         json={"schedule_kind": "cron", "cron": "0 9 * * *"},
                         headers=AUTH)
    assert r.status_code == 200
    assert r.json()["schedule_kind"] == "cron"
    assert r.json()["next_due_at"] is not None


async def test_put_validation_and_404(client):
    spawn_id = await _seed_spawn()
    tid = await _seed_task(spawn_id)
    r = await client.put(f"/api/v1/scheduled-tasks/{tid}", json={"interval_s": 10},
                         headers=AUTH)
    assert r.status_code == 422
    r = await client.put(f"/api/v1/scheduled-tasks/{tid}",
                         json={"schedule_kind": "cron", "cron": "99 * * * *"},
                         headers=AUTH)
    assert r.status_code == 422
    assert "out of range" in r.text
    r = await client.put(f"/api/v1/scheduled-tasks/{tid}", json={"name": "  "},
                         headers=AUTH)
    assert r.status_code == 422
    r = await client.put(f"/api/v1/scheduled-tasks/{tid}", json={"spawn_id": 4242},
                         headers=AUTH)
    assert r.status_code == 422
    r = await client.put("/api/v1/scheduled-tasks/9999", json={"name": "x"}, headers=AUTH)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# pause / resume
# ---------------------------------------------------------------------------

async def test_manual_pause_leaves_reason_none(client):
    spawn_id = await _seed_spawn()
    created = (await client.post("/api/v1/scheduled-tasks", json=_body(spawn_id),
                                 headers=AUTH)).json()
    r = await client.post(f"/api/v1/scheduled-tasks/{created['id']}/pause", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["paused_reason"] is None      # manual pause NEVER writes a reason
    assert body["next_due_at"] is None
    row = await _get_task(created["id"])
    assert row.enabled is False and row.paused_reason is None and row.next_due_at is None


async def test_resume_clears_failures_and_fires_soon(client):
    spawn_id = await _seed_spawn()
    # An auto-paused, long-stale interval task: resume must clear the pause
    # bookkeeping AND recompute next_due forward from now — which for a stale
    # interval task means ~immediately (DELIBERATE, review S7).
    tid = await _seed_task(
        spawn_id, enabled=False, paused_reason="连续失败 3 次:boom",
        consecutive_failures=3, last_fired_at=datetime.utcnow() - timedelta(days=10),
        next_due_at=None)
    before = datetime.utcnow()
    r = await client.post(f"/api/v1/scheduled-tasks/{tid}/resume", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["paused_reason"] is None
    assert body["consecutive_failures"] == 0
    due = datetime.fromisoformat(body["next_due_at"])
    assert due <= before + timedelta(seconds=60)   # stale task fires on the next tick


async def test_pause_resume_404(client):
    assert (await client.post("/api/v1/scheduled-tasks/9999/pause",
                              headers=AUTH)).status_code == 404
    assert (await client.post("/api/v1/scheduled-tasks/9999/resume",
                              headers=AUTH)).status_code == 404


# ---------------------------------------------------------------------------
# fire-now
# ---------------------------------------------------------------------------

async def test_fire_now_dispatches_supervised_fire(client, monkeypatch):
    spawn_id = await _seed_spawn()
    tid = await _seed_task(spawn_id)
    fired: list[int] = []

    async def fake_fire(task):
        fired.append(task.id)

    monkeypatch.setattr(scheduler, "_fire", fake_fire)
    r = await client.post(f"/api/v1/scheduled-tasks/{tid}/fire-now", headers=AUTH)
    assert r.status_code == 202
    await asyncio.sleep(0.01)                 # let the supervised task run
    assert fired == [tid]


async def test_fire_now_single_flight_409(client, monkeypatch):
    spawn_id = await _seed_spawn()
    tid = await _seed_task(spawn_id)
    await _seed_run(tid)                      # in-flight: outcome IS NULL
    fired: list[int] = []

    async def fake_fire(task):
        fired.append(task.id)

    monkeypatch.setattr(scheduler, "_fire", fake_fire)
    r = await client.post(f"/api/v1/scheduled-tasks/{tid}/fire-now", headers=AUTH)
    assert r.status_code == 409
    assert "already running" in r.text
    await asyncio.sleep(0.01)
    assert fired == []


async def test_fire_now_missing_task_404(client):
    r = await client.post("/api/v1/scheduled-tasks/9999/fire-now", headers=AUTH)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE cascades runs rows
# ---------------------------------------------------------------------------

async def test_delete_cascades_runs_rows(client):
    spawn_id = await _seed_spawn()
    tid = await _seed_task(spawn_id)
    now = datetime.utcnow()
    await _seed_run(tid, outcome="ok", finished_at=now)
    await _seed_run(tid, outcome="error", reason="boom", finished_at=now)
    r = await client.delete(f"/api/v1/scheduled-tasks/{tid}", headers=AUTH)
    assert r.status_code == 200
    assert await _get_task(tid) is None
    async with db_session.AsyncSessionLocal() as db:
        left = (await db.execute(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == tid)
        )).scalars().all()
    assert left == []                         # FK ON DELETE CASCADE (pragma ON)
    assert (await client.get(f"/api/v1/scheduled-tasks/{tid}/runs",
                             headers=AUTH)).status_code == 404
    assert (await client.delete(f"/api/v1/scheduled-tasks/{tid}",
                                headers=AUTH)).status_code == 404


# ---------------------------------------------------------------------------
# GET /scheduled-tasks/{id}/runs
# ---------------------------------------------------------------------------

async def test_runs_history_newest_first_limit_50(client):
    spawn_id = await _seed_spawn()
    tid = await _seed_task(spawn_id)
    now = datetime.utcnow()
    run_ids = []
    async with db_session.AsyncSessionLocal() as db:
        for i in range(55):
            db.add(ScheduledTaskRun(task_id=tid, started_at=now + timedelta(seconds=i),
                                    finished_at=now + timedelta(seconds=i + 1),
                                    outcome="ok" if i % 2 == 0 else "error",
                                    run_id=1000 + i, reason=f"r{i}"))
        await db.commit()
        run_ids = [r for (r,) in (await db.execute(
            select(ScheduledTaskRun.id).where(ScheduledTaskRun.task_id == tid)
            .order_by(ScheduledTaskRun.id.desc())))]
    r = await client.get(f"/api/v1/scheduled-tasks/{tid}/runs", headers=AUTH)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 50                    # capped
    assert [x["id"] for x in rows] == run_ids[:50]   # newest first
    newest = rows[0]
    assert newest["run_id"] == 1054
    assert newest["reason"] == "r54"
    assert newest["outcome"] == "ok"
    assert newest["started_at"] is not None
    assert newest["finished_at"] is not None
