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
its last waiter is done, and nobody waits on it past the expiry it shows.

A background job asks like a window (0.1.61, `BroadcastAsker`): the same choices, and
the grants and rules of its conversation, through `permissions.decide`. Leaving the
sandbox stays one plain card per command, and a job never uses the sandbox grant a
window was given.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
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
#: S2a-1: who answered the last plain card this task waited on ("mac" for the asking window, or a
#: SOURCES entry), None when nobody did. Only the asking window's own click unlocks a bare run (U11).
LAST_ANSWERED_BY: ContextVar[str | None] = ContextVar("approvals_last_answered_by", default=None)
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
#: The permission kinds whose card is answered only where its whole card is shown, whatever type of frame carries it (0.1.57: installing
#: code wants the whole card). The web names the same kinds (`WINDOW_ONLY_KINDS`, askParts.tsx); tests/server/test_card_kinds.py keeps them equal.
WINDOW_ONLY_KINDS = frozenset({"capability"})


def window_only(frame: dict) -> bool:
    """Whether this card is answered only by the asking window (0.1.61 §A4, PR 2b final review M6): the capability proposal, or any card
    that carries the `capability` permission kind (a `propose_action` frame rides it). The phone never gets one and the island refuses it;
    a yes from the phone is swallowed and a yes from the Inbox or the island is "open in Arslan". Saying no is allowed from anywhere."""
    perm_kind = frame.get("perm_kind")
    return (frame.get("type") in WINDOW_ONLY or (isinstance(perm_kind, str) and perm_kind in WINDOW_ONLY_KINDS)
            or _runs_bare(frame))


def _runs_bare(frame: dict) -> bool:
    """S2a-1 (U11, ⓪Plan for v0.1.63): a command card whose command, approved, runs with no sandbox at all
    (one plain osascript or `shortcuts run`, `task_service.unwrapped_once`) is approved only in the window,
    where the whole command is shown. Decided from the card's own command, so no frame field changes.
    v0.1.64 candidate: allow it from the phone once the phone's card shows the whole script."""
    if frame.get("type") != "propose_run_command" or frame.get("remote_host"):
        return False
    from server.services import task_service, terminal_policy
    # The shell line the tool loop runs (terminal_policy.as_shell, as tool_loop builds it), never the
    # card's display field: the card and the executor are judged on the same string (③Hands, #265).
    command = terminal_policy.as_shell(frame.get("command"), frame.get("argv"))
    return bool(terminal_policy.ask_rules(command) & terminal_policy.BARE_RULES) \
        and task_service.unwrapped_once(command)


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
    #: When it expires unanswered (wall clock, what the Inbox shows): set once, when it opens.
    expires_at: float = 0.0
    #: The same moment on the monotonic clock, which every waiter waits until — an identical ask
    #: that joins it later too — so the card never outlives the expiry it shows, and a step of
    #: the system clock never lengthens or ends a wait.
    deadline: float = 0.0

    def __post_init__(self) -> None:
        if not self.expires_at:
            self.expires_at = self.opened_at + TIMEOUT_S
        if not self.deadline:
            self.deadline = time.monotonic() + TIMEOUT_S


_pending: dict[str, Pending] = {}


def remaining(pending: Pending) -> float:
    """How long a waiter on this card may still wait: what is left of the card's own time, never
    a fresh `TIMEOUT_S` (PR 2b plan review: one waiting on a card it joined must not keep it open
    past the expiry it showed; when the card expires, every waiter reads it as expired together)."""
    return max(0.0, pending.deadline - time.monotonic())


def joining(conversation_id: str, frame: dict) -> Pending | None:
    """The card still waiting in this conversation that `frame` would join (the same `dedupe`
    key: an identical ask, 0.1.61 §A4), or None when it would open a card of its own."""
    key = frame.get("dedupe")
    if not key:
        return None
    for existing in _pending.values():
        if (existing.conversation_id == conversation_id and existing.frame.get("dedupe") == key
                and not existing.future.done() and remaining(existing) > 0):
            return existing                # (a card whose time is up is not joined: never shown)
    return None


def open_card(conversation_id: str, frame: dict, *, broadcast: bool = True,
              skip: Callable[[dict], None] | None = None) -> Pending:
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
        # `skip` (S2a-1b, see ws/arslan._ask_everywhere): one socket left out, the Bridge's.
        emit = run_registry.make_emit(conversation_id) if skip is None else run_registry.make_emit(
            conversation_id, skip=skip)
        emit(frame)
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


