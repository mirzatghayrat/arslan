"""Proactivity service (0.1.47): store what was noticed, let the user decide.

The flow: detectors (deterministic, free) -> policy gate (evidence required,
duplicates and mutes dropped) -> inbox item -> maybe one quiet notification ->
the user accepts (-> a background job; its own confirmations still apply),
snoozes, or dismisses. Nothing in this module acts on its own, and the only
model call in the whole feature is the optional, capped diagnosis
(proactive_diagnosis), which runs after an item exists.

Bounded by construction: stale open items expire, finished ones are deleted by
age and by a row cap, and spend rows are trimmed (see `prune`).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from arslan import proactive_policy as policy
from arslan.proactive_policy import Candidate, ProactiveConfig
from server.db import session as db_session
from server.db.models import ProactiveItem, ProactiveMute, ProactiveSpend, ProactiveWatch, ScheduledTask, Setting
from server.services import desktop_status, proactive_detectors as detectors, runtime_messages, settings_service

logger = logging.getLogger(__name__)

CONFIG_KEY = "proactive_config"
OPEN = ("new", "seen")
ACTIONABLE = ("new", "seen", "snoozed")
FINISHED = ("dismissed", "expired", "accepted")
SNOOZE_DAYS = (1, 3, 7)
MAX_ROWS = 500
KEEP_FINISHED_DAYS = 90
MAX_WATCHES = 20
MIN_WATCH_INTERVAL_S = 1800
MAX_WATCH_INTERVAL_S = 7 * 86400
SCAN_INTERVAL_S = 600
FIRST_SCAN_DELAY_S = 60


class ProactiveError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── time ────────────────────────────────────────────────────────────────────

def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_now() -> datetime:
    return datetime.now()


def start_of_local_day_utc(now_utc: datetime, now_local: datetime) -> datetime:
    """Midnight of the user's local day, expressed as naive UTC (how rows are stored)."""
    return now_utc - (now_local - now_local.replace(hour=0, minute=0, second=0, microsecond=0))


# ── config ──────────────────────────────────────────────────────────────────

async def load_config() -> ProactiveConfig:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(Setting, CONFIG_KEY)
    try:
        return ProactiveConfig(**json.loads(row.value)) if row and row.value else ProactiveConfig()
    except (ValueError, TypeError):
        logger.warning("stored proactive config is unreadable; using defaults")
        return ProactiveConfig()          # defaults spend nothing, so this can only under-notify


async def save_config(patch: dict) -> ProactiveConfig:
    current = (await load_config()).model_dump()
    try:
        merged = ProactiveConfig(**{**current, **patch})
    except ValueError as exc:
        raise ProactiveError("invalid_config") from exc
    async with db_session.AsyncSessionLocal() as db:
        await settings_service._set_raw(db, CONFIG_KEY, json.dumps(merged.model_dump()))
        await db.commit()
    return merged


# ── serialization ───────────────────────────────────────────────────────────

def present(item: ProactiveItem) -> dict:
    return {"id": item.id, "kind": item.kind, "title_key": item.title_key, "params": item.params or {},
            "evidence": item.evidence or [], "goal": item.goal, "priority": item.priority, "status": item.status,
            "diagnosis": item.diagnosis, "conversation_id": item.conversation_id, "job_id": item.job_id,
            "created_at": item.created_at.isoformat() + "Z",
            "snooze_until": item.snooze_until.isoformat() + "Z" if item.snooze_until else None}


def _evidence_json(candidate: Candidate) -> list[dict]:
    return [{"key": e.key, "params": e.params, **({"quote": e.quote} if e.quote else {})} for e in candidate.evidence]


# ── ingest ──────────────────────────────────────────────────────────────────

async def _notified_today(db, since_utc: datetime) -> int:
    return int(await db.scalar(select(func.count()).select_from(ProactiveItem)
                               .where(ProactiveItem.notified_at >= since_utc)) or 0)


