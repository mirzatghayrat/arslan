"""Confirmation cards for background work (0.1.42).

A foreground turn asks for confirmation by owning its WebSocket's receive loop
(`server/ws/arslan.py`). Background work cannot: it outlives the turn and may
run while no window is open. Here a card is broadcast to every attached tab,
recorded as pending, and answered by `call_id` from whichever socket receives
the reply. Unanswered cards expire after 30 minutes (0.1.61): expired is never
declined — the model is told nobody answered. A reconnecting tab gets the
still-pending cards again.

The same registry carries the cards of a turn the iPhone started (mobile bridge):
those are shown on the phone and in every Mac window on the conversation, and the
first answer from either decides (`open_card` / `close_card`). Every shared card
ends with a `card_resolved` broadcast, so the copies nobody answered close.

An answer carries a scope, one of the choices its card offered (the phone and the
island give only the first), and on No the user's note (0.1.61 §A4). Identical
requests in one conversation (the same `dedupe` key) share one card; it closes when
its last waiter is done.

A background job asks like a window (0.1.61, `BroadcastAsker`): the same choices, and
the grants and rules of its conversation, through `permissions.decide`. Leaving the
sandbox stays one plain card per command, and a job never uses the sandbox grant a
window was given.
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field

from server.services import desktop_status, run_registry
from server.ws import protocol

TIMEOUT_S = 1800                   # 30 minutes (0.1.61 §A4); hands_tools.CARD_S follows it
#: Where an answer may come from, besides a Mac window ("mac").
SOURCES = ("phone", "inbox", "island")
#: Sources that answer a card this once only: their yes takes the card's first choice and never
#: remembers (0.1.61 §A4: "a phone never grants always"; the island answers Once or No).
FIRST_CHOICE_ONLY = ("phone", "island")
#: How the last card this task waited on ended: "approved", "declined", or "expired" (nobody
#: answered in time). A tool result must not tell the model the user said no when nobody did.
LAST_OUTCOME: ContextVar[str | None] = ContextVar("approvals_last_outcome", default=None)
ANSWERS = {
    "confirm_workspace_write": True, "cancel_workspace_write": False,
    "confirm_schedule": True, "cancel_schedule": False,
    "confirm_run_command": True, "cancel_run_command": False,
    "confirm_action": True, "cancel_action": False,   # 0.1.45 browser / Mac actions
    "confirm_capability": True, "cancel_capability": False,   # 0.1.57 install and retry
}
#: Kinds approved only in the Arslan window that asked (never the Inbox, the phone or the
#: island): the card may carry a key typed on it, and installing code wants the whole card.
WINDOW_ONLY = {"propose_capability"}


@dataclass
class Pending:
    call_id: str
    conversation_id: str
    frame: dict
    future: asyncio.Future = field(repr=False)
    opened_at: float = field(default_factory=time.time)
    #: A window's own card: never replayed into another tab, never broadcast. Only the
    #: Inbox / island answer it from outside that socket (by call_id).
    private: bool = False
    #: How many callers wait on this card: identical requests share it (0.1.61 §A4), and it
    #: is unregistered when the last of them is done with it.
    waiters: int = 1


_pending: dict[str, Pending] = {}


def joining(conversation_id: str, frame: dict) -> Pending | None:
    """The card still waiting in this conversation that `frame` would join (the same `dedupe`
    key: an identical ask, 0.1.61 §A4), or None when it would open a card of its own."""
    key = frame.get("dedupe")
    if not key:
        return None
    for existing in _pending.values():
        if (existing.conversation_id == conversation_id and existing.frame.get("dedupe") == key
                and not existing.future.done()):
            return existing
    return None


def open_card(conversation_id: str, frame: dict, *, broadcast: bool = True) -> Pending:
    """Register one card so a reply from anywhere resolves `pending.future` (see
    `answer`): any socket on the conversation, the Inbox, the island (0.1.55). With
    `broadcast`, it is also sent to every socket on the conversation; a window's own
    turn sends it to its own socket instead. The caller waits and must call
    `close_card` once it is decided or given up on.

    A request identical to one still waiting in this conversation (the same `dedupe` key,
    0.1.61 §A4: parallel calls, a job and its window) opens no second card: the caller
    waits on the one already on screen, and gets that card back (with ITS call_id)."""
    existing = joining(conversation_id, frame)
    if existing is not None:
        existing.waiters += 1                  # the same question, already on screen: one card
        return existing
    pending = Pending(frame["call_id"], conversation_id, frame, asyncio.get_running_loop().create_future(),
                      private=not broadcast)
    _pending[pending.call_id] = pending
    if broadcast:
        run_registry.make_emit(conversation_id)(frame)
    return pending


def close_card(pending: Pending) -> dict:
    """Unregister a card once its last waiter is done and tell every socket how it ended
    (`card_resolved`, once). Returns the decision: approved, remember, scope, note, by."""
    pending.waiters -= 1
    if pending.future.done() and not pending.future.cancelled():
        decision = pending.future.result()
        outcome = "approved" if decision["approved"] else "declined"
    else:
        decision = {"approved": False, "remember": False, "scope": None, "note": "", "by": None}
        outcome = "expired"
        if pending.waiters > 0:
            return decision                    # another waiter still waits on this card
    if _pending.pop(pending.call_id, None) is not None and not pending.private:
        run_registry.make_emit(pending.conversation_id)(
            protocol.card_resolved(pending.call_id, outcome, decision["by"]))
    return decision


async def ask(conversation_id: str, frame: dict) -> bool:
    """Broadcast one card and wait for its answer. False on timeout or refusal.

    The plain card Hands still uses (until it moves onto permissions.decide). Like decide it asks
    only where someone can answer: a chat turn and a job bind a card surface
    (permissions.asking_with); a run with none — a scheduled run — is refused at once, with no
    card, no wait and (unlike decide) no ledger row yet. While it waits, the wall clocks of the
    turn or job stand still (`task_service.paused_clock`)."""
    from server.services import permissions
    _forget_decision()
    LAST_OUTCOME.set(None)
    if permissions.current_asker() is None:
        LAST_OUTCOME.set("declined")         # as decide's refusal for want of a surface
        return False
    # Marked so the card can say it is a background job asking, and hide the
    # "remember" option this path never honours.
    pending = open_card(conversation_id, frame | {"background": True})
    try:
        with _paused_clock(), desktop_status.awaiting_approval(conversation_id):
            await asyncio.wait_for(asyncio.shield(pending.future), timeout=TIMEOUT_S)
    except TimeoutError:
        pass
    finally:
        decision = close_card(pending)
    # close_card answers "by" nobody exactly when the card expired.
    LAST_OUTCOME.set("approved" if decision["approved"] else "expired" if decision["by"] is None else "declined")
    return bool(decision["approved"])


def answer(data: dict) -> bool:
    """Route one reply frame to a pending shared card. True if it was one.

    Only a reply of the card's own kind resolves it: a `confirm_schedule` can
    never approve a pending command card. The first reply decides; a later one
    (the other side answering too) is swallowed.

    The decision carries a scope, one of the card's `options` (0.1.61 §A4): what the
    reply chose, else the old "remember" checkbox mapped (`_legacy_scope`); the phone and
    the island give only the first option. A "No" carries the user's note.
    """
    call_id = data.get("call_id") if isinstance(data, dict) else None
    kind = data.get("type") if isinstance(data, dict) else None
    pending = _pending.get(call_id) if isinstance(call_id, str) else None
    if pending is None or kind not in ANSWERS or not _same_kind(kind, pending.frame["type"]):
        return False
    # The Bridge marks what the phone sends; the Inbox and the island mark theirs
    # (0.1.55); anything else is a Mac window.
    by = data.get("source") if data.get("source") in SOURCES else "mac"
    if ANSWERS[kind] and pending.frame["type"] in WINDOW_ONLY and by != "mac":
        return True                         # swallowed: only the asking window approves this one
    if not pending.future.done():
        options = [o for o in pending.frame.get("options") or [] if isinstance(o, str)]
        scope, remember = data.get("scope"), bool(data.get("remember"))
        if by in FIRST_CHOICE_ONLY:
            # Never more than once from there: no wider scope, and no "remember" either (the
            # window's legacy "don't ask again" reads it).
            scope, remember = (options[0] if options else None), False
        elif (scope is None and not remember and "conversation" in options
                and pending.frame["type"] in ("propose_workspace_write", "propose_schedule")):
            # Until PR 2b sends scopes (remove this branch then): today's UI answers these two
            # cards with neither a scope nor "remember", and such a yes held for the socket or the
            # job (the per-socket and per-job grants this PR removed): "in this conversation".
            scope = "conversation"
        elif scope not in options:
            scope = _legacy_scope(options, remember)
        decision = {"approved": ANSWERS[kind], "remember": remember,
                    "scope": scope if ANSWERS[kind] else None,
                    "note": "" if ANSWERS[kind] else str(data.get("note") or "").strip()[:500],
                    "by": by}
        if pending.frame["type"] in WINDOW_ONLY:
            decision["extras"] = _extras(pending.frame, data) if ANSWERS[kind] else {}
        pending.future.set_result(decision)
    return True


def _legacy_scope(options: list[str], remember: bool) -> str | None:
    """A reply without a scope (the UI before 0.1.61 PR 2b): the old checkbox, mapped."""
    if not options:
        return None
    if remember:
        for preferred in ("always", "conversation"):
            if preferred in options:
                return preferred
    return options[0]


def _extras(frame: dict, data: dict) -> dict:
    """What an approval may carry (0.1.57): values for the keys THIS card asked for, and the
    folders it offered — a subset the user kept, never one it added. Anything else is dropped."""
    if frame.get("type") != "propose_capability":
        return {}
    asked = {k.get("name") for k in frame.get("keys") or [] if isinstance(k, dict)}
    keys = {name: value.strip()[:2000] for name, value in (data.get("keys") or {}).items()
            if name in asked and isinstance(value, str) and value.strip()} if isinstance(data.get("keys"), dict) else {}
    offered = list(frame.get("folders") or [])
    kept = [f for f in data.get("folders") or [] if f in offered] if isinstance(data.get("folders"), list) else offered
    return {"keys": keys, "folders": kept}


def _same_kind(reply: str, card: str) -> bool:
    return reply.split("_", 1)[1] == card.split("_", 1)[1]


def pending_cards(conversation_id: str) -> list[dict]:
    """Shared cards to replay into a (re)connecting socket — never a window's private one."""
    return [p.frame for p in _pending.values() if p.conversation_id == conversation_id and not p.private]


