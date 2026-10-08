"""A project's plan: levels, checkpoints, and how they move (0.1.56).

Rules (spec §1, §4, §5):
- The board column is DERIVED: Idea until a level starts; then the band of the current
  level (a current level in the Done band still shows in Doing); Done and Dropped are
  only ever set by the user.
- Small ticks may be automatic (with evidence, undoable); clearing a level by Arslan is a
  PROPOSAL the user accepts or declines — unless the user turned auto-advance on after the
  shadow streak reached 10. Done/Dropped are never automatic.
- Nothing here bumps `projects.version`: that column pins running tasks
  (task_repository: task_project_changed). The plan has its own `plan_version`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update

from server.db.models import Project, ProjectCheckpoint, ProjectEvent, ProjectLevel

COLUMNS = ("idea", "shaping", "doing", "done", "dropped")
STAGES = ("idea", "active", "done", "dropped")
SHADOW_STREAK_TO_ASK = 10
ACTIVITY_EVERY = timedelta(hours=1)


class PlanError(Exception):
    """A refused plan operation; `code` is what the API returns."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _id() -> str:
    return str(uuid.uuid4())


def _iso(value):
    return value.isoformat() + "Z" if value else None


def stage_of(project: Project) -> str:
    return project.stage if project.stage in STAGES else "idea"


def column_of(stage: str, levels: list[dict]) -> str:
    """The board column, as a pure function of the stage and the levels' states/bands."""
    if stage in ("done", "dropped"):
        return stage
    if stage != "active":
        return "idea"
    current = next((lv for lv in levels if lv["state"] == "current"), None)
    if current is None:
        # Every level cleared but not marked Done by the user: still being finished.
        return "doing" if levels and all(lv["state"] == "cleared" for lv in levels) else "shaping"
    return "shaping" if current["band"] == "shaping" else "doing"


# ── reading ────────────────────────────────────────────────────────────────────

async def levels_of(db, project_id: str) -> list[ProjectLevel]:
    return list((await db.execute(select(ProjectLevel).where(ProjectLevel.project_id == project_id)
                                  .order_by(ProjectLevel.position))).scalars().all())


async def checkpoints_of(db, level_ids: list[str]) -> dict[str, list[ProjectCheckpoint]]:
    if not level_ids:
        return {}
    rows = (await db.execute(select(ProjectCheckpoint).where(ProjectCheckpoint.level_id.in_(level_ids))
                             .order_by(ProjectCheckpoint.position))).scalars().all()
    out: dict[str, list[ProjectCheckpoint]] = {}
    for row in rows:
        out.setdefault(row.level_id, []).append(row)
    return out


def _checkpoint(row: ProjectCheckpoint) -> dict:
    return {"id": row.id, "text": row.text, "expects": row.expects, "state": row.state, "progress": row.progress,
            "evidence": row.evidence, "done_at": _iso(row.done_at), "done_by": row.done_by}


def _level(row: ProjectLevel, checkpoints: list[ProjectCheckpoint]) -> dict:
    return {"id": row.id, "position": row.position, "name": row.name, "description": row.description,
            "band": row.band, "clear_condition": row.clear_condition, "state": row.state, "habit": bool(row.habit),
            "started_at": _iso(row.started_at), "cleared_at": _iso(row.cleared_at),
            "checkpoints": [_checkpoint(c) for c in checkpoints]}


async def plan_of(db, project: Project) -> dict:
    levels = await levels_of(db, project.id)
    cps = await checkpoints_of(db, [lv.id for lv in levels])
    shaped = [_level(lv, cps.get(lv.id, [])) for lv in levels]
    return {"project_id": project.id, "version": project.plan_version or 0, "stage": stage_of(project),
            "paused": bool(project.paused), "column": column_of(stage_of(project), shaped), "levels": shaped}


# ── writing ────────────────────────────────────────────────────────────────────

