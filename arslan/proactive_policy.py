"""Proactivity policy (0.1.47): what Arslan may raise, and when it may interrupt.

Pure functions, time injected, no I/O — so every rule below is tested directly
and none of it depends on a clock, a database or a model.

The rules, in one place:

- NOTICE WITH CODE. Detectors are deterministic; this module never asks a model
  whether something is worth raising.
- NO EVIDENCE, NO PROPOSAL. A candidate without evidence (or with an evidence
  line that says nothing) is refused here, not trusted to the detector.
- QUIET BY DEFAULT. Duplicates are dropped, muted sources stay muted, and an
  interruption (a system notification) needs: the user wants them, it is not
  quiet hours, today's cap is not spent, and the kind is one the user asked to
  hear about. Job and schedule problems are NOT in that list: the job and the
  scheduler already notify when they end, a second ping would just be noise.
- NEVER CARRY SECRETS. A credential-shaped string in a goal or a quoted page /
  file name is refused, so a watched page cannot smuggle one into the inbox.
- SPENDING IS OPT-IN AND BOUNDED. A zero budget is off; a call is allowed only
  if its worst case still fits today's remainder.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from arslan.companion.content_policy import contains_credential

KINDS = ("job_followup", "scheduled_problem", "web_change", "folder_change", "brief")
#: Kinds that may interrupt with a system notification. Job / schedule problems
#: already notified when the job or the run ended.
NOTIFYING_KINDS = frozenset({"web_change", "folder_change", "brief"})
PRIORITIES = ("high", "normal", "low")
#: Why a background job stopped short, as detectors name it ("other" = none of these).
JOB_REASONS = ("task_budget_exhausted", "task_validation_failed", "task_checks_not_run",
               "task_reconciliation_required", "process_interrupted", "task_input_required",
               "task_no_progress", "execution_failed", "task_execution_failed", "other")
#: Every sentence the inbox can show is a KEY the UI translates. These two sets are the
#: catalog: `gate` refuses a candidate that uses a key outside them, so an item whose text
#: the UI cannot render never reaches the inbox (it would show the raw key), and
#: web/src/locales/proactive-keys.json (checked by test) ties the catalog to the six languages.
TITLE_KEYS = frozenset(f"title.{kind}" for kind in KINDS)
EVIDENCE_KEYS = frozenset({
    "job.goal", *(f"job.reason.{reason}" for reason in JOB_REASONS),
    "sched.state", "sched.run", "web.changed", "web.added", "web.removed", "folder.new", "folder.file",
    "brief.open", "brief.running", "brief.schedules"})
#: Days an open item stays worth showing; afterwards it expires (never deleted by expiry).
FRESH_DAYS = {"job_followup": 7, "scheduled_problem": 14, "web_change": 14, "folder_change": 14, "brief": 2}
MAX_GOAL_CHARS = 1500
WATCH_COOLDOWN = timedelta(hours=24)


def _hhmm(value: str) -> str:
    parts = str(value).strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts) or not (0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60):
        raise ValueError("expected HH:MM")
    return f"{int(parts[0]):02d}:{int(parts[1]):02d}"


class ProactiveConfig(BaseModel):
    """The user's choices. Defaults: watching is on (it costs nothing), anything
    that spends is off."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    notify: bool = True
    notify_daily_cap: int = Field(default=5, ge=0, le=20)
    quiet_start: str = "22:00"
    quiet_end: str = "08:00"
    job_followups: bool = True
    scheduled_problems: bool = True
    watches: bool = True
    brief_enabled: bool = False
    brief_time: str = "08:30"
    diagnosis_daily_usd: float = Field(default=0.0, ge=0.0, le=5.0)   # 0 = off

    _times = field_validator("quiet_start", "quiet_end", "brief_time")(lambda cls, v: _hhmm(v))


@dataclass(frozen=True)
class Evidence:
    """One line of why. `key` names a translatable sentence; `quote` is text that
    came from outside (a page, a file name): shown in quotes, never obeyed."""

    key: str
    params: dict = field(default_factory=dict)
    quote: str | None = None