def known_ids() -> set[str]:
    return set(_pending)


def waiters(call_id: str) -> int:
    """How many callers still wait on this card (0 once it is decided or gone)."""
    pending = _pending.get(call_id)
    return pending.waiters if pending is not None and not pending.future.done() else 0


#: Terminal rules whose command deletes, sends, publishes or reaches elsewhere — and
#: AppleScript / Shortcuts, which can do any of those from inside an app.
_ISLAND_RISKY_RULES = {"delete", "send-mail", "send-message", "upload", "publish", "git-push",
                       "remote-shell", "apple-events", "login-items", "install"}
_RISKY_SCRIPT = re.compile(r"\b(?:delete|send|move|do\s+shell\s+script|purchase|buy|pay|submit|transfer|empty\s+trash)\b",
                           re.IGNORECASE)


def island_may_answer(frame: dict) -> bool:
    """0.1.55 decision 3: the island answers every card except a risky one (delete, send,
    pay, buy, transfer, submit) — those are answered in Arslan, with the whole context in
    view. Fail-closed: a kind this does not know is not answerable from the island."""
    kind = frame.get("type")
    if kind in ("propose_workspace_write", "propose_schedule"):
        return True
    if kind == "propose_action":
        action = frame.get("kind")
        if action in ("browser_site", "desktop_look", "desktop_app", "mac_shortcut",
                      "desktop_takeover"):          # Hands v2 §6.4: the island may answer it
            return True
        if action == "mac_script":
            return not _RISKY_SCRIPT.search(str(frame.get("detail") or ""))
        return False                       # desktop_risky, and anything new
    if kind == "propose_run_command":
        if frame.get("remote_host") or frame.get("sandbox") in ("outside", "retry"):
            return False                   # another machine, or writing outside the sandbox
        from server.services import terminal_policy
        verdict = terminal_policy.assess(str(frame.get("pretty") or ""))
        return verdict.level != "forbid" and verdict.rule not in _ISLAND_RISKY_RULES \
            and not verdict.rule.startswith("hermes:")
    return False


