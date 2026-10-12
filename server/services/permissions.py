"""One place that decides whether Arslan may cross a boundary (0.1.61 §3, §A11).

`decide(request, context)` answers, in order:
  1. money — always a card, in every mode, never remembered;
  2. an "Always" rule for exactly this kind and target;
  3. a grant for this task or this conversation (a background job reads the grants of the
     conversation that started it);
  4. a card on the surface bound to this turn (`asking_with`): the chat window, a job's
     broadcast — or none, for a scheduled run, which has nobody to ask: the answer is no, at
     once (silence is not consent; Hermes resolves unattended runs from policy the same way).
Every decision is one ledger row (`approval_events`). A row that cannot be written never takes
back a refusal or a standing yes (it is logged); the writes after a card's answer, the rule or
grant and its row in one transaction, are part of remembering the answer and fail closed.

What a request IS, and whether it is forbidden outright, is the caller's business —
terminal_policy for commands, Hands for apps. This module remembers and asks. Approve for
me and Full access (PR 7) slot in between 1 and 2.
"""
from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field, replace

from server.db import session as db_session
from server.services import approvals, permission_store

logger = logging.getLogger(__name__)

#: Kinds a card answers for this one time only: never a grant, never a rule.
_ONCE_ONLY = frozenset({"money", "app_risky", "capability", "other_agent", "system", "opaque",
                        "remote", "takeover"})
#: Kinds whose first choice is "for this task": work in an app is many steps.
_TASK_FIRST = frozenset({"app", "shortcut"})
#: Kinds that never offer "Always".
_NEVER_ALWAYS = _ONCE_ONLY | frozenset({"destructive", "screen", "workspace_write", "schedule"})
_EXTRA_MAX = 1024
#: A ledger row's target is kept whole up to this: a bound, not a trim (a many-app card's target
#: is every bundle id joined, and cutting it would cut an app in two).
_TARGET_MAX = 20_000

_EXPIRED = ("Nobody answered the card for {title} in {minutes} minutes. This is NOT a refusal. Don't "
            "retry it in this turn. Finish what you can and tell the user what is waiting.")
_NO_SURFACE = ("{title} needs the user's OK, and this run has nobody to ask (it runs on its "
               "own). It was not done. Tell the user, so they can allow it for next time.")


@dataclass(frozen=True)
class Request:
    kind: str
    target: str                 # the scope a grant or rule is stored under
    title: str                  # the card's question, one line
    detail: str = ""            # what exactly: command, element label, arguments
    why: str = ""               # the model's one-line reason, if any
    always_label: str = ""      # the literal scope "Always" stores; "" hides "Always"
    conversation_ok: bool = True
    extra: dict = field(default_factory=dict)
    frame: dict | None = None   # the caller's card frame (its type and fields); None → propose_action
    #: What "Always" stores: (kind, target) or (kind, target, label); () → ((kind, target),).
    #: An entry without a label stores `always_label`.
    remember_as: tuple[tuple[str, str] | tuple[str, str, str], ...] = ()
    grant_as: tuple[tuple[str, str], ...] = ()      # what a task/conversation grant stores


@dataclass(frozen=True)
class Context:
    conversation_id: str | None
    job_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None  # the turn or job "for this task" covers; filled when empty
    surface: str = "chat"
    user_request: str = ""      # the user's latest words (trusted), for the reviewer (PR 7)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    by: str                     # floor | mode | rule | grant | reviewer | user | expired | policy
    scope: str | None = None    # once | task | conversation | always
    note: str = ""              # the user's "tell Arslan instead"
    model_text: str = ""        # what the tool result tells the model when not allowed


Asker = Callable[[dict], Awaitable[dict]]
_ASKER: ContextVar[Asker | None] = ContextVar("permissions_asker", default=None)
#: The last decision in this context: tool results read it to tell "expired" from "no".
LAST_DECISION: ContextVar[Decision | None] = ContextVar("permissions_last_decision", default=None)


