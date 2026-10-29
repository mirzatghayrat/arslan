"""PRJ0 (v0.1.64, user 2026-10-28): three Projects features nobody used are gone.

- "Learn how you advance gates": the shadow streak, the one ask at 10, auto-advance, the
  line after a decline that became a plan rule, and the plan rules themselves
  (project_habits; its table goes in its own PR, migration 0076).
- Rhythm stats: the median days per level ("pace"), its overrides, and the retro's
  "usually N days".
- Stall reminders: the quiet-for-too-long chip on a project card and its "pick it up".

What stays is tested where it lives: proposals and undo (test_project_plan.py), the retro
without them (test_project_retro.py), file activity (test_project_evidence.py).
"""
import importlib.util

import httpx
import pytest
from fastapi import FastAPI

from server import auth
from server.api.companion import router as companion_router
from server.api.projects import router as projects_router
from server.schemas import SettingsIn, SettingsOut
from server.services import project_drafter, project_plan, project_retro, settings_service

AUTH: dict[str, str] = {}


@pytest.fixture
async def api(execution_db, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-prj0-token")
    app = FastAPI()
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(companion_router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-prj0-token"}) as client:
        yield client


def test_the_module_its_helpers_and_the_setting_are_gone():
    assert importlib.util.find_spec("server.services.project_habits") is None
    for name in ("shadow", "shadow_view", "auto_advance_enabled", "add_note", "SHADOW_STREAK_TO_ASK",
                 "ASKED_KEY", "KEPT_KEY"):
        assert not hasattr(project_plan, name), name
    assert not hasattr(project_retro, "keep_rule") and not hasattr(project_retro, "SLOWER_THAN_USUAL")
    assert not hasattr(project_drafter, "plan_rules")
    assert "projects_auto_advance" not in SettingsIn.model_fields
    assert "projects_auto_advance" not in SettingsOut.model_fields
    assert "projects_auto_advance" not in settings_service._PLAIN_KEYS


async def test_the_routes_are_gone(api):
    pid = (await api.post("/api/v1/projects", json={"name": "Sample", "kind": "general"})).json()["id"]
    for method, path, body in (
            ("GET", "/api/v1/project-habits", None),
            ("PUT", "/api/v1/project-habits/rules/r1", {"enabled": False}),
            ("PUT", "/api/v1/project-habits/pace", {"template": "game", "band": "shaping", "days": 4}),
            ("PUT", "/api/v1/project-habits/auto-advance", {"on": True, "answered": "ask"}),
            ("POST", f"/api/v1/projects/{pid}/proposal-notes/e1", {"note": "one more pass"}),
            ("POST", f"/api/v1/projects/{pid}/retro/rules/0/keep", None)):
        response = await api.request(method, path, json=body)
        assert response.status_code in (404, 405), (method, path, response.status_code)


async def test_the_settings_api_no_longer_reports_or_stores_auto_advance(client):
    """A window from before still sends it: a 200, nothing stored, never reported."""
    response = await client.put("/api/v1/settings", json={"projects_auto_advance": "true"}, headers=AUTH)
    assert response.status_code == 200, response.text
    assert "projects_auto_advance" not in response.json()
    assert "projects_auto_advance" not in (await client.get("/api/v1/settings", headers=AUTH)).json()