def all_pending() -> list[dict]:
    """Every card waiting for the user, in any conversation, oldest first (0.1.55: the
    Inbox's "现在就要你批准" and the island). `expires_at` is when it expires unanswered (never
    a refusal); `island_ok` says whether the island may answer it (see `island_may_answer`)."""
    rows = sorted(_pending.values(), key=lambda p: p.opened_at)
    return [{"call_id": p.call_id, "conversation_id": p.conversation_id, "frame": p.frame,
             "opened_at": p.opened_at, "expires_at": p.opened_at + TIMEOUT_S,
             "island_ok": island_may_answer(p.frame)}
            for p in rows if not p.future.done()]


class OpenInArslan(Exception):
    """A risky card was answered from the island: it is answered in Arslan only."""


def answer_by_id(call_id: str, approve: bool, *, source: str, remember: bool = False,
                 scope: str | None = None, note: str = "") -> bool:
    """Answer one pending card by id from outside a socket (Inbox, island). Same rule
    as `answer`: the reply is built from the card's own kind, so it can only ever
    confirm or cancel THAT card; its scope and note are `answer`'s too."""
    pending = _pending.get(call_id)
    if pending is None:
        return False
    if approve and pending.frame.get("type") in WINDOW_ONLY:
        raise OpenInArslan(call_id)
    if source == "island" and approve and not island_may_answer(pending.frame):
        # Enforced here, not only by hiding the buttons: the island page is a client.
        # Declining is always safe, so only an approval is refused.
        raise OpenInArslan(call_id)
    kind = pending.frame["type"].removeprefix("propose_")
    return answer({"type": f"{'confirm' if approve else 'cancel'}_{kind}", "call_id": call_id,
                   "remember": remember, "scope": scope, "note": note, "source": source})


