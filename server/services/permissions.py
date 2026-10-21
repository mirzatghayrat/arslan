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
me and Full access (PR 7) slot in between 1 and 2. A request's kind is one of `KINDS`: any other
is a caller bug, and it raises before anything is asked, stored or recorded.
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

#: Every kind a request may have: spec §A11's `Kind`, plus `workspace_write` (the write card the
#: chat window and jobs ask through `decide`). The protections key on these exact strings — the
#: money rung, the once-only kinds, the kinds that never offer "Always" — so a kind outside this
#: set is a caller bug, never an ordinary kind: `decide`, `decide_many` and
#: `record_standing` raise ValueError for it before any card, grant, rule or ledger row ("payment"
#: for "money" would otherwise be offered "In this conversation" and "Always"). A later PR that
#: adds a kind adds it HERE and, in the same change, decides its scope sets below.
KINDS = frozenset({"command", "folder", "outside", "send", "destructive", "system", "screen",
                   "opaque", "app", "app_risky", "money", "takeover", "shortcut", "site",
                   "mcp_tool", "other_agent", "capability", "schedule", "remote",
                   "workspace_write", "network"})
#: What an answer may store (`remember_as`, `grant_as`) is one of `KINDS` or one of these: kinds
#: of a stored rule or grant that are never a request's own. A command's "Always" is a
#: `legacy_rule` per rule it matched (§A9). (§A5 also names the rule kinds `command_prefix` and
#: `mcp_server`: the PR that first stores one adds it here.)
_STORED_ONLY = frozenset({"legacy_rule"})

#: Kinds a card answers for this one time only: never a grant, never a rule.
_ONCE_ONLY = frozenset({"money", "app_risky", "capability", "other_agent", "system", "opaque",
                        "remote", "takeover"})
#: Kinds whose first choice is "for this task": work in an app, or on a site, is many steps — and
#: the island and the phone answer only the first choice (§A4).
_TASK_FIRST = frozenset({"app", "shortcut", "site"})
#: Kinds that never offer "Always". A site's and a Shortcut's are here for 0.1.61 only: the Settings
#: page that lists and removes such rules is a later PR, and until it exists an "Always" for either
#: could be taken back only with the Inbox's 10-second Undo. Take them out of this set, and out of
#: nowhere else, when that page ships: the card, the Inbox's "Always allow" (`always_from`) and the
#: rule lookup (`_standing`) all follow it.
# S2a-1: "network" (a command reaching the network after the turn read outside content) is asked this
# time or for this conversation, never "Always": outside content can steer what it sends.
_NEVER_ALWAYS = (_ONCE_ONLY
                 | frozenset({"destructive", "screen", "workspace_write", "schedule", "site", "shortcut", "network"}))
# The scope sets name kinds of KINDS only: a kind mistyped there would protect nothing.
if not (_ONCE_ONLY | _TASK_FIRST | _NEVER_ALWAYS) <= KINDS:
    raise AssertionError(f"scope sets name unknown kinds: "
                         f"{sorted((_ONCE_ONLY | _TASK_FIRST | _NEVER_ALWAYS) - KINDS)}")
_EXTRA_MAX = 1024
#: A ledger row's target is kept whole up to this: a bound, not a trim (a many-app card's target
#: is every bundle id joined, and cutting it would cut an app in two).
_TARGET_MAX = 20_000

#: The reserved key of the ledger `extra` of what could not be asked — a refusal for want of a
#: surface ("policy"), or a card that never opened while the person was away ("away"): what
#: "Always" on its card would have stored, as [[kind, target, label], …] — written only when the
#: card would have offered "Always" (§A4). The Inbox's "Always allow" stores exactly this set,
#: never a kind or target a client names (`always_from`), and lists it first (`always`).
ALWAYS_KEY = "always"

_EXPIRED = ("Nobody answered the card for {title} in {minutes} minutes. This is NOT a refusal. Don't "
            "retry it in this turn. Finish what you can and tell the user what is waiting.")
# S1 (U14 a): what a run with nobody to ask (a scheduled run) is told when it reaches a step that needs an
# OK. No earlier answer counts there, so it is not told that an "Always" would help (⓪Plan, Q2).
_UNATTENDED = ("{title} needs the user's OK, and this run has nobody to ask: a scheduled run never takes "
               "such a step, and no earlier answer counts here. It was not done. Tell the user; they can do "
               "it in a chat.")


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
    #: 0.1.62 F4a: this card answers for this one time only, whatever its kind: only "once" is
    #: offered, and no stored rule or grant answers it (S1, S2a and S5 use this name).
    once_only: bool = False


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
    #: floor | mode | rule | grant | reviewer | user | expired | policy (§A11). "expired" is also
    #: a card that never opened because the person is away (an earlier card of the job or turn
    #: went unanswered): for the caller it is the same — nobody answered, NOT a refusal — and only
    #: its ledger row says "away" (`_record_in`).
    by: str
    scope: str | None = None    # once | task | conversation | always
    note: str = ""              # the user's "tell Arslan instead"
    model_text: str = ""        # what the tool result tells the model when not allowed