@dataclass(frozen=True)
class Candidate:
    kind: str
    fingerprint: str
    source_key: str
    title_key: str
    evidence: tuple[Evidence, ...]
    goal: str = ""
    params: dict = field(default_factory=dict)
    criteria: tuple[dict, ...] = ()
    priority: Literal["high", "normal", "low"] = "normal"
    conversation_id: str | None = None
    notify: bool = True          # a per-source preference (a watch's own switch)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str = ""


def gate(candidate: Candidate, *, existing: set[str], muted: set[str]) -> Verdict:
    """May this candidate become an inbox item? The first failing rule names itself."""
    if candidate.kind not in KINDS:
        return Verdict(False, "unknown_kind")
    if not candidate.title_key.strip():
        return Verdict(False, "no_title")
    if not candidate.evidence or any(not e.key.strip() for e in candidate.evidence):
        return Verdict(False, "no_evidence")
    if candidate.priority not in PRIORITIES:
        return Verdict(False, "bad_priority")
    if candidate.title_key not in TITLE_KEYS or any(e.key not in EVIDENCE_KEYS for e in candidate.evidence):
        return Verdict(False, "unknown_key")
    if candidate.kind != "brief" and not candidate.goal.strip():
        return Verdict(False, "no_goal")
    if len(candidate.goal) > MAX_GOAL_CHARS:
        return Verdict(False, "goal_too_long")
    if candidate.fingerprint in existing:
        return Verdict(False, "duplicate")
    if f"kind:{candidate.kind}" in muted:
        return Verdict(False, "muted_kind")
    if candidate.source_key in muted:
        return Verdict(False, "muted_source")
    texts = [candidate.goal, *(e.quote or "" for e in candidate.evidence)]
    if any(t and contains_credential(t) for t in texts):
        return Verdict(False, "credential")
    return Verdict(True)


def parse_clock(value: str) -> time:
    hours, minutes = _hhmm(value).split(":")
    return time(int(hours), int(minutes))


def in_quiet_hours(now: datetime, start: str, end: str) -> bool:
    """Quiet from `start` up to (not including) `end`, local time; the window may
    wrap midnight. Equal times mean no quiet hours."""
    a, b, t = parse_clock(start), parse_clock(end), now.time().replace(second=0, microsecond=0)
    if a == b:
        return False
    return a <= t < b if a < b else (t >= a or t < b)


def may_notify(candidate: Candidate, *, now: datetime, config: ProactiveConfig, notified_today: int) -> bool:
    """May this item interrupt the user? Every condition must hold."""
    return (config.notify and candidate.notify and candidate.kind in NOTIFYING_KINDS
            and notified_today < config.notify_daily_cap
            and not in_quiet_hours(now, config.quiet_start, config.quiet_end))


def cooldown_over(last_item_at: datetime | None, now: datetime) -> bool:
    """A watch raises at most one item per day, however often the page changes."""
    return last_item_at is None or now - last_item_at >= WATCH_COOLDOWN


def is_stale(kind: str, created_at: datetime, now: datetime) -> bool:
    return now - created_at > timedelta(days=FRESH_DAYS.get(kind, 7))


def brief_due(now: datetime, config: ProactiveConfig, last_brief_day: str | None) -> bool:
    """One brief a day, at or after the chosen time, only if switched on."""
    return (config.brief_enabled and now.strftime("%Y-%m-%d") != last_brief_day
            and now.time() >= parse_clock(config.brief_time))


def diagnosis_allowed(*, cap_usd: float, spent_micro: int, worst_case_micro: int) -> bool:
    """Zero is off. Otherwise the call's worst case must still fit what is left."""
    return cap_usd > 0 and spent_micro + worst_case_micro <= round(cap_usd * 1_000_000)


def order(items: list) -> list:
    """Most important first, newest first within a priority."""
    rank = {p: i for i, p in enumerate(PRIORITIES)}
    return sorted(items, key=lambda i: (rank.get(i.priority, 9), -i.created_at.timestamp()))
