"""0.1.56 P1: projects in two layers — plan, derived column, ticks, proposals, undo, board."""
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from server import auth
from server.api.companion import router as companion_router
from server.api.projects import router as projects_router
from server.services import project_plan, project_templates
from server.services.project_plan import column_of


@pytest.fixture
async def api(execution_db, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-projects-token")
    app = FastAPI()
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(companion_router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-projects-token"}) as client:
        yield client


GAME_LEVELS = [
    {"name": "Idea", "band": "shaping", "checkpoints": [{"text": "One-line pitch"}]},
    {"name": "Prototype", "band": "shaping",
     "checkpoints": [{"text": "Playable build", "expects": {"kind": "file", "pattern": "build/*"}}, {"text": "Fun test"}]},
    {"name": "Production", "band": "doing", "checkpoints": []},
    {"name": "Launch", "band": "done", "checkpoints": []},
]


async def _create(api, **extra) -> dict:
    body = {"name": "Sluice (sample)", "kind": "general", "template": "game",
            "finish_line": "On the App Store", **extra}
    response = await api.post("/api/v1/projects", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _plan(api, pid, levels=GAME_LEVELS, version=0):
    response = await api.put(f"/api/v1/projects/{pid}/plan", json={"expected_version": version, "levels": levels})
    assert response.status_code == 200, response.text
    return response.json()


async def _project_row(execution_db, pid):
    from server.db.models import Project
    async with execution_db() as db:
        return await db.get(Project, pid)


async def _run(execution_db, fn):
    from server.db.models import Project
    async def go(pid, *args, **kw):
        async with execution_db() as db:
            project = await db.get(Project, pid)
            out = await fn(db, project, *args, **kw)
            await db.commit()
            return out
    return go


# ── the column is derived ─────────────────────────────────────────────────────

L = lambda band, state: {"band": band, "state": state}  # noqa: E731


@pytest.mark.parametrize("stage, levels, column", [
    ("idea", [L("shaping", "todo")], "idea"),
    (None, [], "idea"),
    ("active", [L("shaping", "current"), L("doing", "todo")], "shaping"),
    ("active", [L("shaping", "cleared"), L("doing", "current"), L("done", "todo")], "doing"),
    ("active", [L("shaping", "cleared"), L("doing", "cleared"), L("done", "current")], "doing"),  # Done is the user's
    ("active", [L("shaping", "cleared"), L("done", "cleared")], "doing"),                         # all cleared, not marked
    ("done", [L("shaping", "cleared")], "done"),
    ("dropped", [L("shaping", "current")], "dropped"),
])
def test_the_board_column_is_a_function_of_stage_and_current_band(stage, levels, column):
    assert column_of(stage, levels) == column


# ── templates and the deterministic draft ─────────────────────────────────────

def test_every_template_has_six_languages_and_runs_shaping_to_done():
    assert len(project_templates.TEMPLATES) == 10
    for key, levels in project_templates.TEMPLATES.items():
        assert levels[0][0] == "shaping" and levels[-1][0] == "done", key
        bands = [band for band, _ in levels]
        assert bands == sorted(bands, key=project_templates.BANDS.index), key   # never goes back a column
        for band, names in levels:
            assert set(names) == set(project_templates.LANGS) and all(n.strip() for n in names.values()), key


async def test_the_draft_is_the_template_in_the_users_language_with_the_finish_line_last(api):
    draft = (await api.post("/api/v1/projects/draft", json={"template": "game", "finish_line": "上架 App Store",
                                                               "lang": "zh-CN"})).json()
    assert draft["source"] == "template"
    assert [lv["name"] for lv in draft["levels"]][:2] == ["点子", "原型（找乐子）"]
    assert draft["levels"][-1]["clear_condition"] == "上架 App Store"
    unknown = (await api.post("/api/v1/projects/draft", json={"template": "nope"})).json()
    assert unknown["levels"][0]["name"] == "Think it through"


# ── plan writes never touch projects.version ──────────────────────────────────

async def test_no_plan_operation_changes_the_version_that_pins_running_tasks(api, execution_db):
    project = await _create(api)
    pid = project["id"]
    pinned = (await _project_row(execution_db, pid)).version
    plan = await _plan(api, pid)
    from server.services.project_plan import note_activity
    async with execution_db() as db:
        await note_activity(db, pid)
        await db.commit()
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    cp = plan["levels"][0]["checkpoints"][0]["id"]
    tick = await _run(execution_db, project_plan.tick)
    await tick(pid, cp, actor="arslan", evidence={"kind": "said", "quote": "pitch is fine"})
    board = (await api.get("/api/v1/projects/board")).json()
    proposal = board["cards"][0]["proposal"]
    await api.post(f"/api/v1/projects/{pid}/proposals/{proposal['id']}/accept")
    events = (await api.get(f"/api/v1/projects/{pid}/events")).json()
    advance = next(e for e in events if e["kind"] == "advance")
    await api.post(f"/api/v1/projects/{pid}/events/{advance['id']}/undo")
    await api.put(f"/api/v1/projects/{pid}/stage", json={"paused": True})
    await _plan(api, pid, GAME_LEVELS[:3], version=(await api.get(f"/api/v1/projects/{pid}/plan")).json()["version"])
    row = await _project_row(execution_db, pid)
    # task_repository._active / start compare exactly these two: a running task keeps going.
    assert row.version == pinned and row.status == "active"


# ── starting, ticking, proposing, deciding, undoing ───────────────────────────

async def test_a_planned_project_waits_in_idea_until_the_first_activity(api, execution_db):
    pid = (await _create(api))["id"]
    plan = await _plan(api, pid)
    assert plan["stage"] == "idea" and plan["column"] == "idea" and plan["version"] == 1
    assert all(lv["state"] == "todo" for lv in plan["levels"])
    async with execution_db() as db:
        await project_plan.note_activity(db, pid)
        await project_plan.note_activity(db, pid)       # an hour has not passed: one activity row
        await db.commit()
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    assert plan["stage"] == "active" and plan["column"] == "shaping"
    assert plan["levels"][0]["state"] == "current" and plan["levels"][0]["started_at"]
    from sqlalchemy import func, select

    from server.db.models import ProjectEvent
    async with execution_db() as db:
        assert await db.scalar(select(func.count()).select_from(ProjectEvent).where(ProjectEvent.kind == "activity")) == 1


async def test_arslan_ticks_need_evidence_and_completing_a_level_makes_one_proposal(api, execution_db):
    pid = (await _create(api))["id"]
    await _plan(api, pid)
    async with execution_db() as db:
        await project_plan.note_activity(db, pid)
        await db.commit()
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    level1_cp = plan["levels"][0]["checkpoints"][0]["id"]
    tick = await _run(execution_db, project_plan.tick)
    with pytest.raises(project_plan.PlanError, match="evidence_required"):
        await tick(pid, level1_cp, actor="arslan")
    await tick(pid, level1_cp, actor="arslan", evidence={"kind": "file", "path": "pitch.md"})
    await tick(pid, level1_cp, actor="arslan", evidence={"kind": "file", "path": "pitch.md"})   # already done: no-op
    card = (await api.get("/api/v1/projects/board")).json()["cards"][0]
    assert card["proposal"]["level"] == "Idea" and card["proposal"]["next"] == "Prototype"
    assert card["proposal"]["moves_column"] is False
    # Nothing moved yet: a proposal waits for the user.
    assert card["current"]["name"] == "Idea" and card["column"] == "shaping"
    from sqlalchemy import func, select

    from server.db.models import ProjectEvent
    async with execution_db() as db:
        assert await db.scalar(select(func.count()).select_from(ProjectEvent).where(ProjectEvent.kind == "proposal")) == 1


async def test_a_user_tick_never_proposes(api, execution_db):
    pid = (await _create(api))["id"]
    await _plan(api, pid)
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    response = await api.post(f"/api/v1/projects/{pid}/checkpoints/{plan['levels'][0]['checkpoints'][0]['id']}/tick")
    assert response.json()["levels"][0]["checkpoints"][0]["done_by"] == "user"
    assert (await api.get("/api/v1/projects/board")).json()["cards"][0]["proposal"] is None


async def _ready_with_proposal(api, execution_db, level_index=0):
    pid = (await _create(api))["id"]
    await _plan(api, pid)
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    propose = await _run(execution_db, project_plan.propose_advance)
    await propose(pid, evidence={"kind": "said", "quote": "this level is done"})
    card = (await api.get("/api/v1/projects/board")).json()["cards"][0]
    return pid, card["proposal"]["id"]


async def test_accept_advances_and_the_streak_counts_decline_and_undo_as_misses(api, execution_db):
    pid, proposal = await _ready_with_proposal(api, execution_db)
    plan = (await api.post(f"/api/v1/projects/{pid}/proposals/{proposal}/accept")).json()
    assert [lv["state"] for lv in plan["levels"]] == ["cleared", "current", "todo", "todo"]
    shadow = (await api.get("/api/v1/projects/board")).json()["shadow"]
    assert (shadow["proposed"], shadow["accepted"], shadow["streak"]) == (1, 1, 1)
    # A second proposal, declined: the streak resets.
    propose = await _run(execution_db, project_plan.propose_advance)
    await propose(pid, evidence={"kind": "said", "quote": "prototype done"})
    second = (await api.get("/api/v1/projects/board")).json()["cards"][0]["proposal"]["id"]
    assert (await api.post(f"/api/v1/projects/{pid}/proposals/{second}/decline")).status_code == 200
    shadow = (await api.get("/api/v1/projects/board")).json()["shadow"]
    assert (shadow["proposed"], shadow["accepted"], shadow["streak"]) == (2, 1, 0)
    assert (await api.post(f"/api/v1/projects/{pid}/proposals/{second}/accept")).status_code == 409


async def test_undoing_an_accepted_advance_reverts_it_and_counts_as_a_miss(api, execution_db):
    pid, proposal = await _ready_with_proposal(api, execution_db)
    await api.post(f"/api/v1/projects/{pid}/proposals/{proposal}/accept")
    advance = next(e for e in (await api.get(f"/api/v1/projects/{pid}/events")).json() if e["kind"] == "advance")
    plan = (await api.post(f"/api/v1/projects/{pid}/events/{advance['id']}/undo")).json()
    assert [lv["state"] for lv in plan["levels"]][:2] == ["current", "todo"]
    assert plan["levels"][1]["started_at"] is None
    shadow = (await api.get("/api/v1/projects/board")).json()["shadow"]
    assert (shadow["accepted"], shadow["streak"]) == (0, 0)


async def test_only_the_latest_advance_can_be_undone(api, execution_db):
    pid = (await _create(api))["id"]
    await _plan(api, pid)
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    await api.post(f"/api/v1/projects/{pid}/advance")
    await api.post(f"/api/v1/projects/{pid}/advance")
    advances = [e for e in (await api.get(f"/api/v1/projects/{pid}/events")).json() if e["kind"] == "advance"]
    older = advances[-1]["id"]
    response = await api.post(f"/api/v1/projects/{pid}/events/{older}/undo")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "only_latest_advance"


async def test_a_proposal_the_plan_moved_past_goes_stale_and_does_not_count(api, execution_db):
    pid, proposal = await _ready_with_proposal(api, execution_db)
    await api.post(f"/api/v1/projects/{pid}/advance")                       # cleared by hand meanwhile
    assert (await api.post(f"/api/v1/projects/{pid}/proposals/{proposal}/accept")).status_code == 200
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    assert [lv["state"] for lv in plan["levels"]][:3] == ["cleared", "current", "todo"]   # not advanced twice
    shadow = (await api.get("/api/v1/projects/board")).json()["shadow"]
    assert shadow["proposed"] == 0


async def test_the_last_level_is_proposed_as_met_but_done_stays_the_users(api, execution_db):
    pid = (await _create(api))["id"]
    await _plan(api, pid, [{"name": "Only", "band": "done", "checkpoints": []}])
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    propose = await _run(execution_db, project_plan.propose_advance)
    await propose(pid, evidence={"kind": "said", "quote": "it shipped"})
    card = (await api.get("/api/v1/projects/board")).json()["cards"][0]
    assert card["proposal"]["last"] is True
    await api.post(f"/api/v1/projects/{pid}/proposals/{card['proposal']['id']}/accept")
    card = (await api.get("/api/v1/projects/board")).json()["cards"][0]
    assert card["stage"] == "active" and card["column"] == "doing"
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "done"})
    card = (await api.get("/api/v1/projects/board")).json()["cards"][0]
    assert card["column"] == "done" and card["done_at"]


async def test_with_auto_advance_on_arslan_advances_itself_but_never_past_the_last_level(api, execution_db):
    from server.services import settings_service
    async with execution_db() as db:
        await settings_service._set_raw(db, "projects_auto_advance", "true")
        await db.commit()
    pid = (await _create(api))["id"]
    await _plan(api, pid, GAME_LEVELS[:2])
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    propose = await _run(execution_db, project_plan.propose_advance)
    await propose(pid, evidence={"kind": "said", "quote": "pitch done"})
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    assert [lv["state"] for lv in plan["levels"]] == ["cleared", "current"]
    advance = next(e for e in (await api.get(f"/api/v1/projects/{pid}/events")).json() if e["kind"] == "advance")
    assert advance["actor"] == "arslan" and advance["payload"]["evidence"]["quote"] == "pitch done"
    await propose(pid, evidence={"kind": "said", "quote": "shipped"})     # last level: a proposal, not an advance
    card = (await api.get("/api/v1/projects/board")).json()["cards"][0]
    assert card["proposal"]["last"] is True and card["stage"] == "active"


# ── re-planning keeps history ────────────────────────────────────────────────

async def test_cleared_levels_stay_and_kept_checkpoints_keep_their_ticks(api, execution_db):
    pid = (await _create(api))["id"]
    await _plan(api, pid)
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    await api.post(f"/api/v1/projects/{pid}/advance")
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    proto = plan["levels"][1]
    await api.post(f"/api/v1/projects/{pid}/checkpoints/{proto['checkpoints'][0]['id']}/tick")
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    # The request tries to rename the cleared level and drops it; it reorders the rest.
    request = [{**plan["levels"][0], "name": "RENAMED"},
               {**plan["levels"][1], "name": "Prototype v2"},
               {"name": "Beta", "band": "doing", "checkpoints": [{"text": "5 testers"}]},
               plan["levels"][3]]
    new = await _plan(api, pid, request, version=plan["version"])
    assert [lv["name"] for lv in new["levels"]] == ["Idea", "Prototype v2", "Beta", "Launch"]
    assert new["levels"][0]["state"] == "cleared"
    assert new["levels"][1]["state"] == "current" and new["levels"][1]["started_at"] == proto["started_at"]
    assert new["levels"][1]["checkpoints"][0]["state"] == "done"
    stale = await api.put(f"/api/v1/projects/{pid}/plan", json={"expected_version": plan["version"], "levels": request})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "plan_version_conflict"
    kinds = [e["kind"] for e in (await api.get(f"/api/v1/projects/{pid}/events")).json()]
    assert "plan_change" in kinds


async def test_bad_plans_are_refused(api):
    pid = (await _create(api))["id"]
    for levels, code in [([], "invalid_plan"), ([{"name": "x", "band": "later"}], "invalid_level"),
                         ([{"name": "x", "band": "doing", "checkpoints": [{"text": ""}]}], "invalid_checkpoints"),
                         ([{"name": "x", "band": "doing", "checkpoints": [{"text": "a", "expects": {"kind": "url"}}]}],
                          "invalid_expects")]:
        response = await api.put(f"/api/v1/projects/{pid}/plan", json={"expected_version": 0, "levels": levels})
        assert response.status_code == 422 and response.json()["detail"]["code"] == code, levels


# ── the board, files, conversations ──────────────────────────────────────────

async def test_the_board_lists_active_projects_with_counts(api):
    a = (await _create(api, name="A"))["id"]
    b = (await _create(api, name="B"))["id"]
    await _plan(api, a)
    await api.put(f"/api/v1/projects/{a}/stage", json={"stage": "active", "paused": True})
    project_b = (await api.get("/api/v1/projects?include_archived=true")).json()
    b_row = next(p for p in project_b if p["id"] == b)
    await api.put(f"/api/v1/projects/{b}", json={"expected_version": b_row["version"], "status": "archived",
                                                  "project": {"name": "B", "kind": "general"}})
    board = (await api.get("/api/v1/projects/board")).json()
    assert [c["id"] for c in board["cards"]] == [a]
    card = board["cards"][0]
    assert card["paused"] is True and card["column"] == "shaping" and card["left"] == 4
    assert card["current"] == {"position": 1, "name": "Idea", "started_at": card["current"]["started_at"]}
    assert board["counts"] == {"paused": 1, "archived": 1}
    assert board["shadow"]["ask_at"] == 10 and board["shadow"]["auto_advance"] is False


async def test_files_lists_the_folder_top_level_without_secrets(api, tmp_path):
    folder = tmp_path / "Sluice"
    (folder / "levels").mkdir(parents=True)
    (folder / "README.md").write_text("x")
    (folder / ".env").write_text("SECRET=1")
    (folder / "id_rsa").write_text("key")
    pid = (await _create(api, workspace_ref=str(folder)))["id"]
    listing = (await api.get(f"/api/v1/projects/{pid}/files")).json()
    assert listing["exists"] is True
    assert listing["entries"] == [{"name": "levels", "dir": True}, {"name": "README.md", "dir": False}]
    missing = (await _create(api, name="X", workspace_ref=str(tmp_path / "nope")))["id"]
    assert (await api.get(f"/api/v1/projects/{missing}/files")).json()["exists"] is False


async def test_conversations_of_a_project_newest_first_with_their_opening(api, execution_db):
    from server.db.models import ArslanMessage, ConversationContext
    pid = (await _create(api))["id"]
    now = datetime.utcnow()
    async with execution_db() as db:
        for cid, opening, age in [("c-old", "Plan the prototype", 3), ("c-new", "Draw the art", 1)]:
            db.add(ConversationContext(id=cid, owner_id="local", project_id=pid))
            db.add(ArslanMessage(conversation_id=cid, role="user", content=opening, timestamp=now - timedelta(days=age)))
            db.add(ArslanMessage(conversation_id=cid, role="arslan", content="ok", timestamp=now - timedelta(days=age)))
        db.add(ConversationContext(id="c-other", owner_id="local", project_id=None))
        await db.commit()
    rows = (await api.get(f"/api/v1/projects/{pid}/conversations")).json()
    assert [r["conversation_id"] for r in rows] == ["c-new", "c-old"]
    assert rows[0]["opening"] == "Draw the art" and rows[0]["messages"] == 2


async def test_unknown_project_and_checkpoint_are_404(api):
    assert (await api.get("/api/v1/projects/nope/plan")).status_code == 404
    pid = (await _create(api))["id"]
    await _plan(api, pid)
    assert (await api.post(f"/api/v1/projects/{pid}/checkpoints/nope/tick")).status_code == 404


async def test_one_open_proposal_at_a_time(api, execution_db):
    pid, first = await _ready_with_proposal(api, execution_db)
    propose = await _run(execution_db, project_plan.propose_advance)
    assert await propose(pid, evidence={"kind": "said", "quote": "again"}) is None
    events = (await api.get(f"/api/v1/projects/{pid}/events")).json()
    assert [e["id"] for e in events if e["kind"] == "proposal"] == [first]


async def test_a_turn_in_a_project_conversation_counts_as_its_activity(execution_db, monkeypatch):
    """run_turn notes the activity before anything else about the turn, and only for a project."""
    from server.services import personal_context as pc
    from server.services import task_service
    seen = []

    class Stop(Exception):
        pass

    async def note(project_id):
        seen.append(project_id)
        raise Stop

    monkeypatch.setattr(task_service, "_note_project_activity", note)

    async def function(*_args, **_kw):
        return "answer"

    ctx = pc.TaskMemoryContext(task_id="t1", run_id="turn-t1", conversation_id="c1", model_is_local=True,
                               project_id="p-1")
    with pc.bind(ctx), pytest.raises(Stop):
        await task_service.run_turn(function, "c1", "hello", None)
    assert seen == ["p-1"]
    seen.clear()
    plain = pc.TaskMemoryContext(task_id="t2", run_id="turn-t2", conversation_id="c2", model_is_local=True)
    monkeypatch.setattr(task_service, "repository", lambda: (_ for _ in ()).throw(Stop()))
    with pc.bind(plain), pytest.raises(Stop):
        await task_service.run_turn(function, "c2", "hello", None)
    assert seen == []


async def test_the_activity_hook_starts_a_planned_project_and_never_raises(api, execution_db, monkeypatch):
    from server.services import task_service
    pid = (await _create(api))["id"]
    await _plan(api, pid)
    await task_service._note_project_activity(pid)
    assert (await api.get(f"/api/v1/projects/{pid}/plan")).json()["stage"] == "active"

    async def broken(*_a, **_k):
        raise RuntimeError("db gone")
    monkeypatch.setattr(project_plan, "note_activity", broken)
    await task_service._note_project_activity(pid)           # logged, not raised