async def ingest(found: list[detectors.Found], *, now_utc: datetime, now_local: datetime,
                 config: ProactiveConfig) -> dict:
    """Gate every finding; store the ones that pass. Returns what happened, by reason."""
    created: list[int] = []
    rejected: dict[str, int] = {}
    notified = 0
    since = start_of_local_day_utc(now_utc, now_local)
    for item in found:
        candidate = item.candidate
        async with db_session.AsyncSessionLocal() as db:
            existing = set((await db.execute(select(ProactiveItem.fingerprint).where(
                ProactiveItem.fingerprint == candidate.fingerprint))).scalars())
            muted = set((await db.execute(select(ProactiveMute.key))).scalars())
            verdict = policy.gate(candidate, existing=existing, muted=muted)
            if verdict.ok:
                row = ProactiveItem(
                    kind=candidate.kind, fingerprint=candidate.fingerprint, source_key=candidate.source_key,
                    title_key=candidate.title_key, params=candidate.params, evidence=_evidence_json(candidate),
                    goal=candidate.goal, criteria=list(candidate.criteria), priority=candidate.priority,
                    status="new", conversation_id=candidate.conversation_id, created_at=now_utc)
                db.add(row)
                try:
                    await db.flush()
                except IntegrityError:          # raced with another scan: same evidence, same item
                    await db.rollback()
                    verdict = policy.Verdict(False, "duplicate")
                else:
                    if policy.may_notify(candidate, now=now_local, config=config,
                                         notified_today=await _notified_today(db, since)):
                        row.notified_at = now_utc
                        notified += 1
                    await db.commit()
                    created.append(row.id)
        if not verdict.ok:
            rejected[verdict.reason] = rejected.get(verdict.reason, 0) + 1
        if item.ack is not None:               # only now may a watch's baseline move
            await item.ack()
    for _ in range(notified):
        desktop_status.push("proactive", outcome="ok")
    return {"created": created, "rejected": rejected, "notified": notified}


# ── the morning brief ───────────────────────────────────────────────────────

async def build_brief(now_utc: datetime, now_local: datetime, locale: str) -> detectors.Found | None:
    """Today at a glance, from data already in hand. No model. Nothing to say means
    no brief: an empty 'good morning' is noise."""
    from server.services import background_jobs
    async with db_session.AsyncSessionLocal() as db:
        open_items = (await db.execute(select(ProactiveItem).where(
            ProactiveItem.status.in_(OPEN), ProactiveItem.kind != "brief"))).scalars().all()
        soon = (await db.execute(select(ScheduledTask).where(
            ScheduledTask.enabled.is_(True), ScheduledTask.name != detectors.HEARTBEAT_NAME,
            ScheduledTask.next_due_at.is_not(None), ScheduledTask.next_due_at <= now_utc + timedelta(hours=24),
            ScheduledTask.next_due_at >= now_utc))).scalars().all()
    running = [j for j in background_jobs._jobs.values() if j.phase != "finished"]
    lines: list[policy.Evidence] = []
    if open_items:
        kinds: dict[str, int] = {}
        for item in open_items:
            kinds[item.kind] = kinds.get(item.kind, 0) + 1
        lines.append(policy.Evidence("brief.open", {"count": len(open_items), "kinds": kinds}))
    if running:
        lines.append(policy.Evidence("brief.running", {"count": len(running)},
                                     quote=" · ".join(j.goal[:60] for j in running[:3])))
    if soon:
        lines.append(policy.Evidence("brief.schedules", {"count": len(soon)},
                                     quote=" · ".join(t.name[:40] for t in soon[:3])))
    if not lines:
        return None
    day = now_local.strftime("%Y-%m-%d")
    return detectors.Found(Candidate(kind="brief", fingerprint=f"brief:{day}", source_key="brief",
                                     title_key="title.brief", params={"day": day}, evidence=tuple(lines)))


async def _last_brief_day() -> str | None:
    async with db_session.AsyncSessionLocal() as db:
        fingerprint = await db.scalar(select(ProactiveItem.fingerprint).where(ProactiveItem.kind == "brief")
                                      .order_by(ProactiveItem.id.desc()).limit(1))
    return fingerprint.split(":", 1)[1] if fingerprint else None


# ── scanning ────────────────────────────────────────────────────────────────

