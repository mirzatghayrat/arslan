"""0.1.56 P6: the retro at Done — counted facts, one model call on request, rules kept as habits."""
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from server import auth
from server.api.companion import router as companion_router
from server.api.projects import router as projects_router
from server.services import project_drafter, project_retro


@pytest.fixture
async def api(execution_db, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-retro-token")
    app = FastAPI()
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(companion_router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-retro-token"}) as client:
        yield client


LEVELS = [{"name": "Shape", "band": "shaping", "checkpoints": [{"text": "Sketch"}, {"text": "Mood"}]},
          {"name": "Build", "band": "doing", "checkpoints": [{"text": "Core"}]},
          {"name": "Ship", "band": "done", "checkpoints": []}]


class _Adapter:
    def __init__(self, content=None, error=None):
        self.content, self.error, self.calls = content, error, []

    async def chat(self, *, system, user):
        self.calls.append((system, user))
        if self.error:
            raise self.error

        class R:
            content = self.content
        return R()


async def _done_project(api, execution_db, *, name="Sample game") -> str:
    from server.db.models import ProjectLevel
    pid = (await api.post("/api/v1/projects", json={"name": name, "kind": "general", "template": "game",
                                                   "finish_line": "On the store"})).json()["id"]
    await api.put(f"/api/v1/projects/{pid}/plan", json={"expected_version": 0, "levels": LEVELS})
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    cut = [{**lv, "checkpoints": lv["checkpoints"][:1]} for lv in plan["levels"]]
    await api.put(f"/api/v1/projects/{pid}/plan", json={"expected_version": plan["version"], "levels": cut})
    async with execution_db() as db:
        rows = (await db.execute(select(ProjectLevel).where(ProjectLevel.project_id == pid)
                                 .order_by(ProjectLevel.position))).scalars().all()
        start = datetime(2026, 1, 1)
        for row, days in zip(rows, (10, 3)):
            row.state, row.started_at, row.cleared_at = "cleared", start, start + timedelta(days=days)
            start += timedelta(days=days)
        await db.commit()
    await api.put("/api/v1/project-habits/pace", json={"template": "game", "band": "shaping", "days": 4})
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "done"})
    return pid


async def test_the_retro_is_only_for_a_done_project(api, execution_db, monkeypatch):
    adapter = _Adapter('{"summary": "x", "rules": []}')
    monkeypatch.setattr(project_retro, "_get_adapter", lambda: adapter)
    pid = (await api.post("/api/v1/projects", json={"name": "Open", "kind": "general"})).json()["id"]
    response = await api.post(f"/api/v1/projects/{pid}/retro", json={})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "not_done"
    assert adapter.calls == [] and (await api.get(f"/api/v1/projects/{pid}/retro")).json() is None


async def test_one_call_writes_it_from_counted_facts(api, execution_db, monkeypatch):
    adapter = _Adapter('{"summary": "Shaping took 10 days against your usual 4.", '
                       '"rules": ["Time-box shaping to a week", "Cut scope before building", "Third", "Fourth"]}')
    monkeypatch.setattr(project_retro, "_get_adapter", lambda: adapter)
    pid = await _done_project(api, execution_db)
    retro = (await api.post(f"/api/v1/projects/{pid}/retro", json={"lang": "zh"})).json()
    assert len(adapter.calls) == 1
    system, user = adapter.calls[0]
    assert "Simplified Chinese" in system
    facts = retro["facts"]
    assert facts["slower"] == ["Shape"] and facts["levels"][0] == {
        "level": "Shape", "band": "shaping", "days": 10.0, "usual": 4.0, "slower": True}
    assert facts["levels"][1]["usual"] is None and facts["levels"][1]["slower"] is False
    assert facts["plan_changes"] == 1 and facts["cut_checkpoints"] == 1
    assert '"slower": ["Shape"]' in user
    assert retro["source"] == "model" and retro["summary"].startswith("Shaping took 10 days")
    assert [r["text"] for r in retro["rules"]] == ["Time-box shaping to a week", "Cut scope before building", "Third"]
    assert (await api.get(f"/api/v1/projects/{pid}/retro")).json()["id"] == retro["id"]
    again = (await api.post(f"/api/v1/projects/{pid}/retro", json={})).json()   # asking again replaces it
    assert again["id"] != retro["id"] and (await api.get(f"/api/v1/projects/{pid}/retro")).json()["id"] == again["id"]
    from server.db.models import ProjectEvent
    async with execution_db() as db:
        kinds = (await db.execute(select(ProjectEvent.kind).where(ProjectEvent.project_id == pid))).scalars().all()
    assert kinds.count("retro") == 1


@pytest.mark.parametrize("adapter", [_Adapter(error=RuntimeError("no model")), _Adapter("not json"),
                                     _Adapter('{"rules": ["only rules"]}')])
async def test_without_a_usable_reply_the_retro_is_the_facts(api, execution_db, monkeypatch, adapter):
    monkeypatch.setattr(project_retro, "_get_adapter", lambda: adapter)
    pid = await _done_project(api, execution_db)
    retro = (await api.post(f"/api/v1/projects/{pid}/retro", json={})).json()
    assert retro["source"] == "facts" and retro["summary"] is None and retro["rules"] == []
    assert retro["facts"]["slower"] == ["Shape"]


async def test_a_kept_rule_becomes_a_plan_rule_once(api, execution_db, monkeypatch):
    monkeypatch.setattr(project_retro, "_get_adapter",
                        lambda: _Adapter('{"summary": "s", "rules": ["Time-box shaping to a week", "Other"]}'))
    pid = await _done_project(api, execution_db, name="Tidepool")
    await api.post(f"/api/v1/projects/{pid}/retro", json={})
    kept = (await api.post(f"/api/v1/projects/{pid}/retro/rules/0/keep")).json()
    assert [r["kept"] for r in kept["rules"]] == [True, False]
    await api.post(f"/api/v1/projects/{pid}/retro/rules/0/keep")
    rules = (await api.get("/api/v1/project-habits")).json()["rules"]
    retro_rules = [r for r in rules if r["value"].get("code") == "retro"]
    assert [(r["text"], r["sources"]) for r in retro_rules] == [("Time-box shaping to a week", ["Tidepool"])]
    assert "Time-box shaping to a week" in await project_drafter.plan_rules("game")
    assert (await api.post(f"/api/v1/projects/{pid}/retro/rules/5/keep")).status_code == 404