Asker = Callable[[dict], Awaitable[dict]]
_ASKER: ContextVar[Asker | None] = ContextVar("permissions_asker", default=None)
#: The tasks (chat turns, jobs) this process gave a "for this task" grant: what `forget_task` has
#: to delete when one ends. Any other task's end never touches the database — whose write lock a
#: stopped job's own interrupted transaction could hold for seconds (CI 38293278888). A task whose
#: delete failed stays here, for the next forget of that id to retry. What this registry cannot see
#: is closed elsewhere (PR 2c): boot drops every task grant the last run left
#: (`forget_every_task_grant`), and a chat task resumed under its own id drops its grants before it
#: starts (`drop_task_grants`, from `task_service.prepare_resume`).
_GRANTED_TASKS: set[str] = set()
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


def current_asker() -> Asker | None:
    """The card surface bound to this turn or job (`asking_with`), for a caller that wraps it —
    the chat window's shadow judge goes with the cards that are really shown."""
    return _ASKER.get()


def options_for(req: Request) -> list[str]:
    if req.once_only:
        return ["once"]
    opts = ["task" if req.kind in _TASK_FIRST else "once"]
    if req.conversation_ok and req.kind not in _ONCE_ONLY:
        opts.append("conversation")
    if req.always_label and req.kind not in _NEVER_ALWAYS:
        opts.append("always")
    return opts


async def decide(req: Request, ctx: Context) -> Decision:
    _forget_last()
    _check(req)
    ctx = _filled(ctx)
    mode = await _mode()
    # S1 (U14 a): with nobody to ask (a scheduled run), nothing standing answers: an "Always" rule or a
    # grant let a scheduled run act with nobody there. `_ask` then refuses by policy.
    standing = await _standing(req, ctx, mode) if _ASKER.get() is not None else None
    if standing is not None:
        return _done(standing)
    return _done(await _ask(req, ctx, mode))


async def decide_many(reqs: list[Request], ctx: Context, *, title: str) -> list[Decision]:
    """One card for several requests of one kind (Hands' DesktopAccess). Those already allowed
    are left off the card; one answer covers every one shown; decisions in input order.

    The card is the generic `propose_action`, built from the requests' joined details so that it
    names every one of them (their own frames are not used), and it offers the choices of their
    one kind. A list of mixed kinds is a caller bug, since a money step on an app's card would be
    offered "this conversation": it raises ValueError, whatever the store holds — as does any
    request of a kind outside `KINDS`, before any of them is looked up."""
    _forget_last()
    for req in reqs:
        _check(req)
    if len({r.kind for r in reqs}) > 1:
        raise ValueError("decide_many needs one kind")
    ctx = _filled(ctx)
    mode = await _mode()
    # S1 (U14 a): as in `decide`, nothing standing answers when nobody can be asked.
    unattended = _ASKER.get() is None
    out: list[Decision | None] = [None if unattended else await _standing(r, ctx, mode) for r in reqs]
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


#: Who may have decided a standing yes that `record_standing` writes, and the scope it records:
#: an "Always" rule, or the mode (§A8's `decided_by`), which stores nothing and has no scope.
_STANDING_BY = {"rule": "always", "mode": None}


async def record_standing(req: Request, ctx: Context, *, by: str = "rule") -> None:
    """A caller that found a standing answer itself still writes the ledger row, so the count of
    decisions stays whole: `by="rule"` for an "Always" rule it read (terminal_policy's legacy
    rules), `by="mode"` for a step the mode lets start without a card (③Hands' "while I'm away"
    takeover). Any other `by`, like a kind outside `KINDS`, raises ValueError and writes nothing."""
    if not isinstance(by, str) or by not in _STANDING_BY:
        raise ValueError(f"a standing answer is decided by a rule or the mode, not {by!r}")
    _check(req)
    await _record(req, _filled(ctx), await _mode(), Decision(True, by, _STANDING_BY[by]))


async def forget_task(task_id: str | None) -> int:
    """A task's grants end with it (0.1.61 §A5): a job that is done, failed, stopped or cancelled
    leaves no "for this task" grant behind. Its conversation's grants stay. Returns how many went.

    Only a task this process gave such a grant has any (`_GRANTED_TASKS`): for every other one this
    returns at once, without the database. A delete that does not go through — a held write lock
    gives "database is locked", or the wait itself is cancelled — leaves the task registered, for the
    next forget of that id to retry: a chat task is resumed under the same id."""
    if not task_id or task_id not in _GRANTED_TASKS:
        return 0
    # Discarded first: a grant this task is given while the delete runs registers it again.
    _GRANTED_TASKS.discard(task_id)
    try:
        async with db_session.AsyncSessionLocal() as db:
            gone = await permission_store.delete_task_grants(db, task_id)
            await db.commit()
    except BaseException:
        _GRANTED_TASKS.add(task_id)             # still stored: it is still owed
        raise
    return gone