@contextlib.contextmanager
def asking_with(asker: Asker | None) -> Iterator[None]:
    """Bind the card surface for everything awaited inside (a turn, a job)."""
    token = _ASKER.set(asker)
    try:
        yield
    finally:
        _ASKER.reset(token)


def options_for(req: Request) -> list[str]:
    opts = ["task" if req.kind in _TASK_FIRST else "once"]
    if req.conversation_ok and req.kind not in _ONCE_ONLY:
        opts.append("conversation")
    if req.always_label and req.kind not in _NEVER_ALWAYS:
        opts.append("always")
    return opts


async def decide(req: Request, ctx: Context) -> Decision:
    _forget_last()
    ctx = _filled(ctx)
    mode = await _mode()
    standing = await _standing(req, ctx, mode)
    if standing is not None:
        return _done(standing)
    return _done(await _ask(req, ctx, mode))


async def decide_many(reqs: list[Request], ctx: Context, *, title: str) -> list[Decision]:
    """One card for several requests of one kind (Hands' DesktopAccess). Those already allowed
    are left off the card; one answer covers every one shown; decisions in input order.

    The card is the generic `propose_action`, built from the requests' joined details so that it
    names every one of them (their own frames are not used), and it offers the choices of their
    one kind. A list of mixed kinds is a caller bug, since a money step on an app's card would be
    offered "this conversation": it raises ValueError, whatever the store holds."""
    _forget_last()
    if len({r.kind for r in reqs}) > 1:
        raise ValueError("decide_many needs one kind")
    ctx = _filled(ctx)
    mode = await _mode()
    out: list[Decision | None] = [await _standing(r, ctx, mode) for r in reqs]
    shown = [r for r, d in zip(reqs, out) if d is None]
    decided = None
    if shown:
        combined = Request(
            kind=shown[0].kind, target="\x1e".join(r.target for r in shown), title=title,
            detail="\n".join(r.detail or r.target for r in shown),
            always_label=(", ".join(r.always_label for r in shown)
                          if all(r.always_label for r in shown) else ""),
            conversation_ok=all(r.conversation_ok for r in shown),
            extra={"items": [r.extra for r in shown]},
            # The card says every label; each rule keeps its own.
            remember_as=tuple((r.kind, r.target, r.always_label) for r in shown),
            grant_as=tuple((r.kind, r.target) for r in shown))
        decided = await _ask(combined, ctx, mode)
        out = [d if d is not None else decided for d in out]
    decisions: list[Decision] = out          # type: ignore[assignment]
    # What a tool result reads afterwards (LAST_DECISION, LAST_OUTCOME) is the card's answer when
    # a card was shown, not whichever request happens to come last.
    last = decided if decided is not None else (decisions[-1] if decisions else None)
    if last is not None:
        _done(last)
    return decisions


async def would_ask(req: Request, ctx: Context) -> bool:
    """Would `decide` show a card? No side effects: nothing asked, nothing recorded, and no setting
    read (the mode only goes into the ledger row, which `record=False` never writes)."""
    return await _standing(req, _filled(ctx), "", record=False) is None


async def record_standing(req: Request, ctx: Context) -> None:
    """A caller that found a standing answer itself (terminal_policy's legacy rules) still
    writes the ledger row, so the count of decisions stays whole."""
    await _record(req, _filled(ctx), await _mode(), Decision(True, "rule", "always"))


# ── the ladder ────────────────────────────────────────────────────────────────

async def _standing(req: Request, ctx: Context, mode: str, *, record: bool = True) -> Decision | None:
    if req.kind in _ONCE_ONLY:
        return None
    async with db_session.AsyncSessionLocal() as db:
        rule = await permission_store.find_rule(db, req.kind, req.target)
        if rule is not None:
            decision = Decision(True, "rule", "always")
            if record:
                await _note_standing_use(db, req, ctx, mode, decision, rule=rule)
            return decision
        grant = await permission_store.find_grant(db, ctx.conversation_id, ctx.task_id,
                                                  req.kind, req.target)
        if grant is not None:
            decision = Decision(True, "grant", "task" if grant.task_id else "conversation")
            if record:
                await _note_standing_use(db, req, ctx, mode, decision, grant=grant)
            return decision
    return None


