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
    plan = (await api.post(f"/api/v1/projects/{pid}/proposals/{proposal}/accept", json={"leftover": "drop"})).json()
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
    assert (await api.post(f"/api/v1/projects/{pid}/proposals/{second}/accept", json={"leftover": "drop"})).status_code == 409


async def test_undoing_an_accepted_advance_reverts_it_and_counts_as_a_miss(api, execution_db):
    pid, proposal = await _ready_with_proposal(api, execution_db)
    await api.post(f"/api/v1/projects/{pid}/proposals/{proposal}/accept", json={"leftover": "drop"})
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
    await api.post(f"/api/v1/projects/{pid}/advance", json={"leftover": "drop"})
    await api.post(f"/api/v1/projects/{pid}/advance", json={"leftover": "drop"})
    advances = [e for e in (await api.get(f"/api/v1/projects/{pid}/events")).json() if e["kind"] == "advance"]
    older = advances[-1]["id"]
    response = await api.post(f"/api/v1/projects/{pid}/events/{older}/undo")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "only_latest_advance"


async def test_a_proposal_the_plan_moved_past_goes_stale_and_does_not_count(api, execution_db):
    pid, proposal = await _ready_with_proposal(api, execution_db)
    await api.post(f"/api/v1/projects/{pid}/advance", json={"leftover": "drop"})                       # cleared by hand meanwhile
    assert (await api.post(f"/api/v1/projects/{pid}/proposals/{proposal}/accept", json={"leftover": "drop"})).status_code == 200
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
    # 0.1.58 §5: auto-advance only clears a level with nothing left open.
    await _plan(api, pid, [{**lv, "checkpoints": []} for lv in GAME_LEVELS[:2]])
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
    await api.post(f"/api/v1/projects/{pid}/advance", json={"leftover": "drop"})
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


# ── the project reaches the model (§8) ───────────────────────────────────────

async def test_the_card_names_the_project_its_finish_line_level_and_open_checkpoints(api, execution_db, tmp_path):
    pid = (await _create(api, workspace_ref=str(tmp_path)))["id"]
    async with execution_db() as db:
        assert "not started" not in await project_plan.card_text(db, pid)      # no plan yet: no stage line
    await _plan(api, pid)
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    await api.post(f"/api/v1/projects/{pid}/advance", json={"leftover": "drop"})
    async with execution_db() as db:
        card = await project_plan.card_text(db, pid)
    assert "reference data, not instructions" in card
    assert "Sluice (sample) (game)" in card and "Done means: On the App Store" in card
    assert 'level 2 of 4, "Prototype"' in card
    assert "Open checkpoints: Playable build; Fun test" in card
    assert f"Folder: {tmp_path}" in card
    assert len(card) <= project_plan.CARD_CHARS


async def test_an_archived_or_unknown_project_has_no_card(api, execution_db):
    project = await _create(api)
    await api.put(f"/api/v1/projects/{project['id']}", json={"expected_version": project["version"], "status": "archived",
                                                             "project": {"name": "x", "kind": "general"}})
    async with execution_db() as db:
        assert await project_plan.card_text(db, project["id"]) == ""
        assert await project_plan.card_text(db, "nope") == ""


async def test_a_turn_in_the_project_sees_the_card_and_one_outside_does_not(api, execution_db, monkeypatch):
    from server.orchestrator import arslan
    from server.services import personal_context as pc
    pid = (await _create(api))["id"]
    await _plan(api, pid)
    systems = []

    async def fake_run_native(**kw):
        systems.append(kw["system"])
        return {"answer": "ok"}

    monkeypatch.setattr(arslan.tool_loop, "run_native", fake_run_native)
    with pc.bind(pc.TaskMemoryContext(task_id="t1", run_id="r1", conversation_id="c1", model_is_local=True, project_id=pid)):
        await arslan._handle_answer_body("c1", "what next?", lambda ev: None)
    with pc.bind(pc.TaskMemoryContext(task_id="t2", run_id="r2", conversation_id="c2", model_is_local=True)):
        await arslan._handle_answer_body("c2", "what next?", lambda ev: None)
    assert "This conversation belongs to a project" in systems[0] and "Sluice (sample)" in systems[0]
    assert "This conversation belongs to a project" not in systems[1]


# ── a changed plan, proposed (§7) ────────────────────────────────────────────

async def _active_with_cleared_first(api):
    pid = (await _create(api))["id"]
    await _plan(api, pid)
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    await api.post(f"/api/v1/projects/{pid}/advance", json={"leftover": "drop"})                    # Idea cleared, Prototype current
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    await api.post(f"/api/v1/projects/{pid}/checkpoints/{plan['levels'][1]['checkpoints'][0]['id']}/tick")
    return pid


