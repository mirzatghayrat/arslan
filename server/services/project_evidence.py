"""Evidence that moves a project's current level (0.1.56 §4): files, what the user said, runs.

Every tick Arslan makes names what it saw. Three sources, all best-effort and never in the
way of a turn:

- Files (§4.2): checkpoints with `expects: {kind: "file", pattern, min}` are checked against
  the project folder after each turn in a project conversation and on the proactive loop.
- You said (§4.3): after the user's own turn, a judge reads the user's message against the
  current level. Two decision points, because the judge answers yes/no only: the gate
  `project.progress` ("does the message say any of this is done?") runs once per turn; only
  on a yes does `project.progress.item` ask per open checkpoint and for the condition.
- Runs (§4.4): "交给 Arslan 起头" records a hand-off (conversation ↔ checkpoint); a background
  job in that conversation that ends `done` ticks the checkpoint.

Only the current level's checkpoints are ticked: a later level's work is not evidence for it
yet. Proposals that follow wait on the card — never a notification, never an Inbox item.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import or_, select

from server.db import session as db_session
from server.db.models import ArslanMessage, ConversationContext, Project, ProjectCheckpoint, ProjectEvent
from server.services import project_plan

logger = logging.getLogger(__name__)

SCAN_DEPTH = 4
SCAN_ENTRIES = 5000
SKIP_DIRS = {"node_modules", "__pycache__"}
QUOTE_CHARS = 120
MAX_ITEMS = 5          # open checkpoints asked per turn (the condition is asked besides)


# ── files ────────────────────────────────────────────────────────────────────

def scan_folder(folder: Path) -> list[str]:
    """Relative POSIX paths of files under `folder`, bounded: depth ≤ SCAN_DEPTH, at most
    SCAN_ENTRIES entries looked at, hidden and secrets-named entries skipped, symlinks only
    when they resolve inside the folder (directories behind symlinks are never walked)."""
    from server.services.workspace_paths import is_secret_name
    root = folder.resolve()
    found: list[str] = []
    seen = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        rel = Path(current).relative_to(root)
        depth = 0 if str(rel) == "." else len(rel.parts)
        # Files at most SCAN_DEPTH folders down: deeper folders are not walked.
        dirs[:] = [] if depth >= SCAN_DEPTH else sorted(
            d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS and not is_secret_name(d))
        for name in sorted(files):
            seen += 1
            if seen > SCAN_ENTRIES:
                return found
            if name.startswith(".") or is_secret_name(name):
                continue
            path = Path(current) / name
            if path.is_symlink():
                try:
                    if not path.resolve().is_relative_to(root):
                        continue
                except OSError:
                    continue
            found.append((rel / name).as_posix() if depth else name)
        seen += len(dirs)
        if seen > SCAN_ENTRIES:
            return found
    return found


def _segments_match(path: list[str], pattern: list[str]) -> bool:
    from fnmatch import fnmatchcase
    if not pattern:
        return not path
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        return any(_segments_match(path[i:], rest) for i in range(len(path) + 1))
    return bool(path) and fnmatchcase(path[0], head) and _segments_match(path[1:], rest)


def matches(pattern: str, paths: list[str]) -> list[str]:
    """Paths matching a glob relative to the folder: `*` stays inside one folder, `**` spans
    folders, case-sensitive. A pattern that tries to leave the folder matches nothing."""
    raw = pattern.strip()
    parts = [p for p in PurePosixPath(raw).parts if p not in ("", ".")]
    if not parts or ".." in parts or raw.startswith("/"):   # defence: scanned paths never hold ".."
        return []
    return [p for p in paths if _segments_match(p.split("/"), parts)]


def expected_min(expects: dict) -> int:
    try:
        return max(1, min(1000, int(expects.get("min") or 1)))
    except (TypeError, ValueError):
        return 1


async def _current_level(db, project: Project) -> dict | None:
    if project.status != "active" or project_plan.stage_of(project) != "active" or project.paused:
        return None
    plan = await project_plan.plan_of(db, project)
    return next((lv for lv in plan["levels"] if lv["state"] == "current"), None)


async def check_files(db, project: Project) -> int:
    """Tick the current level's file checkpoints whose files are there. Returns ticks made."""
    from server.api.projects import project_folder
    level = await _current_level(db, project)
    if level is None:
        return 0
    wanted = [cp for cp in level["checkpoints"] if cp["state"] != "done"
              and isinstance(cp.get("expects"), dict) and cp["expects"].get("kind") == "file"]
    if not wanted:
        return 0
    folder = project_folder(project)
    if folder is None:
        return 0
    paths = scan_folder(folder)
    ticked = 0
    moved = False
    for cp in wanted:
        hits = matches(cp["expects"]["pattern"], paths)
        need = expected_min(cp["expects"])
        # "3/10" on the checkpoint while files are arriving; written only when it changes.
        progress = f"{len(hits)}/{need}" if hits and need > 1 else None
        row = await db.get(ProjectCheckpoint, cp["id"])
        if row is not None and row.progress != progress:
            row.progress, moved = progress, True
        if len(hits) >= need:
            await project_plan.tick(db, project, cp["id"], actor="arslan", evidence={
                "kind": "file", "pattern": cp["expects"]["pattern"], "count": len(hits), "paths": hits[:3]})
            ticked += 1
    if moved and not ticked:
        await project_plan._bump_plan(db, project)
    return ticked