async def scan_once(*, now_utc: datetime | None = None, now_local: datetime | None = None,
                    fetch=None, manual: bool = False) -> dict:
    """One pass over every detector. Safe to call any time; a detector that fails
    is logged and skipped, never allowed to stop the others."""
    now_utc, now_local = now_utc or utc_now(), now_local or local_now()
    config = await load_config()
    if not config.enabled and not manual:
        return {"skipped": "disabled"}
    await maintain(now_utc)
    try:
        locale = await runtime_messages.selected_locale()
    except Exception:  # noqa: BLE001
        locale = "en"
    async with db_session.AsyncSessionLocal() as db:
        workspace = await settings_service.workspace_dir(db)
    ctx = detectors.Context(now=now_utc, config=config, locale=locale, workspace=workspace, fetch=fetch)
    wanted = [name for name, on in (("job_followups", config.job_followups),
                                    ("scheduled_problems", config.scheduled_problems),
                                    ("web_changes", config.watches), ("folder_changes", config.watches)) if on]
    found: list[detectors.Found] = []
    for name in wanted:
        try:
            found.extend(await detectors.DETECTORS[name](ctx))
        except Exception as exc:  # noqa: BLE001 — isolated on purpose
            logger.warning("proactive detector %s failed: %s %s", name, type(exc).__name__, exc)
    if policy.brief_due(now_local, config, await _last_brief_day()):
        try:
            brief = await build_brief(now_utc, now_local, locale)
            if brief is not None:
                found.append(brief)
        except Exception as exc:  # noqa: BLE001
            logger.warning("proactive brief failed: %s", type(exc).__name__)
    result = await ingest(found, now_utc=now_utc, now_local=now_local, config=config)
    if config.diagnosis_daily_usd > 0 and result["created"]:
        from server.services import proactive_diagnosis
        for item_id in result["created"][:2]:
            try:
                await proactive_diagnosis.diagnose(item_id, config=config, now_local=now_local)
            except Exception as exc:  # noqa: BLE001 — diagnosis is a bonus, never a failure
                logger.warning("proactive diagnosis failed: %s", type(exc).__name__)
    return result


async def maintain(now_utc: datetime) -> None:
    """Wake due snoozes, expire stale items, trim to the caps."""
    async with db_session.AsyncSessionLocal() as db:
        for item in (await db.execute(select(ProactiveItem).where(ProactiveItem.status == "snoozed",
                     ProactiveItem.snooze_until <= now_utc))).scalars():
            item.status, item.snooze_until = "new", None
        for item in (await db.execute(select(ProactiveItem).where(ProactiveItem.status.in_(ACTIONABLE)))).scalars():
            if policy.is_stale(item.kind, item.created_at, now_utc):
                item.status = "expired"
        await db.commit()
    await prune(now_utc)


async def prune(now_utc: datetime) -> None:
    cutoff = now_utc - timedelta(days=KEEP_FINISHED_DAYS)
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(delete(ProactiveItem).where(ProactiveItem.status.in_(FINISHED),
                                                     ProactiveItem.created_at < cutoff))
        total = int(await db.scalar(select(func.count()).select_from(ProactiveItem)) or 0)
        if total > MAX_ROWS:          # over the cap: drop the oldest finished ones, never an open one
            old = (await db.execute(select(ProactiveItem.id).where(ProactiveItem.status.in_(FINISHED))
                                    .order_by(ProactiveItem.id).limit(total - MAX_ROWS))).scalars().all()
            if old:
                await db.execute(delete(ProactiveItem).where(ProactiveItem.id.in_(old)))
        await db.execute(delete(ProactiveSpend).where(
            ProactiveSpend.day < (now_utc - timedelta(days=60)).strftime("%Y-%m-%d")))
        await db.commit()


# ── what the user does with an item ─────────────────────────────────────────

async def _get(db, item_id: int) -> ProactiveItem:
    item = await db.get(ProactiveItem, item_id)
    if item is None:
        raise ProactiveError("item_not_found")
    return item


async def list_items(scope: str = "open", limit: int = 100) -> list[dict]:
    statuses = {"open": OPEN, "done": FINISHED, "snoozed": ("snoozed",)}.get(scope)
    async with db_session.AsyncSessionLocal() as db:
        query = select(ProactiveItem)
        if statuses:
            query = query.where(ProactiveItem.status.in_(statuses))
        rows = (await db.execute(query.order_by(ProactiveItem.id.desc()).limit(max(1, min(limit, 200))))).scalars().all()
    return [present(r) for r in policy.order(rows)]