def decline_pending(call_ids: set[str], note: str, *, source: str = "mac",
                    mine: dict[str, int] | None = None) -> int:
    """Answer these waiting cards No, with the user's words as the note — a message typed in
    the window while its card waits (spec §A4). Returns how many were answered.

    With `mine` (call_id → how many of the card's waiters are the caller's), a card someone else
    waits on too — a job that asked the identical question — is left open for them: the caller
    only stops waiting on it."""
    answered = 0
    for call_id in list(call_ids):
        pending = _pending.get(call_id)
        if pending is None or pending.future.done():
            continue
        if mine is not None and pending.waiters > mine.get(call_id, 0):
            continue
        pending.future.set_result({"approved": False, "remember": False, "scope": None,
                                   "note": note.strip()[:500], "by": source})
        answered += 1
    return answered


class BroadcastAsker:
    """A background job's card surface (0.1.61): every window on the conversation, the Inbox,
    the island and the phone see the card. Once one card in the job went unanswered the person
    is away: later cards do not open and wait 30 minutes each; they read as expired at once
    (seen on a device 2026-10-05: a model told "expired" asked again within two seconds)."""

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.unanswered = False

    async def __call__(self, frame: dict) -> dict:
        _forget_decision()
        if self.unanswered:
            LAST_OUTCOME.set("expired")
            return {"approved": False, "remember": False, "scope": None, "note": "", "by": None}
        pending = open_card(self.conversation_id, frame | {"background": True})
        try:
            with _paused_clock(), desktop_status.awaiting_approval(self.conversation_id):
                await asyncio.wait_for(asyncio.shield(pending.future), timeout=TIMEOUT_S)
        except TimeoutError:
            pass
        finally:
            decision = close_card(pending)
        if decision["by"] is None:
            self.unanswered = True
        LAST_OUTCOME.set("approved" if decision["approved"]
                         else "expired" if decision["by"] is None else "declined")
        # The card the user answered: an identical ask that joined it records that one (§A8).
        # A copy: waiters on one card share the decision dict.
        return {**decision, "call_id": pending.call_id}