async def _note_standing_use(db, req: Request, ctx: Context, mode: str, decision: Decision, *,
                             rule=None, grant=None) -> None:
    """The rule or grant has decided. Counting its use and writing the ledger row come after, and
    a failure there (a locked database, a full disk) must not turn a standing yes into an
    exception: the write is rolled back, logged, and the yes stands. (The lookup above is not
    guarded: a store that cannot be read grants nothing.)"""
    try:
        if rule is not None:
            await permission_store.touch_rule(db, rule)
        await _record_in(db, req, ctx, mode, decision,
                         rule_id=rule.id if rule is not None else None,
                         grant_id=grant.id if grant is not None else None)
        await db.commit()
    except Exception:  # noqa: BLE001 — see above
        logger.warning("approval ledger write failed", exc_info=True)
        with contextlib.suppress(Exception):
            await db.rollback()


async def _ask(req: Request, ctx: Context, mode: str) -> Decision:
    asker = _ASKER.get()
    if asker is None:
        decision = Decision(False, "policy", model_text=_NO_SURFACE.format(title=req.title))
        await _record(req, ctx, mode, decision)
        return decision
    opts = options_for(req)
    base = dict(req.frame) if req.frame else _generic_frame(req)
    call_id = base.get("call_id") or uuid.uuid4().hex
    frame = {**base, "call_id": call_id, "title": req.title, "options": opts,
             "always_label": req.always_label if "always" in opts else "",
             "perm_kind": req.kind, "dedupe": _dedupe(req),
             "expires_at": time.time() + approvals.TIMEOUT_S}
    if req.why and "why" not in frame:
        frame["why"] = req.why[:300]
    started = time.monotonic()
    answer = await asker(frame)
    wait_ms = int((time.monotonic() - started) * 1000)
    # Provenance is the card the user answered: an identical ask that joined a card on screen
    # records that card, not its own never-shown call_id.
    card_id = answer.get("call_id") or call_id
    note = str(answer.get("note") or "").strip()[:500]
    if answer.get("by") is None:
        decision = Decision(False, "expired", model_text=_EXPIRED.format(
            title=req.title, minutes=max(1, int(approvals.TIMEOUT_S // 60))))
    elif answer.get("approved"):
        scope = answer.get("scope") if answer.get("scope") in opts else opts[0]
        if answer.get("by") in approvals.FIRST_CHOICE_ONLY:
            scope = opts[0]                    # the phone and the island answer once only (§A4)
        decision = Decision(True, "user", scope)
    else:
        decision = Decision(False, "user", note=note, model_text=_declined_text(req.title, note))
    async with db_session.AsyncSessionLocal() as db:
        rule_id = grant_id = None
        if decision.allowed and decision.scope == "always":
            for kind, target, *label in req.remember_as or ((req.kind, req.target),):
                rule = await permission_store.add_rule(
                    db, kind, target, label=label[0] if label else req.always_label,
                    created_from=card_id)
                rule_id = rule_id or rule.id
        elif decision.allowed and decision.scope in ("task", "conversation"):
            task = (ctx.task_id or "") if decision.scope == "task" else ""
            if not ctx.conversation_id or (decision.scope == "task" and not task):
                # Nothing to remember it for. The decision says so: a grant with an empty task
                # id would cover the whole conversation, and one with no conversation, nobody.
                decision = replace(decision, scope="once")
            else:
                for kind, target in req.grant_as or ((req.kind, req.target),):
                    grant = await permission_store.add_grant(db, ctx.conversation_id, task, kind,
                                                             target, call_id=card_id)
                    grant_id = grant_id or grant.id
        await _record_in(db, req, ctx, mode, decision, wait_ms=wait_ms, rule_id=rule_id,
                         grant_id=grant_id)
        await db.commit()
    return decision


def _dedupe(req: Request) -> str:
    """Identical asks share one card (§A4): the same kind and target AND everything the card
    shows — its title, its detail and the caller's own frame (without its call_id). Two commands
    under one rule, two schedules, two writes in one folder, writing vs editing one file are not
    identical: one answer must never approve what its card did not show. JSON with sorted keys,
    so no separator inside a field can make two different asks read the same."""
    shown = {k: v for k, v in (req.frame or {}).items() if k != "call_id"}
    return json.dumps([req.kind, req.target, req.title, req.detail, shown], sort_keys=True,
                      default=str)


def _generic_frame(req: Request) -> dict:
    from server.ws import protocol
    return protocol.propose_action(uuid.uuid4().hex, req.kind, req.target, req.detail)


def _declined_text(title: str, note: str) -> str:
    if note:
        return f"The user said no to: {title}. They said: {note}"
    return f"The user said no to: {title}. Don't ask for it again in this turn."


def _forget_last() -> None:
    """A new decision starts: what a tool result reads afterwards must be about it. If it raises,
    that is nothing, not the answer to an earlier request."""
    LAST_DECISION.set(None)
    approvals.LAST_OUTCOME.set(None)


def _done(decision: Decision) -> Decision:
    LAST_DECISION.set(decision)
    approvals.LAST_OUTCOME.set("approved" if decision.allowed
                               else "expired" if decision.by == "expired" else "declined")
    return decision


def _filled(ctx: Context) -> Context:
    from server.services import personal_context
    current = personal_context.current()
    if current is None:
        return replace(ctx, task_id=ctx.task_id or ctx.job_id)
    return replace(ctx, task_id=ctx.task_id or ctx.job_id or getattr(current, "task_id", None),
                   run_id=ctx.run_id or getattr(current, "run_id", None),
                   user_request=ctx.user_request or getattr(current, "query", "") or "")


async def _mode() -> str:
    """Standard (sandbox first) or Careful (the old "ask for every command"). PR 7 adds
    Approve for me and Full access, per conversation."""
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            policy = await settings_service.shell_confirm_policy(db)
    except Exception:  # noqa: BLE001 — an unreadable setting is the default
        return "standard"
    return "careful" if policy == "ask_all" else "standard"


async def _record(req: Request, ctx: Context, mode: str, decision: Decision, **ids) -> None:
    """One ledger row, on its own, for a decision that does not wait on it: a refusal for lack of
    a surface, or `record_standing`."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            await _record_in(db, req, ctx, mode, decision, **ids)
            await db.commit()
    except Exception:  # noqa: BLE001 — such a decision stands even if its row cannot be written
        # (the one write that fails closed is the one after a card's answer, in `_ask`)
        logger.warning("approval ledger write failed", exc_info=True)


async def _record_in(db, req: Request, ctx: Context, mode: str, decision: Decision, *,
                     wait_ms: int | None = None, rule_id: int | None = None,
                     grant_id: int | None = None) -> None:
    await permission_store.record(
        db, conversation_id=ctx.conversation_id, job_id=ctx.job_id,
        run_id=str(ctx.run_id) if ctx.run_id is not None else None,
        kind=req.kind, target=req.target[:_TARGET_MAX], detail=req.detail[:500],
        extra=_extra(req.extra),
        mode=mode, decided_by=decision.by,
        decision=("allow" if decision.allowed else "expired" if decision.by == "expired" else "deny"),
        scope=decision.scope, rule_id=rule_id, grant_id=grant_id, wait_ms=wait_ms)


def _extra(extra: dict) -> dict | None:
    """What the ledger stores: plain JSON, cut to 1 KB. The value that comes back is the parsed
    text, not `extra` itself: the column's own serializer has no `default=str`, so a Path in
    `extra` would fail the insert, after the user has answered."""
    if not extra:
        return None
    try:
        text = json.dumps(extra, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"unserialisable": True}
    return json.loads(text) if len(text) <= _EXTRA_MAX else {"truncated": text[:_EXTRA_MAX]}