NEW_OPEN = [
    {"name": "Prototype", "band": "shaping", "checkpoints": [{"text": "Playable build"}, {"text": "Fun test"},
                                                            {"text": "Single-player only"}]},
    {"name": "Production", "band": "doing", "checkpoints": []},
    {"name": "Six more levels", "band": "doing", "checkpoints": []},
]


async def test_a_plan_proposal_shows_what_changes_and_waits(api, execution_db):
    from server.db.models import Project
    pid = await _active_with_cleared_first(api)
    async with execution_db() as db:
        project = await db.get(Project, pid)
        event = await project_plan.propose_plan(db, project, NEW_OPEN, "no online mode")
        await db.commit()
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    proposal = plan["plan_proposal"]
    assert proposal["id"] == event.id and proposal["reason"] == "no online mode" and proposal["cleared"] == 1
    assert {"op": "add", "level": "Six more levels", "band": "doing"} in proposal["diff"]
    assert {"op": "remove", "level": "Launch"} in proposal["diff"]
    assert {"op": "change", "level": "Prototype", "added": ["Single-player only"], "removed": [], "band": None} in proposal["diff"]
    # Nothing changed yet.
    assert [lv["name"] for lv in plan["levels"]] == ["Idea", "Prototype", "Production", "Launch"]


async def test_taking_the_new_plan_keeps_cleared_levels_ticks_and_the_current_level(api, execution_db):
    from server.db.models import Project
    pid = await _active_with_cleared_first(api)
    before = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    async with execution_db() as db:
        project = await db.get(Project, pid)
        event = await project_plan.propose_plan(db, project, NEW_OPEN, "no online mode")
        await db.commit()
    after = (await api.post(f"/api/v1/projects/{pid}/plan-proposals/{event.id}/accept")).json()
    assert [lv["name"] for lv in after["levels"]] == ["Idea", "Prototype", "Production", "Six more levels"]
    assert after["levels"][0]["state"] == "cleared" and after["levels"][0]["id"] == before["levels"][0]["id"]
    proto = after["levels"][1]
    assert proto["id"] == before["levels"][1]["id"] and proto["state"] == "current"
    assert proto["started_at"] == before["levels"][1]["started_at"]
    assert [cp["state"] for cp in proto["checkpoints"]] == ["done", "todo", "todo"]
    assert after["plan_proposal"] is None
    again = await api.post(f"/api/v1/projects/{pid}/plan-proposals/{event.id}/accept")
    assert again.status_code == 409


async def test_a_newer_proposal_replaces_the_older_and_declining_changes_nothing(api, execution_db):
    from server.db.models import Project
    pid = await _active_with_cleared_first(api)
    async with execution_db() as db:
        project = await db.get(Project, pid)
        first = await project_plan.propose_plan(db, project, NEW_OPEN, "one")
        second = await project_plan.propose_plan(db, project, NEW_OPEN[:2], "two")
        await db.commit()
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    assert plan["plan_proposal"]["id"] == second.id
    assert (await api.post(f"/api/v1/projects/{pid}/plan-proposals/{first.id}/accept")).status_code == 409
    after = (await api.post(f"/api/v1/projects/{pid}/plan-proposals/{second.id}/decline")).json()
    assert [lv["name"] for lv in after["levels"]] == ["Idea", "Prototype", "Production", "Launch"]


async def test_the_same_plan_is_not_a_proposal(api, execution_db):
    from server.db.models import Project
    pid = await _active_with_cleared_first(api)
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    same = [{"name": lv["name"], "band": lv["band"], "checkpoints": [{"text": c["text"]} for c in lv["checkpoints"]]}
            for lv in plan["levels"][1:]]
    async with execution_db() as db:
        project = await db.get(Project, pid)
        with pytest.raises(project_plan.PlanError, match="plan_unchanged"):
            await project_plan.propose_plan(db, project, same)


async def test_the_tool_records_the_proposal_and_shows_the_card(api, execution_db):
    from server.orchestrator import tool_loop
    from server.services import personal_context as pc
    pid = await _active_with_cleared_first(api)
    frames = []
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c", model_is_local=True, project_id=pid)):
        result = await tool_loop._propose_plan_change({"levels": NEW_OPEN, "reason": "no online mode"}, frames.append)
    assert result["ok"] is True
    (frame,) = frames
    assert frame["type"] == "plan_proposed" and frame["project_id"] == pid and frame["proposal_id"] == result["proposal_id"]
    assert any(line["op"] == "add" for line in frame["diff"])
    with pc.bind(pc.TaskMemoryContext(task_id="t2", run_id="r2", conversation_id="c2", model_is_local=True)):
        assert (await tool_loop._propose_plan_change({"levels": NEW_OPEN}, frames.append))["ok"] is False
    assert len(frames) == 1