async def summary() -> dict:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(ProactiveItem.status, ProactiveItem.priority, func.count())
                                 .where(ProactiveItem.status.in_(OPEN))
                                 .group_by(ProactiveItem.status, ProactiveItem.priority))).all()
    return {"open": sum(n for _, _, n in rows),
            "unread": sum(n for status, _, n in rows if status == "new"),
            "high": sum(n for status, p, n in rows if status == "new" and p == "high")}


async def mark_seen(ids: list[int]) -> None:
    async with db_session.AsyncSessionLocal() as db:
        now = utc_now()
        for item in (await db.execute(select(ProactiveItem).where(ProactiveItem.id.in_(ids),
                     ProactiveItem.status == "new"))).scalars():
            item.status, item.seen_at = "seen", now
        await db.commit()


async def accept(item_id: int, conversation_id: str | None = None) -> dict:
    """The one place a proposal becomes work: a background job, with the goal and
    completion criteria the item carries. Its confirmations (writes, commands,
    browser/Mac actions) are the job's own and are asked as usual. The job reports
    into `conversation_id`, or into the item's own conversation when it has one."""
    from server.services import background_jobs
    async with db_session.AsyncSessionLocal() as db:
        item = await _get(db, item_id)
        if item.kind == "brief" or not (item.goal or "").strip():
            raise ProactiveError("nothing_to_do")
        if item.status not in ACTIONABLE:
            raise ProactiveError("already_handled")
        conversation_id = conversation_id or item.conversation_id
        if not conversation_id or len(conversation_id) > 50:
            raise ProactiveError("invalid_conversation")
        goal, criteria = item.goal, list(item.criteria or [])
        # Claim first, in one conditional UPDATE, so two clicks (or two windows)
        # cannot both start a job: only the statement that still finds the item
        # open changes a row.
        claimed = await db.execute(update(ProactiveItem).where(
            ProactiveItem.id == item_id, ProactiveItem.status.in_(ACTIONABLE)).values(
            status="accepted", acted_at=utc_now(), conversation_id=conversation_id))
        if claimed.rowcount != 1:
            raise ProactiveError("already_handled")
        await db.commit()
    try:
        job = await background_jobs.start(conversation_id, goal, criteria)
    except Exception:
        async with db_session.AsyncSessionLocal() as db:       # the job never started: give the item back
            item = await _get(db, item_id)
            item.status, item.acted_at = "new", None
            await db.commit()
        raise
    async with db_session.AsyncSessionLocal() as db:
        (await _get(db, item_id)).job_id = job.job_id
        await db.commit()
    return {"job_id": job.job_id, "conversation_id": conversation_id}


async def snooze(item_id: int, days: int) -> None:
    if days not in SNOOZE_DAYS:
        raise ProactiveError("invalid_snooze")
    async with db_session.AsyncSessionLocal() as db:
        item = await _get(db, item_id)
        if item.status not in ACTIONABLE:
            raise ProactiveError("already_handled")
        item.status, item.snooze_until = "snoozed", utc_now() + timedelta(days=days)
        await db.commit()


async def dismiss(item_id: int, mute: str | None = None) -> None:
    """'Not useful'. mute='source' also silences this source (and stops a watch);
    mute='kind' silences the whole kind."""
    if mute not in (None, "source", "kind"):
        raise ProactiveError("invalid_mute")
    async with db_session.AsyncSessionLocal() as db:
        item = await _get(db, item_id)
        if item.status not in ACTIONABLE:
            raise ProactiveError("already_handled")
        item.status, item.acted_at = "dismissed", utc_now()
        if mute:
            key = item.source_key if mute == "source" else f"kind:{item.kind}"
            if await db.get(ProactiveMute, key) is None:
                db.add(ProactiveMute(key=key, created_at=utc_now()))
            if mute == "source" and key.startswith("watch:"):
                watch = await db.get(ProactiveWatch, int(key.split(":", 1)[1]))
                if watch is not None:
                    watch.enabled = False
        await db.commit()


async def unmute(key: str) -> None:
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(delete(ProactiveMute).where(ProactiveMute.key == key))
        await db.commit()


async def list_mutes() -> list[str]:
    async with db_session.AsyncSessionLocal() as db:
        return sorted((await db.execute(select(ProactiveMute.key))).scalars())


# ── watches ─────────────────────────────────────────────────────────────────