def newest_change(folder: Path, paths: list[str]) -> datetime | None:
    """When a scanned file last changed (UTC, naive like the database's times)."""
    newest = None
    for rel in paths:
        try:
            mtime = (folder / rel).stat().st_mtime
        except OSError:
            continue
        newest = mtime if newest is None or mtime > newest else newest
    return datetime.fromtimestamp(newest, timezone.utc).replace(tzinfo=None) if newest is not None else None


async def note_folder_activity(db, project: Project) -> bool:
    """§9: a file changed in the folder since the project last moved counts as activity (and
    starts a planned project in Idea, like a first conversation does)."""
    from server.api.projects import project_folder
    from server.services import project_habits
    folder = project_folder(project)
    if folder is None:
        return False
    changed = newest_change(folder, scan_folder(folder))
    since = await project_habits.last_activity(db, project.id) or project.created_at
    if changed is None or (since is not None and changed <= since):
        return False
    await project_plan.note_activity(db, project.id)
    return True


async def scan_projects(owner_id: str = "local") -> int:
    """The proactive loop's pass: every project with a folder that is not finished — file
    changes are activity (§9); the current level's file checkpoints tick (§4.2)."""
    ticked = 0
    async with db_session.AsyncSessionLocal() as db:
        ids = (await db.execute(select(Project.id).where(
            Project.owner_id == owner_id, Project.status == "active",
            or_(Project.stage.is_(None), Project.stage.in_(("idea", "active"))),
            Project.workspace_ref.is_not(None)))).scalars().all()
    for project_id in ids:
        try:
            async with db_session.AsyncSessionLocal() as db:
                project = await db.get(Project, project_id)
                await note_folder_activity(db, project)
                ticked += await check_files(db, project)
                await db.commit()
        except Exception:  # noqa: BLE001 — one project never stops the others
            logger.warning("project file scan failed", exc_info=True)
    return ticked


# ── you said ─────────────────────────────────────────────────────────────────

def _quote(text: str) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= QUOTE_CHARS else flat[: QUOTE_CHARS - 1] + "…"


async def _last_user_message_id(db, conversation_id: str) -> int | None:
    return (await db.execute(select(ArslanMessage.id).where(
        ArslanMessage.conversation_id == conversation_id, ArslanMessage.role == "user",
    ).order_by(ArslanMessage.id.desc()).limit(1))).scalar()