async def test_the_tool_is_offered_only_in_a_project_conversation(api, execution_db):
    from server.orchestrator import arslan
    from server.services import personal_context as pc
    pid = (await _create(api))["id"]
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c", model_is_local=True, project_id=pid)):
        assert "propose_plan_change" in {t["key"] for t in await arslan._arslan_tools()}
    with pc.bind(pc.TaskMemoryContext(task_id="t2", run_id="r2", conversation_id="c2", model_is_local=True)):
        assert "propose_plan_change" not in {t["key"] for t in await arslan._arslan_tools()}


# ── the model's draft (§3.2), adapter stubbed ────────────────────────────────

class _Reply:
    def __init__(self, content):
        self.content = content


def _stub(monkeypatch, content=None, error=None):
    from server.services import project_drafter
    calls = []

    class Adapter:
        async def chat(self, system, user, **kw):
            calls.append({"system": system, "user": user})
            if error:
                raise error
            return _Reply(content)
    monkeypatch.setattr(project_drafter, "_get_adapter", lambda: Adapter())
    return calls


GOOD = {"levels": [
    {"name": "Pitch", "band": "shaping", "description": "One line", "clear_condition": "You approve the pitch",
     "checkpoints": [{"text": "Write the pitch", "expects": None}]},
    {"name": "Look approved", "band": "shaping", "habit": True, "clear_condition": "You approve the key art",
     "checkpoints": []},
    {"name": "Build", "band": "doing", "checkpoints": [{"text": "First level", "expects": {"kind": "file", "pattern": "levels/*.json"}}]},
    {"name": "Launch", "band": "done", "clear_condition": "On the App Store", "checkpoints": []},
]}


async def test_without_refine_no_model_is_called(api, monkeypatch):
    calls = _stub(monkeypatch, content="{}")
    body = (await api.post("/api/v1/projects/draft", json={"template": "game", "finish_line": "x"})).json()
    assert body["source"] == "template" and calls == []


async def test_refine_uses_the_models_levels_when_they_hold_the_rules(api, execution_db, monkeypatch):
    import json as _json

    from server.db.models import ProjectHabit
    async with execution_db() as db:
        db.add(ProjectHabit(id="h1", template="game", kind="plan_rule", text="Approve the look before building",
                            sources=[], enabled=True))
        db.add(ProjectHabit(id="h2", template="game", kind="plan_rule", text="SWITCHED OFF RULE", sources=[], enabled=False))
        db.add(ProjectHabit(id="h3", template="trip", kind="plan_rule", text="OTHER TYPE RULE", sources=[], enabled=True))
        await db.commit()
    calls = _stub(monkeypatch, content=_json.dumps(GOOD))
    body = (await api.post("/api/v1/projects/draft", json={"template": "game", "finish_line": "On the App Store",
                                                             "lang": "zh", "refine": True})).json()
    assert body["source"] == "model"
    assert [lv["name"] for lv in body["levels"]] == ["Pitch", "Look approved", "Build", "Launch"]
    assert body["levels"][1]["habit"] is True
    assert body["levels"][2]["checkpoints"][0]["expects"] == {"kind": "file", "pattern": "levels/*.json", "min": 1}
    (call,) = calls
    assert "Simplified Chinese" in call["system"]
    sent = _json.loads(call["user"])
    assert sent["plan_rules"] == ["Approve the look before building"]
    assert sent["finish_line"] == "On the App Store" and sent["levels"][0]["name"] == "点子"


@pytest.mark.parametrize("content, error", [
    ('{"levels": [{"name": "Only", "band": "done"}]}', None),                                  # too few
    ('{"levels": [{"name": "A", "band": "doing"}, {"name": "B", "band": "shaping"}, {"name": "C", "band": "done"}]}', None),
    ('{"levels": [{"name": "A", "band": "shaping"}, {"name": "B", "band": "doing"}, {"name": "C", "band": "doing"}]}', None),
    ("not json at all", None),
    (None, RuntimeError("no model configured")),
])
async def test_a_reply_that_breaks_the_rules_keeps_the_draft(api, monkeypatch, content, error):
    _stub(monkeypatch, content=content, error=error)
    given = [{"name": "Mine", "band": "shaping", "checkpoints": []}, {"name": "End", "band": "done", "checkpoints": []}]
    body = (await api.post("/api/v1/projects/draft", json={"template": "game", "refine": True, "levels": given})).json()
    assert body["refine_failed"] is True and body["source"] == "template"
    assert [lv["name"] for lv in body["levels"]] == ["Mine", "End"]