class JobConfirmations:
    """The three confirmation callbacks the tool loop expects, for one job. Its cards are its
    `BroadcastAsker`'s. Rule cards, the workspace write and the schedule are decided by
    `permissions.decide` (0.1.61): the window's choices, and the grants and rules of the job's
    conversation — a job's grants are its conversation's. Leaving the sandbox and another
    machine stay plain cards: one answer, nothing remembered."""

    def __init__(self, conversation_id: str, job_id: str | None = None):
        self.conversation_id = conversation_id
        self.job_id = job_id
        self.asker = BroadcastAsker(conversation_id)

    def _context(self):
        """Where a decision of this job is made: its ledger rows carry the job id (§A8)."""
        from server.services import permissions
        return permissions.Context(conversation_id=self.conversation_id, job_id=self.job_id,
                                   surface="job")

    async def _card(self, frame: dict) -> bool:
        return bool((await self.asker(frame))["approved"])

    async def workspace_write(self, action: str, path: str) -> bool:
        from server.db import session as db_session
        from server.services import permissions, settings_service
        async with db_session.AsyncSessionLocal() as db:
            root = await settings_service.workspace_dir(db)
        if root is None:
            _forget_decision()                 # no card: the refusal is not an earlier answer
            LAST_OUTCOME.set(None)
            return False
        # Decided with that session closed: decide opens its own, and a card may wait 30 minutes.
        with permissions.asking_with(self.asker):
            decision = await permissions.decide(permissions.Request(
                kind="workspace_write", target=str(root), title=f"Let Arslan write in {root.name}?",
                detail=path, frame=protocol.propose_workspace_write(uuid.uuid4().hex, str(root),
                                                                    action, path)),
                self._context())
        return decision.allowed

    async def schedule(self, name: str, when: str) -> bool:
        from server.services import permissions
        with permissions.asking_with(self.asker):
            decision = await permissions.decide(permissions.Request(
                kind="schedule", target="*", title=f"Schedule “{name}”?", detail=when,
                frame=protocol.propose_schedule(uuid.uuid4().hex, name, when)),
                self._context())
        return decision.allowed

    async def command(self, command: str, argv: list, *, remote_host: str | None = None,
                      fingerprints: list | None = None, sandbox: str | None = None, why: str = "") -> bool:
        from server.db import session as db_session
        from server.services import settings_service
        from server.services import terminal_policy
        from server.ws.arslan import effective_risk, may_skip_card
        risk = effective_risk(remote_host, command, argv)
        verdict = terminal_policy.assess(terminal_policy.as_shell(command, argv))
        if sandbox in ("outside", "retry"):
            # 0.1.51 P3: leaving the sandbox is always a card; a job's card offers no
            # "rest of the conversation", and a job never uses one the chat window was
            # given: that grant is a session grant.
            return await self._ask_with_shadow(protocol.propose_run_command(
                uuid.uuid4().hex, command, argv, reason=verdict.reason if verdict.level == "ask" else "",
                sandbox=sandbox, why=why), command, verdict, sandboxed=False)
        policy, standing = "", False
        if not remote_host:
            async with db_session.AsyncSessionLocal() as db:
                policy = await settings_service.shell_confirm_policy(db)
                standing = terminal_policy.standing_allows(terminal_policy.as_shell(command, argv),
                                                           await terminal_policy.always_allowed(db))
        # The user's standing answer is taken below, where it writes its ledger row.
        if may_skip_card(remote_host, policy=policy, risk=risk):
            return True
        if remote_host:
            return await self._card(protocol.propose_run_command(
                uuid.uuid4().hex, command, argv, reason=verdict.reason or f"risk: {risk}",
                remote_host=remote_host, fingerprints=list(fingerprints or [])))
        shell = terminal_policy.as_shell(command, argv)
        rules = sorted(terminal_policy.ask_rules(shell))
        if standing:
            from server.services import permissions
            await permissions.record_standing(_command_request(shell, rules, None), self._context())
            return True
        frame = protocol.propose_run_command(
            uuid.uuid4().hex, command, argv, reason=verdict.reason or f"risk: {risk}",
            rule=verdict.rule or None)
        return await self._decide_with_shadow(_command_request(shell, rules, frame), command, verdict)

    async def _ask_with_shadow(self, frame: dict, command: str, verdict, *, sandboxed: bool | None = None) -> bool:
        """0.1.52 S2: the card as before, plus a shadow judgment recorded with the real answer."""
        from server.services import judgment
        judgment.shadow("tool.approval", judgment.approval_state(command, rule=verdict.rule, reason=verdict.reason,
                                                                 sandboxed=sandboxed),
                        ref=frame["call_id"], conversation_id=self.conversation_id)
        approved = await self._card(frame)
        judgment.record_outcome_later(frame["call_id"], "approved" if approved else "declined", point="tool.approval")
        return approved

    async def _decide_with_shadow(self, req, command: str, verdict) -> bool:
        """`_ask_with_shadow` for a rule card, decided by `permissions.decide` on this job's card
        surface. The shadow judgment goes with a card the user is shown: none when a rule or a
        grant decides, none once the job stopped waiting, and one per card (an identical ask that
        joins a card on screen is not judged again). It is joined to the real answer: "expired"
        when nobody answered, never "declined"."""
        from server.services import judgment, permissions
        judged: list[str] = []

        async def ask(frame: dict) -> dict:
            # No await between this check and the card opening inside `self.asker`.
            if not self.asker.unanswered and joining(self.conversation_id, frame) is None:
                judgment.shadow("tool.approval", judgment.approval_state(command, rule=verdict.rule,
                                                                         reason=verdict.reason),
                                ref=frame["call_id"], conversation_id=self.conversation_id)
                judged.append(frame["call_id"])
            return await self.asker(frame)

        with permissions.asking_with(ask):
            decision = await permissions.decide(req, self._context())
        outcome = ("approved" if decision.allowed
                   else "expired" if decision.by == "expired" else "declined")
        for ref in judged:
            judgment.record_outcome_later(ref, outcome, point="tool.approval")
        return decision.allowed