def present_watch(w: ProactiveWatch) -> dict:
    return {"id": w.id, "kind": w.kind, "target": w.target, "label": w.label, "enabled": bool(w.enabled),
            "interval_s": w.interval_s, "notify": bool(w.notify), "last_error": w.last_error,
            "last_checked_at": w.last_checked_at.isoformat() + "Z" if w.last_checked_at else None,
            "last_changed_at": w.last_changed_at.isoformat() + "Z" if w.last_changed_at else None}


async def list_watches() -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(ProactiveWatch).order_by(ProactiveWatch.id))).scalars().all()
    return [present_watch(w) for w in rows]


def _interval(value) -> int:
    if (not isinstance(value, int) or isinstance(value, bool)
            or not MIN_WATCH_INTERVAL_S <= value <= MAX_WATCH_INTERVAL_S):
        raise ProactiveError("invalid_interval")
    return value


async def add_watch(kind: str, target: str, *, label: str | None = None, interval_s: int = 21600,
                    notify: bool = True) -> dict:
    target = (target or "").strip()
    if kind == "web":
        from urllib.parse import urlsplit

        from server.services.browser_proxy import validate_url
        try:
            target = validate_url(target)
        except ValueError as exc:
            raise ProactiveError("invalid_url") from exc
        default_label = urlsplit(target).hostname or target
    elif kind == "folder":
        async with db_session.AsyncSessionLocal() as db:
            workspace = await settings_service.workspace_dir(db)
        if workspace is None:
            raise ProactiveError("workspace_required")
        path = detectors.inside(workspace, target)
        if path is None:
            raise ProactiveError("outside_workspace")
        target, default_label = str(path), path.name or str(path)
    else:
        raise ProactiveError("invalid_kind")
    label = " ".join((label or default_label).split())[:120] or default_label
    interval = _interval(interval_s)
    async with db_session.AsyncSessionLocal() as db:
        if int(await db.scalar(select(func.count()).select_from(ProactiveWatch)) or 0) >= MAX_WATCHES:
            raise ProactiveError("too_many_watches")
        watch = ProactiveWatch(kind=kind, target=target, label=label, interval_s=interval,
                               notify=bool(notify), enabled=True, created_at=utc_now())
        db.add(watch)
        await db.commit()
        await db.refresh(watch)
        return present_watch(watch)


async def update_watch(watch_id: int, patch: dict) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        watch = await db.get(ProactiveWatch, watch_id)
        if watch is None:
            raise ProactiveError("watch_not_found")
        if "interval_s" in patch:
            watch.interval_s = _interval(patch["interval_s"])
        if "enabled" in patch:
            watch.enabled = bool(patch["enabled"])
            if watch.enabled:          # turning it back on lifts the mute that turned it off
                await db.execute(delete(ProactiveMute).where(ProactiveMute.key == f"watch:{watch.id}"))
        if "notify" in patch:
            watch.notify = bool(patch["notify"])
        if "label" in patch:
            watch.label = " ".join(str(patch["label"]).split())[:120] or watch.label
        await db.commit()
        return present_watch(watch)


async def delete_watch(watch_id: int) -> None:
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(delete(ProactiveWatch).where(ProactiveWatch.id == watch_id))
        await db.execute(delete(ProactiveMute).where(ProactiveMute.key == f"watch:{watch_id}"))
        await db.commit()


# ── the loop ────────────────────────────────────────────────────────────────

_loop_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


async def _loop(interval: float, first_delay: float) -> None:
    assert _stop_event is not None
    try:
        await asyncio.wait_for(_stop_event.wait(), timeout=first_delay)
        return
    except TimeoutError:
        pass
    while not _stop_event.is_set():
        try:
            await scan_once()
        except Exception as exc:  # noqa: BLE001 — the loop outlives any one scan
            logger.warning("proactive scan failed: %s %s", type(exc).__name__, exc)
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass


def start(*, interval: float = SCAN_INTERVAL_S, first_delay: float = FIRST_SCAN_DELAY_S) -> None:
    global _loop_task, _stop_event
    if _loop_task is not None and not _loop_task.done():
        return
    _stop_event = asyncio.Event()
    _loop_task = asyncio.create_task(_loop(interval, first_delay))


async def stop() -> None:
    global _loop_task
    if _stop_event is not None:
        _stop_event.set()
    task, _loop_task = _loop_task, None
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