async def forget_every_task_grant() -> int:
    """Boot (0.1.61 §A5, PR 2c): no turn or job survives a restart, so neither does any "for this
    task" grant — those the last run never got to forget (it stopped, or a delete failed) would
    otherwise wait for the 24-hour prune. Conversation grants stay. Returns how many went; a
    failure raises, and the caller (`server.main.lifespan`) logs it and boots on."""
    async with db_session.AsyncSessionLocal() as db:
        gone = await permission_store.delete_every_task_grant(db)
        await db.commit()
    _GRANTED_TASKS.clear()                     # after the commit: a grant still stored is still owed
    return gone


async def drop_task_grants(db, task_id: str) -> int:
    """A chat task resumed under its own id (`task_service.prepare_resume`) starts with none of the
    "for this task" grants it was given before, whatever `_GRANTED_TASKS` says (0.1.61 §A5, PR 2c):
    a grant whose end-of-task delete failed, or that a restart left behind, would answer for the
    resumed run without a card. In the caller's transaction (the resume's own), so a resume that
    does not start drops nothing."""
    return await permission_store.delete_task_grants(db, task_id)


def _check(req: Request) -> None:
    """A kind outside `KINDS` is a caller bug (see there): raised before the store is read, so a
    rule or grant that somehow exists for it decides nothing. What an answer would store is
    checked too, before the card: an unknown kind there would only surface after the user said
    yes."""
    if req.kind not in KINDS:
        raise ValueError(f"unknown permission kind: {req.kind!r}")
    for entry in (*req.remember_as, *req.grant_as):
        kind = entry[0] if entry else None
        if kind not in KINDS and kind not in _STORED_ONLY:
            raise ValueError(f"unknown permission kind to store: {kind!r}")


# ── the ladder ────────────────────────────────────────────────────────────────

async def _standing(req: Request, ctx: Context, mode: str) -> Decision | None:
    if req.kind in _ONCE_ONLY or req.once_only:
        return None
    async with db_session.AsyncSessionLocal() as db:
        # Only a kind whose card offers "Always" has rules: a stray row for any other is not one.
        rule = (await permission_store.find_rule(db, req.kind, req.target)
                if req.kind not in _NEVER_ALWAYS else None)
        if rule is not None:
            decision = Decision(True, "rule", "always")
            await _note_standing_use(db, req, ctx, mode, decision, rule=rule)
            return decision
        grant = await permission_store.find_grant(db, ctx.conversation_id, ctx.task_id,
                                                  req.kind, req.target)
        if grant is not None:
            decision = Decision(True, "grant", "task" if grant.task_id else "conversation")
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
    opts = options_for(req)
    if asker is None:
        # S1 (U14 a, ⓪Plan Q2): refused by policy, and no "Always" set is recorded: the Inbox never offers
        # an "Always" that would read as fixing the scheduled run, which reads no rule.
        decision = Decision(False, "policy", model_text=_UNATTENDED.format(title=req.title))
        await _record(req, ctx, mode, decision)
        return decision
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
    # The card never opened: an earlier card of this job or turn went unanswered, so the person is
    # away and the surface answered at once (`"by": None, "away": True` — BroadcastAsker, the chat
    # window's latch). To the caller and the model it is expired, NOT a refusal. Its ledger row is
    # an expiry decided by "away", with what "Always" on the card would have stored, so the Inbox
    # lists it as it lists a refusal for want of a surface (§A4: "listed in the Inbox the same way").
    away = answer.get("by") is None and bool(answer.get("away"))
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
            for kind, target, label in _always_set(req):
                rule = await permission_store.add_rule(db, kind, target, label=label,
                                                       created_from=card_id)
                rule_id = rule_id or rule.id
        elif decision.allowed and decision.scope in ("task", "conversation"):
            task = (ctx.task_id or "") if decision.scope == "task" else ""
            if not ctx.conversation_id or (decision.scope == "task" and not task):
                # Nothing to remember it for. The decision says so: a grant with an empty task
                # id would cover the whole conversation, and one with no conversation, nobody.
                decision = replace(decision, scope="once")
            else:
                if task:
                    _GRANTED_TASKS.add(task)   # before the write: the task's end must not miss it
                for kind, target in req.grant_as or ((req.kind, req.target),):
                    grant = await permission_store.add_grant(db, ctx.conversation_id, task, kind,
                                                             target, call_id=card_id)
                    grant_id = grant_id or grant.id
        await _record_in(db, req, ctx, mode, decision, wait_ms=None if away else wait_ms,
                         rule_id=rule_id, grant_id=grant_id, away=away,
                         always=_always_set(req) if away and "always" in opts else None)
        await db.commit()
    return decision


