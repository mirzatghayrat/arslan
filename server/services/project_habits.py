"""What Arslan learns about how the user moves projects (0.1.56 §6, §9).

- Plan rules: written by Arslan, active at once, visible and switchable on the habits sheet;
  used only when drafting levels (project_drafter.plan_rules). Three ways in:
  (a) the user adds a level of the same name to two projects of one type,
  (b) re-plans cut planned checkpoints mid-way in two projects of one type,
  (c) the optional line on a declined proposal.
- Pace: median days per level by type and band, computed from cleared levels, never stored
  as text; an override per type and band is stored. Shown only with >= PACE_MIN_LEVELS.
- Stalled: no activity for more than STALL_DAYS, or more than twice the usual for the current
  level when the pace is known. Shown quietly on the card, never notified.

Everything here stays local; rules reach a model only inside a drafting request the user started.
"""
from __future__ import annotations

import statistics
import uuid
from datetime import datetime

from sqlalchemy import func, select

from server.db.models import Project, ProjectEvent, ProjectHabit, ProjectLevel
from server.services import project_templates

PACE_MIN_LEVELS = 3
MIN_STOCK = 2                 # template levels a plan must keep for its other levels to count as added
STALL_DAYS = 21
STALL_FLOOR_DAYS = 3          # "twice the usual" never marks a gap shorter than this
RULE_CHARS = 300