def answer(data: dict) -> bool:
    """Route one reply frame to a pending shared card. True if it was one.

    Only a reply of the card's own kind resolves it: a `confirm_schedule` can
    never approve a pending command card. The first reply decides; a later one
    (the other side answering too) is swallowed.

    The decision carries a scope, one of the card's `options` (0.1.61 §A4): what the reply
    chose, else the card's first, narrowest choice; the phone and the island give only the first
    option. A "No" carries the user's note.
    """
    call_id = data.get("call_id") if isinstance(data, dict) else None
    kind = data.get("type") if isinstance(data, dict) else None
    pending = _pending.get(call_id) if isinstance(call_id, str) else None
    if pending is None or kind not in ANSWERS or not _same_kind(kind, pending.frame["type"]):
        return False
    # The Bridge marks what the phone sends; the Inbox and the island mark theirs
    # (0.1.55); anything else is a Mac window.
    by = data.get("source") if data.get("source") in SOURCES else "mac"
    if ANSWERS[kind] and window_only(pending.frame) and by != "mac":
        return True                         # swallowed: only the asking window approves this one
    if not pending.future.done() and remaining(pending) > 0:      # none after the card's time
        options = [o for o in pending.frame.get("options") or [] if isinstance(o, str)]
        scope, remember = data.get("scope"), bool(data.get("remember"))
        if by in FIRST_CHOICE_ONLY:
            # Never more than once from there: no wider scope, and no "remember" either (the
            # window's legacy "don't ask again" reads it).
            scope, remember = (options[0] if options else None), False
        elif scope not in options:
            # 0.1.61 PR 2b: the window and the Inbox send the scope the user chose; the island and the
            # phone send none and are clamped to the first choice above. A yes with none from anywhere
            # else (a tab left open from before the update, a script) gets the card's first, narrowest
            # choice too: it is asked again next time, never silently widened to the conversation.
            scope = options[0] if options else None
        decision = {"approved": ANSWERS[kind], "remember": remember,
                    "scope": scope if ANSWERS[kind] else None,
                    "note": "" if ANSWERS[kind] else str(data.get("note") or "").strip()[:500],
                    "by": by}
        if pending.frame["type"] in WINDOW_ONLY:
            decision["extras"] = _extras(pending.frame, data) if ANSWERS[kind] else {}
        pending.future.set_result(decision)
    return True


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


def _island_risky_rules() -> frozenset[str]:
    """S2a-2: every layer ② rule (it sends, deletes, changes the system or reaches another app) and
    `unreadable` — read from terminal_policy, never copied — plus the network card's kind."""
    from server.services import terminal_policy
    return terminal_policy.ONCE_ONLY_RULES | {"network"}
#: The permission kinds whose `propose_action` card the island answers (0.1.61 §A4: "Once (For
#: this task) or No for folder, app (look and act, merged), screen, MCP tool, schedule, site and
#: Shortcut cards"). Everything else opens Arslan: money, send, delete, a risky step in an app, a
#: takeover, leaving the sandbox, system changes, other agents' settings, new capabilities,
#: another machine — and any kind this does not know.
ISLAND_KINDS = frozenset({"folder", "app", "screen", "mcp_tool", "schedule", "site", "shortcut"})
#: The permission kinds a card of any type may carry and still be answerable from the island: those
#: of `ISLAND_KINDS`, and the kinds of the cards that are not a `propose_action` — a command (which
#: its own rules below then decide), a write in the workspace, a schedule.
_ISLAND_CARD_KINDS = ISLAND_KINDS | {"command", "workspace_write", "schedule"}