def _always_set(req: Request) -> list[list[str]]:
    """What "Always" stores for this request: [kind, target, label] each. An entry of
    `remember_as` without a label stores `always_label`."""
    return [[kind, target, label[0] if label else req.always_label]
            for kind, target, *label in req.remember_as or ((req.kind, req.target),)]


def always_from(extra) -> list[tuple[str, str, str]]:
    """The "Always" set a row of what could not be asked recorded (`ALWAYS_KEY`), or [] when there
    is none or it is not well formed — then nothing may be allowed from that row. A kind never
    remembered is never in it (fail closed: the whole set is refused)."""
    entries = extra.get(ALWAYS_KEY) if isinstance(extra, dict) else None
    if not isinstance(entries, list) or not entries:
        return []
    out: dict[tuple[str, str], str] = {}
    for entry in entries:
        if (not isinstance(entry, list) or len(entry) != 3
                or not all(isinstance(x, str) for x in entry)
                or not entry[0] or not entry[1] or entry[0] in _NEVER_ALWAYS):
            return []
        out.setdefault((entry[0], entry[1]), entry[2])
    return [(kind, target, label) for (kind, target), label in out.items()]


def _dedupe(req: Request) -> str:
    """Identical asks share one card (§A4): the same kind and target, what the card shows — its
    title, its detail and the caller's own frame (without its call_id) — AND everything an answer
    on it can grant: what "Always" stores (`always_label`, `remember_as`), what a grant stores
    (`grant_as`) and whether "In this conversation" is offered (`conversation_ok`). Two commands
    under one rule, two schedules, two writes in one folder, writing vs editing one file, or one
    app vs that app plus another under "Always" are not identical: one answer must never approve
    or store what its card did not show. JSON with sorted keys, so no separator inside a field can
    make two different asks read the same. (The model's `why` is not in it.) A once-only ask
    (0.1.62 F4a) adds one last item, so every other ask's key is what it was."""
    shown = {k: v for k, v in (req.frame or {}).items() if k != "call_id"}
    return json.dumps([req.kind, req.target, req.title, req.detail, shown, req.always_label,
                       req.conversation_ok, [list(e) for e in req.remember_as],
                       [list(e) for e in req.grant_as]] + (["once_only"] if req.once_only else []),
                      sort_keys=True, default=str)


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
    a surface (with the "Always" set it could have offered), or `record_standing`."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            await _record_in(db, req, ctx, mode, decision, **ids)
            await db.commit()
    except Exception:  # noqa: BLE001 — such a decision stands even if its row cannot be written
        # (the one write that fails closed is the one after a card's answer, in `_ask`)
        logger.warning("approval ledger write failed", exc_info=True)


async def _record_in(db, req: Request, ctx: Context, mode: str, decision: Decision, *,
                     wait_ms: int | None = None, rule_id: int | None = None,
                     grant_id: int | None = None, always: list | None = None,
                     away: bool = False) -> None:
    """One ledger row (§A8): `decided_by` is the decision's `by`, and `decision` is allow, deny or
    expired (an expiry is never a deny). One addition to §A8's `decided_by` (0.1.61, F3): "away"
    — `away`, a card that never opened because the person is away. Its decision is "expired" and
    `wait_ms` is None (no card was open); with a refusal for want of a surface ("policy", deny) it
    is what the Inbox lists (`permission_store.NOT_ASKED`)."""
    # The reserved key is the server's alone: a caller's `extra` never supplies an "Always" set,
    # and the set is kept whole, outside the 1 KB cut of the rest.
    extra = {k: v for k, v in (_extra(req.extra) or {}).items() if k != ALWAYS_KEY}
    if always:
        extra[ALWAYS_KEY] = always
    await permission_store.record(
        db, conversation_id=ctx.conversation_id, job_id=ctx.job_id,
        run_id=str(ctx.run_id) if ctx.run_id is not None else None,
        kind=req.kind, target=req.target[:_TARGET_MAX], detail=req.detail[:500],
        extra=extra or None,
        mode=mode, decided_by="away" if away else decision.by,
        decision=("allow" if decision.allowed else "expired" if decision.by == "expired" else "deny"),
        scope=decision.scope, rule_id=rule_id, grant_id=grant_id, wait_ms=wait_ms)


def _reset_for_tests() -> None:
    _GRANTED_TASKS.clear()


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