def _norm(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def _template_names(template: str | None) -> set[str]:
    levels = project_templates.TEMPLATES.get(template or "", [])
    return {_norm(n) for _band, names in levels for n in names.values()}


async def _rule(db, owner_id: str, template: str | None, code: str, key: str | None = None) -> ProjectHabit | None:
    rows = (await db.execute(select(ProjectHabit).where(
        ProjectHabit.owner_id == owner_id, ProjectHabit.kind == "plan_rule", ProjectHabit.template == template,
    ))).scalars().all()
    for row in rows:
        value = row.value or {}
        if value.get("code") == code and (key is None or value.get("key") == key):
            return row
    return None


async def add_rule(db, *, owner_id: str, template: str | None, text: str, value: dict,
                   sources: list[str]) -> ProjectHabit:
    row = ProjectHabit(id=uuid.uuid4().hex, owner_id=owner_id, template=template, kind="plan_rule",
                       text=text[:RULE_CHARS], value=value, sources=sources, enabled=True,
                       created_at=datetime.utcnow())
    db.add(row)
    await db.flush()
    return row


async def learn_from_plan(db, project: Project, levels: list[dict], *, actor: str, cut_mid_way: bool) -> None:
    """(a) and (b), after a plan is saved. Only projects with a type can teach a type's rule.

    (a) counts a level as the user's addition only in a plan built on the type's template (at
    least MIN_STOCK of its levels are still there): a plan written from scratch would make
    every level "added". Levels a rule put there (habit) are not additions either."""
    template = project.template
    if not template:
        return
    owner = project.owner_id
    if actor == "user":
        stock = _template_names(template)
        if sum(1 for lv in levels if _norm(lv["name"]) in stock) < MIN_STOCK:
            levels = []
        elsewhere = (await db.execute(select(Project.id, ProjectLevel.name).join(
            ProjectLevel, ProjectLevel.project_id == Project.id).where(
            Project.owner_id == owner, Project.template == template, Project.id != project.id))).all()
        for name in dict.fromkeys(lv["name"].strip() for lv in levels if not lv.get("habit")):
            key = _norm(name)
            if not key or key in stock or await _rule(db, owner, template, "add_level", key):
                continue
            # Named as the user first wrote it, in the earlier project.
            other = next(((pid, n) for pid, n in elsewhere if _norm(n) == key), None)
            if other is not None:
                first = other[1].strip()
                await add_rule(db, owner_id=owner, template=template, text=f'Include a level "{first}".',
                               value={"code": "add_level", "key": key, "name": first}, sources=[other[0], project.id])
    if cut_mid_way and not await _rule(db, owner, template, "cut_scope"):
        cut = (await db.execute(select(ProjectEvent.project_id).join(Project, Project.id == ProjectEvent.project_id).where(
            Project.owner_id == owner, Project.template == template, ProjectEvent.kind == "plan_change",
        ))).all()
        projects = list(dict.fromkeys(pid for (pid,) in cut))
        counted = []
        for pid in projects:
            events = (await db.execute(select(ProjectEvent.payload).where(
                ProjectEvent.project_id == pid, ProjectEvent.kind == "plan_change"))).scalars().all()
            if any((p or {}).get("removed_checkpoints") for p in events):
                counted.append(pid)
        if len(counted) >= 2:
            await add_rule(db, owner_id=owner, template=template,
                           text="Keep the first version small: in earlier projects of this type, planned work "
                                "was cut mid-way.", value={"code": "cut_scope"}, sources=counted[:5])


async def learn_from_decline(db, project: Project, note: str) -> None:
    """(c) the user's own words on a decline become a rule for this type, as said."""
    await add_rule(db, owner_id=project.owner_id, template=project.template, text=note,
                   value={"code": "note"}, sources=[project.id])


# ── pace ─────────────────────────────────────────────────────────────────────

async def _overrides(db, owner_id: str) -> dict[tuple[str, str], float]:
    rows = (await db.execute(select(ProjectHabit).where(
        ProjectHabit.owner_id == owner_id, ProjectHabit.kind == "pace_override"))).scalars().all()
    out = {}
    for row in rows:
        value = row.value or {}
        if row.template and value.get("band") and isinstance(value.get("days"), (int, float)):
            out[(row.template, value["band"])] = float(value["days"])
    return out


async def pace(db, owner_id: str = "local") -> list[dict]:
    """Median days per level by type and band, from cleared levels; with the user's override."""
    rows = (await db.execute(select(Project.template, ProjectLevel.band, ProjectLevel.started_at, ProjectLevel.cleared_at)
                             .join(Project, Project.id == ProjectLevel.project_id).where(
        Project.owner_id == owner_id, Project.template.is_not(None), ProjectLevel.state == "cleared",
        ProjectLevel.started_at.is_not(None), ProjectLevel.cleared_at.is_not(None)))).all()
    groups: dict[tuple[str, str], list[float]] = {}
    for template, band, started, cleared in rows:
        groups.setdefault((template, band), []).append(max(0.0, (cleared - started).total_seconds() / 86400))
    overrides = await _overrides(db, owner_id)
    out = []
    for key in sorted(set(groups) | set(overrides)):
        days = groups.get(key, [])
        median = round(statistics.median(days), 1) if len(days) >= PACE_MIN_LEVELS else None
        out.append({"template": key[0], "band": key[1], "levels": len(days), "median_days": median,
                    "override_days": overrides.get(key)})
    return out


async def usual_days(db, owner_id: str, template: str | None, band: str) -> float | None:
    if not template:
        return None
    for row in await pace(db, owner_id):
        if row["template"] == template and row["band"] == band:
            return row["override_days"] if row["override_days"] is not None else row["median_days"]
    return None


async def set_pace(db, owner_id: str, template: str, band: str, days: float | None) -> None:
    rows = (await db.execute(select(ProjectHabit).where(
        ProjectHabit.owner_id == owner_id, ProjectHabit.kind == "pace_override",
        ProjectHabit.template == template))).scalars().all()
    for row in rows:
        if (row.value or {}).get("band") == band:
            await db.delete(row)
    if days is not None:
        db.add(ProjectHabit(id=uuid.uuid4().hex, owner_id=owner_id, template=template, kind="pace_override",
                            text=f"{template}/{band}", value={"band": band, "days": float(days)}, sources=[],
                            enabled=True, created_at=datetime.utcnow()))
    await db.flush()


# ── stalled (§9) ─────────────────────────────────────────────────────────────

async def last_activity(db, project_id: str) -> datetime | None:
    """The newest thing that happened: any event (turn, tick, file change noted, stage)."""
    return await db.scalar(select(func.max(ProjectEvent.created_at)).where(ProjectEvent.project_id == project_id))


async def stall(db, project: Project, current: dict | None, left: int, now: datetime | None = None) -> dict | None:
    """{days, usual, left} when the project is quiet for too long; None otherwise."""
    if current is None or project.paused or (project.stage or "idea") != "active":
        return None
    last = await last_activity(db, project.id)
    started = current.get("started_at")
    if started:
        started_at = datetime.fromisoformat(started.rstrip("Z"))
        last = max(last, started_at) if last else started_at
    if last is None:
        return None
    days = int(((now or datetime.utcnow()) - last).total_seconds() // 86400)
    usual = await usual_days(db, project.owner_id, project.template, current["band"])
    if days > STALL_DAYS or (usual is not None and days > max(2 * usual, STALL_FLOOR_DAYS)):
        return {"days": days, "usual": usual, "left": left}
    return None


# ── the sheet ────────────────────────────────────────────────────────────────

async def sheet(db, owner_id: str = "local") -> dict:
    from server.services import project_plan
    rules = (await db.execute(select(ProjectHabit).where(
        ProjectHabit.owner_id == owner_id, ProjectHabit.kind == "plan_rule").order_by(ProjectHabit.created_at))).scalars().all()
    ids = {pid for r in rules for pid in (r.sources or [])}
    names = dict((await db.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))).all()) if ids else {}
    cleared = sum(row["levels"] for row in await pace(db, owner_id))
    return {
        "shadow": await project_plan.shadow_view(db),
        "rules": [{"id": r.id, "template": r.template, "text": r.text, "value": r.value or {}, "enabled": bool(r.enabled),
                   "sources": [names[s] for s in (r.sources or []) if s in names],
                   "created_at": r.created_at.isoformat() + "Z"} for r in rules],
        "pace": [row for row in await pace(db, owner_id) if row["median_days"] is not None or row["override_days"] is not None],
        "cleared_levels": cleared,
        "pace_min_levels": PACE_MIN_LEVELS,
    }