def island_may_answer(frame: dict) -> bool:
    """0.1.55 decision 3: the island answers every card except a risky one (delete, send,
    pay, buy, transfer, submit) — those are answered in Arslan, with the whole context in
    view. Fail-closed: a kind this does not know is not answerable from the island.

    0.1.61 §A4: a card that permissions.decide shows carries its permission kind (`perm_kind`), and
    it gates every card type: one outside `_ISLAND_CARD_KINDS` is never answerable, whatever its
    type or command text says (PR 3a rides send, delete and system cards on `propose_run_command`
    frames). Past that gate a `propose_action` card is decided by `ISLAND_KINDS` alone — never the
    legacy `kind` its caller's frame may keep, which would let the island answer a takeover — and
    the other card types by their own rule. A `propose_action` card without a permission kind is
    not answerable: none is sent (permissions._ask stamps every card), so one is something new."""
    kind = frame.get("type")
    if window_only(frame):
        return False                       # answered in the asking window only (capability, a bare run)
    if "perm_kind" in frame:
        perm_kind = frame["perm_kind"]
        if not (isinstance(perm_kind, str) and perm_kind in _ISLAND_CARD_KINDS):
            return False
    if kind in ("propose_workspace_write", "propose_schedule"):
        return True
    if kind == "propose_action":
        perm_kind = frame.get("perm_kind")
        return isinstance(perm_kind, str) and perm_kind in ISLAND_KINDS
    if kind == "propose_run_command":
        if (frame.get("remote_host") or frame.get("sandbox") in ("outside", "retry") or frame.get("unsandboxed")
                or frame.get("network")):
            return False                   # another machine, outside the sandbox, or the network too (S2a-2)
        from server.services import terminal_policy
        verdict = terminal_policy.assess(str(frame.get("pretty") or ""))
        return verdict.level != "forbid" and verdict.rule not in _island_risky_rules()
    return False