async def check_said(project_id: str, conversation_id: str, user_message: str) -> dict:
    """§4.3. Returns what it did: {"asked": bool, "ticked": [ids], "proposed": bool}."""
    from server.services import judgment
    out = {"asked": False, "ticked": [], "proposed": False}
    if not (user_message or "").strip():
        return out
    async with db_session.AsyncSessionLocal() as db:
        project = await db.get(Project, project_id)
        level = await _current_level(db, project) if project else None
    if level is None:
        return out
    open_cps = [cp for cp in level["checkpoints"] if cp["state"] != "done"][:MAX_ITEMS]
    condition = level["clear_condition"] or ""
    if not open_cps and not condition:
        return out
    message = user_message.strip()
    out["asked"] = True
    gate = await judgment.judge("project.progress", {
        "level": level["name"], "condition": condition, "open_checkpoints": [cp["text"] for cp in open_cps],
        "user_message": message}, ref=project_id, conversation_id=conversation_id)
    point = judgment.REGISTRY["project.progress"]
    if gate is None or not gate.yes(point.threshold):
        return out
    item_point = judgment.REGISTRY["project.progress.item"]
    done_ids = []
    for cp in open_cps:
        verdict = await judgment.judge("project.progress.item", {"item": cp["text"], "user_message": message},
                                       ref=cp["id"], conversation_id=conversation_id)
        if verdict is not None and verdict.yes(item_point.threshold):
            done_ids.append(cp["id"])
    condition_met = False
    if condition:
        verdict = await judgment.judge("project.progress.item", {
            "item": f"{level['name']}: {condition}", "user_message": message},
            ref=level["id"], conversation_id=conversation_id)
        condition_met = verdict is not None and verdict.yes(item_point.threshold)
    if not done_ids and not condition_met:
        return out
    async with db_session.AsyncSessionLocal() as db:
        project = await db.get(Project, project_id)
        current = await _current_level(db, project)
        if current is None or current["id"] != level["id"]:
            return out       # the plan moved while the judge was thinking
        evidence = {"kind": "said", "quote": _quote(message), "conversation_id": conversation_id,
                    "message_id": await _last_user_message_id(db, conversation_id)}
        for cp_id in done_ids:
            if await project_plan.tick(db, project, cp_id, actor="arslan", evidence=evidence):
                out["ticked"].append(cp_id)
        if condition_met:
            out["proposed"] = await project_plan.propose_advance(db, project, evidence=evidence) is not None
        await db.commit()
    return out


# ── runs ─────────────────────────────────────────────────────────────────────

async def record_handoff(db, project: Project, checkpoint_id: str, conversation_id: str) -> ProjectEvent:
    """"交给 Arslan 起头": this conversation works on this checkpoint (§4.4)."""
    cp, level = await project_plan._checkpoint_in(db, project, checkpoint_id)
    return await project_plan._event(db, project.id, "handoff", "user", {
        "checkpoint_id": cp.id, "text": cp.text, "level_id": level.id, "conversation_id": conversation_id})


async def job_finished(conversation_id: str, job_id: str, goal: str, outcome: str) -> list[str]:
    """A background job in a handed-off conversation ended. `done` ticks the checkpoint(s)
    handed to that conversation; `partial` / `blocked` / anything else does not."""
    if outcome != "done":
        return []
    ticked: list[str] = []
    async with db_session.AsyncSessionLocal() as db:
        project_id = (await db.execute(select(ConversationContext.project_id).where(
            ConversationContext.id == conversation_id))).scalar()
        project = await db.get(Project, project_id) if project_id else None
        if project is None or project.status != "active":
            return []
        handoffs = (await db.execute(select(ProjectEvent).where(
            ProjectEvent.project_id == project.id, ProjectEvent.kind == "handoff",
        ).order_by(ProjectEvent.created_at))).scalars().all()
        for event in handoffs:
            if (event.payload or {}).get("conversation_id") != conversation_id:
                continue
            try:
                done = await project_plan.tick(db, project, event.payload["checkpoint_id"], actor="arslan",
                                               evidence={"kind": "run", "job_id": job_id, "goal": goal[:200],
                                                         "conversation_id": conversation_id})
            except project_plan.PlanError:
                continue      # the checkpoint went away in a re-plan
            if done is not None:
                ticked.append(event.payload["checkpoint_id"])
        await db.commit()
    return ticked


# ── after a turn ─────────────────────────────────────────────────────────────

async def after_turn(project_id: str, conversation_id: str, user_message: str, *, said: bool) -> None:
    """Files always; what the user said only for the user's own turns (a job's goal is not
    the user speaking)."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if project is not None:
                await check_files(db, project)
                await db.commit()
        if said:
            await check_said(project_id, conversation_id, user_message)
    except Exception:  # noqa: BLE001 — evidence is bookkeeping; the turn is already answered
        logger.warning("project evidence after turn failed", exc_info=True)