def _command_request(shell: str, rules: list[str], frame: dict | None):
    """A rule card as a permission request: "In this conversation" covers this kind of command
    (its rules) here; "Always" stores EVERY rule it matched (spec §A9 — the first rule alone
    could never silence `rm -rf build`, which matches two), each under its own words."""
    from server.services import permissions, terminal_policy
    return permissions.Request(
        kind="command", target="|".join(rules) or shell, title=f"Run `{shell[:80]}`?", detail=shell,
        always_label=", ".join(terminal_policy.describe(r) for r in rules),
        remember_as=tuple(("legacy_rule", r, terminal_policy.describe(r)) for r in rules), frame=frame)


def _paused_clock():
    """The wall clocks of the running turn or job stand still while a card waits
    (`task_service.paused_clock`)."""
    from server.services import task_service
    return task_service.paused_clock()


def _forget_decision() -> None:
    """A card starts: an earlier decision is not its answer. `tool_loop._declined` reads
    `permissions.LAST_DECISION` first, so a plain card (leaving the sandbox, another machine)
    must not be told the words of a decide card before it; a decide card sets its own after."""
    from server.services import permissions
    permissions.LAST_DECISION.set(None)


def _reset_for_tests() -> None:
    for pending in _pending.values():
        if not pending.future.done():
            pending.future.cancel()
    _pending.clear()