def all_pending() -> list[dict]:
    """Every card waiting for the user, in any conversation, oldest first (0.1.55: the
    Inbox's "现在就要你批准" and the island). `expires_at` is when it expires unanswered (never
    a refusal); `island_ok` says whether the island may answer it (see `island_may_answer`)."""
    rows = sorted(_pending.values(), key=lambda p: p.opened_at)
    return [{"call_id": p.call_id, "conversation_id": p.conversation_id, "frame": p.frame,
             "opened_at": p.opened_at, "expires_at": p.expires_at,
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
    if pending is None or (not pending.future.done() and remaining(pending) == 0):
        return False                            # gone, or its time is up: "answered or expired"
    if approve and window_only(pending.frame):
        raise OpenInArslan(call_id)
    if source == "island" and approve and not island_may_answer(pending.frame):
        # Enforced here, not only by hiding the buttons: the island page is a client.
        # Declining is always safe, so only an approval is refused.
        raise OpenInArslan(call_id)
    kind = pending.frame["type"].removeprefix("propose_")
    return answer({"type": f"{'confirm' if approve else 'cancel'}_{kind}", "call_id": call_id,
                   "remember": remember, "scope": scope, "note": note, "source": source})


def decline_pending(call_ids: set[str], note: str, *, source: str,
                    mine: dict[str, int] | None = None) -> int:
    """Answer these waiting cards No, with the user's words as the note — a message typed in
    the window while its card waits (spec §A4). Returns how many were answered.

    `source` is the surface that typed — "mac" for a window, "phone" for a message the phone sent
    during its turn — and every screen is told so (`card_resolved`): a card the phone answered
    must not read "answered on Mac" (PR 2b plan review). Like `answer`, anything else is "mac".

    With `mine` (call_id → how many of the card's waiters are the caller's), a card someone else
    waits on too — a job that asked the identical question — is left open for them: the caller
    only stops waiting on it."""
    by = source if source in SOURCES else "mac"
    answered = 0
    for call_id in list(call_ids):
        pending = _pending.get(call_id)
        if pending is None or pending.future.done() or remaining(pending) == 0:
            continue
        if mine is not None and pending.waiters > mine.get(call_id, 0):
            continue
        pending.future.set_result({"approved": False, "remember": False, "scope": None,
                                   "note": note.strip()[:500], "by": by})
        answered += 1
    return answered


class BroadcastAsker:
    """A background job's card surface (0.1.61): every window on the conversation, the Inbox,
    the island and the phone see the card. Once one card in the job went unanswered the person
    is away: later cards do not open and wait 30 minutes each; they read as expired at once
    (seen on a device 2026-10-05: a model told "expired" asked again within two seconds).

    Such an answer is marked `"away": True` (with `"by": None`, as an expiry): permissions.decide
    records it as an expiry decided by "away", with what "Always" on the card would have stored,
    and the Inbox lists it with "Always allow" (§A4: "listed in the Inbox the same way"). Not yet
    for a plain card (leaving the sandbox, another machine): it writes no ledger row at all, so one
    refused this way is not listed until it asks through decide (PR 3)."""

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.unanswered = False

    async def __call__(self, frame: dict) -> dict:
        _forget_decision()
        if self.unanswered:
            LAST_OUTCOME.set("expired")
            return {"approved": False, "remember": False, "scope": None, "note": "", "by": None,
                    "away": True}
        pending = open_card(self.conversation_id, frame | {"background": True})
        try:
            with _paused_clock(), desktop_status.awaiting_approval(self.conversation_id):
                await asyncio.wait_for(asyncio.shield(pending.future), timeout=remaining(pending))
        except TimeoutError:
            pass
        finally:
            decision = close_card(pending)
        if decision["by"] is None:
            self.unanswered = True
        LAST_OUTCOME.set("approved" if decision["approved"]
                         else "expired" if decision["by"] is None else "declined")
        LAST_ANSWERED_BY.set(decision["by"])
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
                      fingerprints: list | None = None, sandbox: str | None = None, why: str = "",
                      network: bool = False) -> bool:
        from server.db import session as db_session
        from server.services import settings_service
        from server.services import terminal_policy
        from server.ws.arslan import effective_risk
        risk = effective_risk(remote_host, command, argv)
        verdict = terminal_policy.assess(terminal_policy.as_shell(command, argv))
        if sandbox in ("outside", "retry"):
            # 0.1.51 P3: leaving the sandbox is always a card; a job's card offers no
            # "rest of the conversation", and a job never uses one the chat window was
            # given: that grant is a session grant.
            return await self._card(protocol.propose_run_command(
                uuid.uuid4().hex, command, argv, reason=verdict.reason if verdict.level == "ask" else "",
                sandbox=sandbox, why=why, network=network))
        # S2a-2: called, a card is shown (the tool loop decided whether one is needed).
        if remote_host:
            return await self._card(protocol.propose_run_command(
                uuid.uuid4().hex, command, argv, reason=verdict.reason or f"risk: {risk}",
                remote_host=remote_host, fingerprints=list(fingerprints or [])))
        async with db_session.AsyncSessionLocal() as db:
            ask_all = await settings_service.shell_confirm_policy(db) == "ask_all"
        shell = terminal_policy.as_shell(command, argv)
        rules = sorted(terminal_policy.ask_rules(shell))
        frame = protocol.propose_run_command(
            uuid.uuid4().hex, command, argv, reason=verdict.reason or f"risk: {risk}",
            rule=verdict.rule or None, network=network)
        from server.services import permissions
        with permissions.asking_with(self.asker):
            decision = await permissions.decide(
                _command_request(shell, rules, frame, ask_all=ask_all, network=network), self._context())
        return decision.allowed


def _command_request(shell: str, rules: list[str], frame: dict | None, *, ask_all: bool = False,
                     network: bool = False):
    """A command card as a permission request, by the command's layer (S2a-2):

    - layer ② or `unreadable` (it matched rules): this time only; nothing is remembered and no stored
      answer stands. The target `rules:<rule>|<rule>…` (sorted) lists every rule it matched.
    - "ask for every command": `text:<command>`, exactly that text, this time or in this conversation.
    - layer ③ outside the sandbox (switched off or unable to start): `unsandboxed:*`, this time or in
      this conversation; no "Always".

    Disjoint targets, so a command whose text reads like a rule set (`git-push`) never stands for the
    commands that match it (`git push origin main`).

    `network`: the card also asks for the network (after outside content), and its title says so. A
    click on it stands for the network this time only; a grant that answers it later does not."""
    from server.services import permissions, task_service
    net = " It will use the network, this time." if network else ""
    if rules:
        # 0.1.62 F4a, S2a-2. S2a-1 (U11): an approved plain osascript or Shortcut runs outside the sandbox,
        # and the card says so; a Shortcut cannot be inspected, so its card says it runs as the user.
        where = ""
        if task_service.unwrapped_once(shell):
            where = (" It runs as you, outside the sandbox; Arslan cannot see what the Shortcut does."
                     if "shortcuts" in rules else " It runs outside the sandbox, this once.")
        return permissions.Request(kind="command", target="rules:" + "|".join(rules),
                                   title=f"Run `{shell[:80]}`?{where}{net}", detail=shell,
                                   conversation_ok=False, once_only=True, frame=frame)
    if ask_all:
        return permissions.Request(kind="command", target="text:" + shell, title=f"Run `{shell[:80]}`?{net}",
                                   detail=shell, frame=frame)
    # Marked on the card (a key the web and the phone ignore), so the island never approves a command
    # that would run with no sandbox around it: `rm notes.txt` there is a real delete.
    return permissions.Request(kind="command", target="unsandboxed:*",
                               title=f"Run `{shell[:80]}` outside the sandbox?{net}", detail=shell,
                               frame={**frame, "unsandboxed": True} if frame else None)


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