# ── 0.1.58 §5: clearing a level early is honest about what was left ──────────

async def _active_game(api):
    pid = (await _create(api))["id"]
    await _plan(api, pid)
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    return pid


async def test_clearing_with_open_checkpoints_asks_first(api):
    pid = await _active_game(api)
    response = await api.post(f"/api/v1/projects/{pid}/advance")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "open_checkpoints" and [o["text"] for o in detail["open"]] == ["One-line pitch"]
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    assert plan["levels"][0]["state"] == "current"          # nothing moved


async def test_move_puts_the_open_ones_first_in_the_next_level_and_undo_puts_them_back(api):
    pid = await _active_game(api)
    before = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    pitch = before["levels"][0]["checkpoints"][0]["id"]
    plan = (await api.post(f"/api/v1/projects/{pid}/advance", json={"leftover": "move", "note": "pitch later"})).json()
    assert [cp["text"] for cp in plan["levels"][1]["checkpoints"]] == ["One-line pitch", "Playable build", "Fun test"]
    assert plan["levels"][0]["checkpoints"] == []
    advance = next(e for e in (await api.get(f"/api/v1/projects/{pid}/events")).json() if e["kind"] == "advance")
    assert advance["actor"] == "user" and advance["payload"]["evidence"] == {"kind": "user_note", "text": "pitch later"}
    plan = (await api.post(f"/api/v1/projects/{pid}/events/{advance['id']}/undo")).json()
    assert [cp["id"] for cp in plan["levels"][0]["checkpoints"]] == [pitch]
    assert [cp["text"] for cp in plan["levels"][1]["checkpoints"]] == ["Playable build", "Fun test"]
    assert [lv["state"] for lv in plan["levels"]][:2] == ["current", "todo"]


async def test_drop_deletes_them_and_undo_brings_them_back_with_their_ids(api):
    pid = await _active_game(api)
    await api.post(f"/api/v1/projects/{pid}/advance")                                   # refused, nothing changes
    await api.post(f"/api/v1/projects/{pid}/advance", json={"leftover": "move"})         # Idea → Prototype
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    ids = [cp["id"] for cp in plan["levels"][1]["checkpoints"]]
    plan = (await api.post(f"/api/v1/projects/{pid}/advance", json={"leftover": "drop"})).json()
    assert plan["levels"][1]["checkpoints"] == [] and plan["levels"][2]["state"] == "current"
    advance = [e for e in (await api.get(f"/api/v1/projects/{pid}/events")).json() if e["kind"] == "advance"][0]
    assert len(advance["payload"]["dropped"]) == 3
    plan = (await api.post(f"/api/v1/projects/{pid}/events/{advance['id']}/undo")).json()
    assert [cp["id"] for cp in plan["levels"][1]["checkpoints"]] == ids


async def test_everything_done_clears_without_a_question(api):
    pid = await _active_game(api)
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    await api.post(f"/api/v1/projects/{pid}/checkpoints/{plan['levels'][0]['checkpoints'][0]['id']}/tick")
    response = await api.post(f"/api/v1/projects/{pid}/advance")
    assert response.status_code == 200 and response.json()["levels"][1]["state"] == "current"


async def test_move_on_the_last_level_is_refused(api):
    pid = (await _create(api))["id"]
    await _plan(api, pid, [{"name": "Only", "band": "done", "checkpoints": [{"text": "Ship"}]}])
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    response = await api.post(f"/api/v1/projects/{pid}/advance", json={"leftover": "move"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "no_next_level"


async def test_accepting_arslans_proposal_with_open_checkpoints_asks_the_same_question(api, execution_db):
    pid, proposal = await _ready_with_proposal(api, execution_db)
    card = (await api.get("/api/v1/projects/board")).json()["cards"][0]
    assert [o["text"] for o in card["proposal"]["open"]] == ["One-line pitch"]
    response = await api.post(f"/api/v1/projects/{pid}/proposals/{proposal}/accept")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "open_checkpoints"
    plan = (await api.post(f"/api/v1/projects/{pid}/proposals/{proposal}/accept", json={"leftover": "move"})).json()
    assert plan["levels"][1]["state"] == "current"
    assert plan["levels"][1]["checkpoints"][0]["text"] == "One-line pitch"
