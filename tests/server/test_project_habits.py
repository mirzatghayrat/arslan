"""0.1.56 P5: shadow mode (ask at 10, offer off after 2 undos), habits (plan rules, pace), stalled."""
import os
import time
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update

from server import auth
from server.api.companion import router as companion_router
from server.api.projects import router as projects_router
from server.services import project_drafter, project_evidence, project_habits, project_plan, settings_service


@pytest.fixture
async def api(execution_db, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-habits-token")
    app = FastAPI()
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(companion_router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-habits-token"}) as client:
        yield client


TWO = [{"name": "Shape it", "band": "shaping", "checkpoints": [{"text": "Sketch"}, {"text": "Mood board"}]},
       {"name": "Make it", "band": "doing", "checkpoints": [{"text": "Build"}]},
       {"name": "Ship it", "band": "done", "checkpoints": []}]


async def _project(api, name="Sample", template="game", levels=TWO, folder=None, active=True) -> str:
    body = {"name": name, "kind": "general", "template": template}
    if folder is not None:
        body["workspace_ref"] = str(folder)
    pid = (await api.post("/api/v1/projects", json=body)).json()["id"]
    response = await api.put(f"/api/v1/projects/{pid}/plan", json={"expected_version": 0, "levels": levels})
    assert response.status_code == 200, response.text
    if active:
        await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    return pid


async def _plan(api, pid):
    return (await api.get(f"/api/v1/projects/{pid}/plan")).json()


async def _propose(execution_db, pid):
    from server.db.models import Project
    async with execution_db() as db:
        event = await project_plan.propose_advance(db, await db.get(Project, pid), evidence={"kind": "said", "quote": "ok"})
        await db.commit()
    return event


async def _shadow(api):
    return (await api.get("/api/v1/projects/board")).json()["shadow"]


async def _set(execution_db, key, value):
    async with execution_db() as db:
        await settings_service._set_raw(db, key, value)
        await db.commit()


# ── shadow mode (§5) ─────────────────────────────────────────────────────────

async def test_the_ask_comes_once_at_ten_kept_in_a_row(api, execution_db):
    pids = [await _project(api, name=f"P{i}", levels=[TWO[0]] * 1 + TWO[1:] * 6) for i in range(2)]
    for i in range(10):
        pid = pids[i % 2]
        event = await _propose(execution_db, pid)
        await api.post(f"/api/v1/projects/{pid}/proposals/{event.id}/accept")
        s = await _shadow(api)
        assert s["streak"] == i + 1 and s["ask_due"] is (i == 9), i
    # 先不: asked, never again, nothing turned on.
    response = await api.put("/api/v1/project-habits/auto-advance", json={"on": False, "answered": "ask"})
    assert response.status_code == 200
    s = await _shadow(api)
    assert s["asked"] and not s["ask_due"] and not s["auto_advance"]
    event = await _propose(execution_db, pids[0])
    assert event.kind == "proposal"                  # still asks; auto-advance never on by itself
    await api.post(f"/api/v1/projects/{pids[0]}/proposals/{event.id}/accept")
    assert not (await _shadow(api))["ask_due"]


async def test_a_decline_or_an_undo_resets_the_streak(api, execution_db):
    pid = await _project(api, levels=[TWO[0]] + TWO[1:] * 4)
    event = await _propose(execution_db, pid)
    await api.post(f"/api/v1/projects/{pid}/proposals/{event.id}/accept")
    event = await _propose(execution_db, pid)
    await api.post(f"/api/v1/projects/{pid}/proposals/{event.id}/decline")
    s = await _shadow(api)
    assert (s["proposed"], s["accepted"], s["streak"]) == (2, 1, 0)
    assert s["last_miss"]["outcome"] == "declined" and s["last_miss"]["level"] == "Make it"
    assert s["miss_is_latest"] is True
    event = await _propose(execution_db, pid)
    await api.post(f"/api/v1/projects/{pid}/proposals/{event.id}/accept")
    s = await _shadow(api)
    assert s["miss_is_latest"] is False and s["last_miss"]["level"] == "Make it"   # the sheet still shows it


async def test_with_auto_advance_its_moves_count_and_two_undos_offer_to_turn_it_off(api, execution_db):
    pid = await _project(api, levels=[TWO[0]] + TWO[1:2] * 5 + TWO[2:])
    await api.put("/api/v1/project-habits/auto-advance", json={"on": True, "answered": "ask"})
    first = await _propose(execution_db, pid)
    assert first.kind == "advance" and first.actor == "arslan"
    s = await _shadow(api)
    assert (s["proposed"], s["accepted"], s["streak"], s["offer_off"]) == (1, 1, 1, False)
    await api.post(f"/api/v1/projects/{pid}/events/{first.id}/undo")
    assert (await _shadow(api))["offer_off"] is False                  # one undo: not yet
    second = await _propose(execution_db, pid)
    await api.post(f"/api/v1/projects/{pid}/events/{second.id}/undo")
    s = await _shadow(api)
    assert s["streak"] == 0 and s["offer_off"] is True and s["last_miss"]["outcome"] == "undone"
    # 留着: not offered again for this run of undos...
    await api.put("/api/v1/project-habits/auto-advance", json={"on": True, "answered": "offer"})
    assert (await _shadow(api))["offer_off"] is False
    # ...but a third undo is a new run.
    third = await _propose(execution_db, pid)
    await api.post(f"/api/v1/projects/{pid}/events/{third.id}/undo")
    assert (await _shadow(api))["offer_off"] is True
    await api.put("/api/v1/project-habits/auto-advance", json={"on": False, "answered": "offer"})
    s = await _shadow(api)
    assert s["auto_advance"] is False and s["offer_off"] is False


async def test_the_setting_is_a_plain_settings_key(execution_db):
    async with execution_db() as db:
        await settings_service.update_settings(db, {"projects_auto_advance": "true"})
        await db.commit()
        assert await project_plan.auto_advance_enabled(db) is True
        assert (await settings_service.get_settings(db))["projects_auto_advance"] == "true"


# ── plan rules (§6) ──────────────────────────────────────────────────────────

async def test_a_declines_line_becomes_a_switchable_rule_the_drafter_uses(api, execution_db):
    pid = await _project(api, name="Sluice (sample)", levels=[TWO[0]] + TWO[1:] * 2)
    event = await _propose(execution_db, pid)
    await api.post(f"/api/v1/projects/{pid}/proposals/{event.id}/decline", json={"note": "  还想 再试一版  "})
    sheet = (await api.get("/api/v1/project-habits")).json()
    [rule] = sheet["rules"]
    assert rule["text"] == "还想 再试一版" and rule["template"] == "game" and rule["enabled"]
    assert rule["sources"] == ["Sluice (sample)"] and rule["value"] == {"code": "note"}
    assert sheet["shadow"]["last_miss"]["note"] == "还想 再试一版"
    assert await project_drafter.plan_rules("game") == ["还想 再试一版"]
    assert await project_drafter.plan_rules("trip") == []
    off = await api.put(f"/api/v1/project-habits/rules/{rule['id']}", json={"enabled": False})
    assert off.json()["rules"][0]["enabled"] is False
    assert await project_drafter.plan_rules("game") == []
    assert (await api.put("/api/v1/project-habits/rules/nope", json={"enabled": True})).status_code == 404


async def test_an_accept_ignores_the_note(api, execution_db):
    pid = await _project(api, levels=[TWO[0]] + TWO[1:] * 2)
    event = await _propose(execution_db, pid)
    await api.post(f"/api/v1/projects/{pid}/proposals/{event.id}/accept", json={"note": "not a rule"})
    assert (await api.get("/api/v1/project-habits")).json()["rules"] == []


async def test_the_same_added_level_in_two_projects_of_a_type_becomes_a_rule(api):
    lv = lambda name, band="shaping": {"name": name, "band": band, "checkpoints": []}  # noqa: E731
    stock = [lv("Idea"), lv("Prototype (find the fun)"), lv("Production", "doing"), lv("Launch", "done")]
    extra = stock[:2] + [lv("Art direction OK")] + stock[2:]
    scratch = [lv("Art direction OK"), lv("Build", "doing"), lv("Ship", "done")]       # not built on the template
    await _project(api, name="A", levels=extra)
    app = [lv("Problem and users"), lv("Prototype"), lv("Art direction OK"), lv("Core features", "doing"), lv("Launch", "done")]
    await _project(api, name="B", template="app", levels=app)            # another type: does not count
    await _project(api, name="S", levels=scratch)                       # written from scratch: not an addition
    await _project(api, name="H", levels=stock[:2] + [{**lv("Art direction OK"), "habit": True}] + stock[2:])
    await _project(api, name="C", levels=stock)
    await _project(api, name="D", levels=stock)
    assert (await api.get("/api/v1/project-habits")).json()["rules"] == []
    await _project(api, name="E", levels=[{**x, "name": x["name"].upper()} if x["name"] == "Art direction OK"
                                          else x for x in extra])
    [rule] = (await api.get("/api/v1/project-habits")).json()["rules"]
    assert rule["template"] == "game" and rule["value"]["code"] == "add_level"
    assert rule["sources"] == ["A", "E"] and "Art direction OK" in rule["text"]
    await _project(api, name="F", levels=extra)                            # learned once
    assert len((await api.get("/api/v1/project-habits")).json()["rules"]) == 1


async def test_cutting_planned_work_mid_way_in_two_projects_becomes_a_rule(api):
    async def cut(pid):
        plan = await _plan(api, pid)
        levels = [{**lv, "checkpoints": lv["checkpoints"][:1]} for lv in plan["levels"]]
        response = await api.put(f"/api/v1/projects/{pid}/plan", json={"expected_version": plan["version"], "levels": levels})
        assert response.status_code == 200
    a = await _project(api, name="A")
    idea = await _project(api, name="Not started", active=False)
    await cut(a)
    await cut(a)                                     # nothing more to cut, and one project is not a habit
    await cut(idea)                                  # not mid-way: never started
    assert (await api.get("/api/v1/project-habits")).json()["rules"] == []
    b = await _project(api, name="B")
    await cut(b)
    [rule] = (await api.get("/api/v1/project-habits")).json()["rules"]
    assert rule["value"] == {"code": "cut_scope"} and rule["sources"] == ["A", "B"]


# ── pace ─────────────────────────────────────────────────────────────────────

async def _clear_levels(execution_db, pid, days: list[float]):
    from server.db.models import ProjectLevel
    async with execution_db() as db:
        levels = (await db.execute(select(ProjectLevel).where(ProjectLevel.project_id == pid)
                                   .order_by(ProjectLevel.position))).scalars().all()
        start = datetime(2026, 1, 1)
        for level, d in zip(levels, days):
            level.state, level.started_at, level.cleared_at = "cleared", start, start + timedelta(days=d)
        await db.commit()


async def test_pace_is_a_median_from_three_cleared_levels_and_can_be_overridden(api, execution_db):
    shaping3 = [{"name": f"S{i}", "band": "shaping", "checkpoints": []} for i in range(3)] + [TWO[2]]
    a = await _project(api, name="A", levels=shaping3)
    await _clear_levels(execution_db, a, [2, 4])
    sheet = (await api.get("/api/v1/project-habits")).json()
    assert sheet["pace"] == [] and sheet["cleared_levels"] == 2 and sheet["pace_min_levels"] == 3
    b = await _project(api, name="B", levels=shaping3)
    await _clear_levels(execution_db, b, [9])
    [row] = (await api.get("/api/v1/project-habits")).json()["pace"]
    assert row == {"template": "game", "band": "shaping", "levels": 3, "median_days": 4.0, "override_days": None}
    response = await api.put("/api/v1/project-habits/pace", json={"template": "game", "band": "shaping", "days": 6})
    assert response.json()["pace"][0]["override_days"] == 6.0
    async with execution_db() as db:
        assert await project_habits.usual_days(db, "local", "game", "shaping") == 6.0
        assert await project_habits.usual_days(db, "local", "app", "shaping") is None
    await api.put("/api/v1/project-habits/pace", json={"template": "game", "band": "shaping", "days": None})
    async with execution_db() as db:
        assert await project_habits.usual_days(db, "local", "game", "shaping") == 4.0
    bad = await api.put("/api/v1/project-habits/pace", json={"template": "boat", "band": "shaping", "days": 3})
    assert bad.status_code == 422


# ── stalled (§9) ─────────────────────────────────────────────────────────────

async def _age(execution_db, pid, days):
    from server.db.models import ProjectEvent, ProjectLevel
    when = datetime.utcnow() - timedelta(days=days)
    async with execution_db() as db:
        await db.execute(update(ProjectEvent).where(ProjectEvent.project_id == pid).values(created_at=when))
        await db.execute(update(ProjectLevel).where(ProjectLevel.project_id == pid, ProjectLevel.started_at.is_not(None))
                         .values(started_at=when))
        await db.commit()


async def _card(api, pid):
    return next(c for c in (await api.get("/api/v1/projects/board")).json()["cards"] if c["id"] == pid)


async def test_quiet_for_more_than_three_weeks_is_stalled_on_the_card_only(api, execution_db):
    from server.db.models import ProactiveItem
    pid = await _project(api)
    await _age(execution_db, pid, 20)
    assert (await _card(api, pid))["stall"] is None
    await _age(execution_db, pid, 23)
    assert (await _card(api, pid))["stall"] == {"days": 23, "usual": None, "left": 3}
    await api.put(f"/api/v1/projects/{pid}/stage", json={"paused": True})
    await _age(execution_db, pid, 23)                       # pausing is activity too; age it again
    assert (await _card(api, pid))["stall"] is None
    async with execution_db() as db:
        assert await db.scalar(select(func.count()).select_from(ProactiveItem)) == 0


async def test_more_than_twice_the_usual_is_stalled_when_the_pace_is_known(api, execution_db):
    pid = await _project(api)
    await api.put("/api/v1/project-habits/pace", json={"template": "game", "band": "shaping", "days": 3})
    await _age(execution_db, pid, 6)
    assert (await _card(api, pid))["stall"] is None
    await _age(execution_db, pid, 7)
    assert (await _card(api, pid))["stall"] == {"days": 7, "usual": 3.0, "left": 3}
    # A tick today is activity: no longer stalled.
    plan = await _plan(api, pid)
    await api.post(f"/api/v1/projects/{pid}/checkpoints/{plan['levels'][0]['checkpoints'][0]['id']}/tick")
    assert (await _card(api, pid))["stall"] is None


async def test_a_short_usual_never_marks_a_gap_under_the_floor(api, execution_db):
    pid = await _project(api)
    await api.put("/api/v1/project-habits/pace", json={"template": "game", "band": "shaping", "days": 0.5})
    await _age(execution_db, pid, 3)
    assert (await _card(api, pid))["stall"] is None
    await _age(execution_db, pid, 4)
    assert (await _card(api, pid))["stall"]["days"] == 4


async def test_a_file_changed_in_the_folder_is_activity_and_starts_a_planned_idea(api, execution_db, tmp_path):
    from server.db.models import ProjectEvent
    tmp_path = tmp_path / "folder"           # the test database lives in tmp_path itself
    tmp_path.mkdir()
    old = tmp_path / "old.txt"
    old.write_text("x")
    past = time.time() - 40 * 86400
    os.utime(old, (past, past))
    pid = await _project(api, folder=tmp_path, active=False)
    await project_evidence.scan_projects()
    assert (await _plan(api, pid))["stage"] == "idea"           # a file from before the project is not activity
    (tmp_path / "new.txt").write_text("y")
    await project_evidence.scan_projects()
    assert (await _plan(api, pid))["stage"] == "active"
    async with execution_db() as db:
        kinds = (await db.execute(select(ProjectEvent.kind).where(ProjectEvent.project_id == pid))).scalars().all()
    assert "activity" in kinds
    await _age(execution_db, pid, 30)
    assert (await _card(api, pid))["stall"] is not None
    (tmp_path / "newer.txt").write_text("z")
    await project_evidence.scan_projects()
    assert (await _card(api, pid))["stall"] is None


async def test_the_line_can_be_added_after_declining_once(api, execution_db):
    pid = await _project(api, levels=[TWO[0]] + TWO[1:] * 2)
    event = await _propose(execution_db, pid)
    early = await api.post(f"/api/v1/projects/{pid}/proposal-notes/{event.id}", json={"note": "not yet declined"})
    assert early.status_code == 409
    await api.post(f"/api/v1/projects/{pid}/proposals/{event.id}/decline")
    assert (await _shadow(api))["last_miss"]["note"] is None
    ok = await api.post(f"/api/v1/projects/{pid}/proposal-notes/{event.id}", json={"note": "one more pass"})
    assert ok.status_code == 200
    assert (await _shadow(api))["last_miss"]["note"] == "one more pass"
    again = await api.post(f"/api/v1/projects/{pid}/proposal-notes/{event.id}", json={"note": "and another"})
    assert again.status_code == 409
    assert [r["text"] for r in (await api.get("/api/v1/project-habits")).json()["rules"]] == ["one more pass"]


async def test_a_card_says_what_to_do_next(api):
    pid = await _project(api)
    plan = await _plan(api, pid)
    first = plan["levels"][0]["checkpoints"][0]
    await api.post(f"/api/v1/projects/{pid}/checkpoints/{first['id']}/tick")
    card = await _card(api, pid)
    assert card["next"] == {"id": plan["levels"][0]["checkpoints"][1]["id"], "text": "Mood board"}