async def _bump_plan(db, project: Project, expected: int | None = None) -> None:
    """Advance the plan's own version (never `projects.version`)."""
    current = project.plan_version or 0
    if expected is not None and expected != current:
        raise PlanError("plan_version_conflict")
    statement = update(Project).where(Project.id == project.id)
    statement = statement.where(Project.plan_version.is_(None) if current == 0 else Project.plan_version == current)
    result = await db.execute(statement.values(plan_version=current + 1).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise PlanError("plan_version_conflict")
    project.plan_version = current + 1


async def _event(db, project_id: str, kind: str, actor: str, payload: dict | None = None,
                 outcome: str | None = None, undo_of: str | None = None) -> ProjectEvent:
    row = ProjectEvent(id=_id(), project_id=project_id, kind=kind, actor=actor, payload=payload or {},
                       outcome=outcome, undo_of=undo_of, created_at=datetime.utcnow())
    db.add(row)
    await db.flush()
    return row


def _clean_level(raw: dict) -> dict:
    name = str(raw.get("name") or "").strip()[:120]
    band = raw.get("band")
    if not name or band not in ("shaping", "doing", "done"):
        raise PlanError("invalid_level")
    cps = raw.get("checkpoints") or []
    if not isinstance(cps, list) or len(cps) > 12:
        raise PlanError("invalid_checkpoints")
    clean_cps = []
    for cp in cps:
        text = str((cp or {}).get("text") or "").strip()[:200]
        if not text:
            raise PlanError("invalid_checkpoints")
        expects = cp.get("expects")
        if expects is not None and not (isinstance(expects, dict) and expects.get("kind") == "file"
                                        and isinstance(expects.get("pattern"), str) and expects["pattern"].strip()):
            raise PlanError("invalid_expects")
        clean_cps.append({"id": cp.get("id"), "text": text, "expects": expects})
    return {"id": raw.get("id"), "name": name, "band": band,
            "description": str(raw.get("description") or "").strip()[:300],
            "clear_condition": str(raw.get("clear_condition") or "").strip()[:400],
            "habit": bool(raw.get("habit")), "checkpoints": clean_cps}


async def put_plan(db, project: Project, expected_version: int, levels_in: list[dict], *, actor: str = "user") -> dict:
    """Replace the levels that are not cleared. Cleared levels are history: they stay first,
    unchanged, whatever the request says. A checkpoint keeps its done state when its id is kept."""
    if not isinstance(levels_in, list) or not 1 <= len(levels_in) <= 15:
        raise PlanError("invalid_plan")
    existing = await levels_of(db, project.id)
    old_cps = await checkpoints_of(db, [lv.id for lv in existing])
    cleared = [lv for lv in existing if lv.state == "cleared"]
    cleared_ids = {lv.id for lv in cleared}
    incoming = [_clean_level(raw) for raw in levels_in if raw.get("id") not in cleared_ids]
    if not incoming and not cleared:
        raise PlanError("invalid_plan")
    had_plan = bool(existing)
    await _bump_plan(db, project, expected_version)
    current_before = next((lv for lv in existing if lv.state == "current"), None)
    old_by_id = {lv.id: lv for lv in existing if lv.id not in cleared_ids}
    old_cp_by_id = {cp.id: cp for lv in existing for cp in old_cps.get(lv.id, [])}
    # Drop the open levels and their checkpoints; re-create from the request.
    for lv in existing:
        if lv.id in cleared_ids:
            continue
        for cp in old_cps.get(lv.id, []):
            await db.delete(cp)
        await db.delete(lv)
    await db.flush()
    position = len(cleared)
    active = stage_of(project) == "active"
    for i, raw in enumerate(incoming):
        previous = old_by_id.get(raw["id"]) if raw["id"] else None
        is_current = active and i == 0
        level = ProjectLevel(
            id=raw["id"] if previous else _id(), project_id=project.id, position=position, name=raw["name"],
            description=raw["description"], band=raw["band"], clear_condition=raw["clear_condition"],
            state="current" if is_current else "todo", habit=raw["habit"],
            started_at=(previous.started_at if previous and previous.started_at and is_current
                        else (datetime.utcnow() if is_current else None)))
        if is_current and current_before is not None and current_before.id == level.id:
            level.started_at = current_before.started_at
        db.add(level)
        await db.flush()
        for j, cp in enumerate(raw["checkpoints"]):
            old = old_cp_by_id.get(cp["id"]) if cp["id"] else None
            db.add(ProjectCheckpoint(
                id=cp["id"] if old else _id(), level_id=level.id, position=j, text=cp["text"], expects=cp["expects"],
                state=old.state if old else "todo", progress=old.progress if old else None,
                evidence=old.evidence if old else None, done_at=old.done_at if old else None,
                done_by=old.done_by if old else None))
        position += 1
    await db.flush()
    if had_plan:
        await _event(db, project.id, "plan_change", actor, {"levels": len(incoming)})
    return await plan_of(db, project)


async def start(db, project: Project, *, actor: str, reason: str) -> bool:
    """Idea → active: the first open level becomes current. False when nothing to start."""
    if stage_of(project) != "idea":
        return False
    levels = await levels_of(db, project.id)
    first = next((lv for lv in levels if lv.state != "cleared"), None)
    if first is None:
        return False
    first.state = "current"
    first.started_at = datetime.utcnow()
    project.stage = "active"
    await _event(db, project.id, "stage", actor, {"to": "active", "reason": reason})
    await _bump_plan(db, project)
    return True


async def note_activity(db, project_id: str) -> None:
    """Something happened in the project (a turn in its conversation, a file). A project in
    Idea with a plan starts (spec: the first conversation or file moves it to Shaping)."""
    project = await db.get(Project, project_id)
    if project is None or project.status != "active":
        return
    if stage_of(project) == "idea":
        await start(db, project, actor="arslan", reason="first_activity")
    last = (await db.execute(select(ProjectEvent.created_at).where(
        ProjectEvent.project_id == project_id, ProjectEvent.kind == "activity",
    ).order_by(ProjectEvent.created_at.desc()).limit(1))).scalar()
    if last is None or datetime.utcnow() - last >= ACTIVITY_EVERY:
        await _event(db, project_id, "activity", "arslan")


async def _checkpoint_in(db, project: Project, checkpoint_id: str) -> tuple[ProjectCheckpoint, ProjectLevel]:
    cp = await db.get(ProjectCheckpoint, checkpoint_id)
    level = await db.get(ProjectLevel, cp.level_id) if cp else None
    if cp is None or level is None or level.project_id != project.id:
        raise PlanError("checkpoint_not_found")
    return cp, level


async def tick(db, project: Project, checkpoint_id: str, *, actor: str, evidence: dict | None = None) -> ProjectEvent | None:
    """Tick a checkpoint. Arslan's ticks need evidence. When Arslan's tick completes the
    current level, a proposal (or, with auto-advance, an advance) follows."""
    cp, level = await _checkpoint_in(db, project, checkpoint_id)
    if actor == "arslan" and not evidence:
        raise PlanError("evidence_required")
    if cp.state == "done":
        return None
    cp.state, cp.done_at, cp.done_by, cp.evidence = "done", datetime.utcnow(), actor, evidence
    event = await _event(db, project.id, "tick", actor, {"checkpoint_id": cp.id, "text": cp.text,
                                                        "level_id": level.id, "evidence": evidence})
    await _bump_plan(db, project)
    if actor == "arslan" and level.state == "current":
        siblings = (await checkpoints_of(db, [level.id])).get(level.id, [])
        if siblings and all(s.state == "done" for s in siblings):
            await propose_advance(db, project, evidence={"kind": "checkpoints", "level_id": level.id})
    return event


async def untick(db, project: Project, checkpoint_id: str, *, actor: str = "user") -> None:
    cp, level = await _checkpoint_in(db, project, checkpoint_id)
    if cp.state != "done":
        return
    cp.state, cp.done_at, cp.done_by, cp.evidence = "todo", None, None, None
    await _event(db, project.id, "untick", actor, {"checkpoint_id": cp.id, "text": cp.text, "level_id": level.id})
    await _bump_plan(db, project)


async def _current_and_next(db, project: Project) -> tuple[ProjectLevel | None, ProjectLevel | None]:
    levels = await levels_of(db, project.id)
    for i, lv in enumerate(levels):
        if lv.state == "current":
            return lv, (levels[i + 1] if i + 1 < len(levels) else None)
    return None, None


async def open_proposal(db, project_id: str) -> ProjectEvent | None:
    return (await db.execute(select(ProjectEvent).where(
        ProjectEvent.project_id == project_id, ProjectEvent.kind == "proposal", ProjectEvent.outcome.is_(None),
    ).order_by(ProjectEvent.created_at.desc()).limit(1))).scalar()


async def propose_advance(db, project: Project, *, evidence: dict) -> ProjectEvent | None:
    """Arslan thinks the current level is cleared. One open proposal at a time; with
    auto-advance on (§5) it advances instead, logged and undoable."""
    current, nxt = await _current_and_next(db, project)
    if current is None or stage_of(project) != "active":
        return None
    if await open_proposal(db, project.id):
        return None
    payload = {"level_id": current.id, "level": current.name, "next_level_id": nxt.id if nxt else None,
               "next": nxt.name if nxt else None, "evidence": evidence,
               "moves_column": bool(nxt) and _column_band(nxt.band) != _column_band(current.band),
               "last": nxt is None}
    if nxt is not None and await auto_advance_enabled(db):
        return await advance(db, project, actor="arslan", evidence=evidence)
    return await _event(db, project.id, "proposal", "arslan", payload)


def _column_band(band: str) -> str:
    return "shaping" if band == "shaping" else "doing"


async def advance(db, project: Project, *, actor: str, evidence: dict | None = None,
                  proposal: ProjectEvent | None = None) -> ProjectEvent:
    current, nxt = await _current_and_next(db, project)
    if current is None:
        raise PlanError("no_current_level")
    now = datetime.utcnow()
    current.state, current.cleared_at = "cleared", now
    if nxt is not None:
        nxt.state, nxt.started_at = "current", now
    event = await _event(db, project.id, "advance", actor, {
        "level_id": current.id, "level": current.name, "next_level_id": nxt.id if nxt else None,
        "next": nxt.name if nxt else None, "evidence": evidence, "proposal_id": proposal.id if proposal else None})
    await _bump_plan(db, project)
    return event


async def decide(db, project: Project, proposal_id: str, accept: bool) -> ProjectEvent | None:
    proposal = await db.get(ProjectEvent, proposal_id)
    if proposal is None or proposal.project_id != project.id or proposal.kind != "proposal":
        raise PlanError("proposal_not_found")
    if proposal.outcome is not None:
        raise PlanError("proposal_decided")
    current, _ = await _current_and_next(db, project)
    if current is None or current.id != proposal.payload.get("level_id"):
        # The plan moved on (the user cleared it by hand, or re-planned): the proposal no
        # longer applies. Not a decline — it does not count for the shadow streak.
        proposal.outcome = "stale"
        await _bump_plan(db, project)
        return None
    proposal.outcome = "accepted" if accept else "declined"
    if not accept:
        await _bump_plan(db, project)
        return None
    if proposal.payload.get("last"):
        await _bump_plan(db, project)          # "the last level's condition is met": Done stays the user's
        return None
    return await advance(db, project, actor="user", evidence=proposal.payload.get("evidence"), proposal=proposal)


async def undo(db, project: Project, event_id: str) -> None:
    """Reverse one of Arslan's ticks or advances, or an accepted advance. An undone
    advance counts as a miss for the shadow streak."""
    event = await db.get(ProjectEvent, event_id)
    if event is None or event.project_id != project.id or event.kind not in ("tick", "advance"):
        raise PlanError("event_not_undoable")
    if event.outcome == "undone":
        return
    if event.kind == "tick":
        await untick(db, project, event.payload["checkpoint_id"], actor="user")
    else:
        latest = (await db.execute(select(ProjectEvent).where(
            ProjectEvent.project_id == project.id, ProjectEvent.kind == "advance",
            ProjectEvent.outcome.is_(None)).order_by(ProjectEvent.created_at.desc()).limit(1))).scalar()
        if latest is None or latest.id != event.id:
            raise PlanError("only_latest_advance")
        cleared = await db.get(ProjectLevel, event.payload["level_id"])
        nxt = await db.get(ProjectLevel, event.payload["next_level_id"]) if event.payload.get("next_level_id") else None
        if cleared is not None:
            cleared.state, cleared.cleared_at = "current", None
        if nxt is not None:
            nxt.state, nxt.started_at = "todo", None
        proposal_id = event.payload.get("proposal_id")
        if proposal_id:
            proposal = await db.get(ProjectEvent, proposal_id)
            if proposal is not None:
                proposal.outcome = "undone"
        await _bump_plan(db, project)
    event.outcome = "undone"
    await db.flush()


async def set_stage(db, project: Project, *, stage: str | None = None, paused: bool | None = None) -> None:
    """The user's own moves: Done, Dropped, back to active, pause. Never called by Arslan."""
    if stage is not None:
        if stage not in ("active", "done", "dropped"):
            raise PlanError("invalid_stage")
        before = stage_of(project)
        if stage == "active" and before == "idea":
            if not await start(db, project, actor="user", reason="started"):
                raise PlanError("no_levels")
        else:
            project.stage = stage
            project.done_at = datetime.utcnow() if stage == "done" else None
            await _event(db, project.id, "stage", "user", {"from": before, "to": stage})
            await _bump_plan(db, project)
    if paused is not None and bool(project.paused) != paused:
        project.paused = paused
        await _event(db, project.id, "stage", "user", {"paused": paused})
        await _bump_plan(db, project)


# ── shadow mode (§5) ───────────────────────────────────────────────────────────

@dataclass
class Shadow:
    proposed: int
    accepted: int
    streak: int
    asked: bool


async def shadow(db) -> Shadow:
    """Over every project: how many level-clear proposals, how many accepted, and the
    current run of accepted ones (a decline or an undo after acceptance resets it)."""
    rows = (await db.execute(select(ProjectEvent.outcome).where(
        ProjectEvent.kind == "proposal", ProjectEvent.outcome.in_(("accepted", "declined", "undone")),
    ).order_by(ProjectEvent.created_at))).scalars().all()
    streak = 0
    for outcome in rows:
        streak = streak + 1 if outcome == "accepted" else 0
    asked = (await db.execute(select(ProjectEvent.id).where(ProjectEvent.kind == "auto_ask").limit(1))).scalar() is not None
    return Shadow(proposed=len(rows), accepted=sum(1 for o in rows if o == "accepted"), streak=streak, asked=asked)


async def auto_advance_enabled(db) -> bool:
    from server.services import settings_service
    raw = await settings_service._get_raw(db, "projects_auto_advance")
    return str(raw).strip().lower() == "true" if raw is not None else False


# ── the board ──────────────────────────────────────────────────────────────────

async def board(db, owner_id: str = "local") -> dict:
    projects = (await db.execute(select(Project).where(Project.owner_id == owner_id)
                                 .order_by(Project.updated_at.desc(), Project.id))).scalars().all()
    cards = []
    for project in projects:
        if project.status != "active":
            continue
        plan = await plan_of(db, project)
        levels = plan["levels"]
        current = next((lv for lv in levels if lv["state"] == "current"), None)
        proposal = await open_proposal(db, project.id)
        cards.append({
            "id": project.id, "name": project.name, "template": project.template, "kind": project.kind,
            "finish_line": project.finish_line, "stage": plan["stage"], "paused": plan["paused"],
            "column": plan["column"], "levels": [{"name": lv["name"], "band": lv["band"], "state": lv["state"]} for lv in levels],
            "current": ({"position": current["position"] + 1, "name": current["name"], "started_at": current["started_at"]}
                        if current else None),
            "left": sum(1 for lv in levels if lv["state"] != "cleared"),
            "proposal": ({"id": proposal.id, **proposal.payload} if proposal else None),
            "done_at": _iso(project.done_at), "has_plan": bool(levels),
        })
    s = await shadow(db)
    archived = sum(1 for p in projects if p.status == "archived")
    return {"cards": cards, "counts": {"paused": sum(1 for c in cards if c["paused"]), "archived": archived},
            "shadow": {"proposed": s.proposed, "accepted": s.accepted, "streak": s.streak,
                       "ask_at": SHADOW_STREAK_TO_ASK, "asked": s.asked,
                       "auto_advance": await auto_advance_enabled(db)}}
