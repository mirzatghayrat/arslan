"""Confirmation cards for background work (0.1.42).

A foreground turn asks for confirmation by owning its WebSocket's receive loop
(`server/ws/arslan.py`). Background work cannot: it outlives the turn and may
run while no window is open. Here a card is broadcast to every attached tab,
recorded as pending, and answered by `call_id` from whichever socket receives
the reply. Unanswered cards are declined after the same 300 s as foreground
cards; a reconnecting tab gets the still-pending cards again.

The same registry carries the cards of a turn the iPhone started (mobile bridge):
those are shown on the phone and in every Mac window on the conversation, and the
first answer from either decides (`open_card` / `close_card`). Every shared card
ends with a `card_resolved` broadcast, so the copies nobody answered close.

Policy is deliberately STRICTER than the foreground: a background job never
inherits a connection's session grants, never offers "remember this command",
and asks for a workspace write once per job.
"""
from __future__ import annotations

import asyncio
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field

from server.services import desktop_status, run_registry
from server.ws import protocol

TIMEOUT_S = 300
#: How the last card this task waited on ended: "approved", "declined", or "expired" (nobody
#: answered in time). A tool result must not tell the model the user said no when nobody did.
LAST_OUTCOME: ContextVar[str | None] = ContextVar("approvals_last_outcome", default=None)
ANSWERS = {
    "confirm_workspace_write": True, "cancel_workspace_write": False,
    "confirm_schedule": True, "cancel_schedule": False,
    "confirm_run_command": True, "cancel_run_command": False,
    "confirm_action": True, "cancel_action": False,   # 0.1.45 browser / Mac actions
}


@dataclass
class Pending:
    call_id: str
    conversation_id: str
    frame: dict
    future: asyncio.Future = field(repr=False)


_pending: dict[str, Pending] = {}


def open_card(conversation_id: str, frame: dict) -> Pending:
    """Broadcast one card to every socket on the conversation and register it, so a
    reply from any of them resolves `pending.future` (see `answer`). The caller waits
    and must call `close_card` once it is decided or given up on."""
    pending = Pending(frame["call_id"], conversation_id, frame, asyncio.get_running_loop().create_future())
    _pending[pending.call_id] = pending
    run_registry.make_emit(conversation_id)(frame)
    return pending


def close_card(pending: Pending) -> dict:
    """Unregister a card and tell every socket how it ended (`card_resolved`), so the
    copies nobody answered close. Returns the decision: approved, remember, by."""
    _pending.pop(pending.call_id, None)
    if pending.future.done() and not pending.future.cancelled():
        decision = pending.future.result()
        outcome = "approved" if decision["approved"] else "declined"
    else:
        decision = {"approved": False, "remember": False, "by": None}
        outcome = "expired"
    run_registry.make_emit(pending.conversation_id)(
        protocol.card_resolved(pending.call_id, outcome, decision["by"]))
    return decision


async def ask(conversation_id: str, frame: dict) -> bool:
    """Broadcast one card and wait for its answer. False on timeout or refusal."""
    # Marked so the card can say it is a background job asking, and hide the
    # "remember" option this path never honours.
    LAST_OUTCOME.set(None)
    pending = open_card(conversation_id, frame | {"background": True})
    try:
        with desktop_status.awaiting_approval(conversation_id):
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
    """
    call_id = data.get("call_id") if isinstance(data, dict) else None
    kind = data.get("type") if isinstance(data, dict) else None
    pending = _pending.get(call_id) if isinstance(call_id, str) else None
    if pending is None or kind not in ANSWERS or not _same_kind(kind, pending.frame["type"]):
        return False
    if not pending.future.done():
        pending.future.set_result({"approved": ANSWERS[kind], "remember": bool(data.get("remember")),
                                   # The Bridge marks what the phone sends; anything else is a Mac window.
                                   "by": "phone" if data.get("source") == "phone" else "mac"})
    return True


def _same_kind(reply: str, card: str) -> bool:
    return reply.split("_", 1)[1] == card.split("_", 1)[1]


def pending_cards(conversation_id: str) -> list[dict]:
    return [p.frame for p in _pending.values() if p.conversation_id == conversation_id]


class JobConfirmations:
    """The three confirmation callbacks the tool loop expects, for one job."""

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self._write_granted = False
        self._unanswered = False

    async def _card(self, frame: dict) -> bool:
        """One card. Once one went unanswered the person is away: no further card opens in this
        job (each would wait five more minutes for nobody, and a model told "expired" asked again
        within two seconds — seen on the device 2026-10-05); the rest read as expired at once."""
        if self._unanswered:
            LAST_OUTCOME.set("expired")
            return False
        approved = await ask(self.conversation_id, frame)
        if LAST_OUTCOME.get() == "expired":
            self._unanswered = True
        return approved

    async def workspace_write(self, action: str, path: str) -> bool:
        from server.db import session as db_session
        from server.services import settings_service
        if self._write_granted:
            return True
        async with db_session.AsyncSessionLocal() as db:
            root = await settings_service.workspace_dir(db)
        if root is None:
            return False
        granted = await self._card(protocol.propose_workspace_write(
            uuid.uuid4().hex, str(root), action, path))
        self._write_granted = granted
        return granted

    async def schedule(self, name: str, when: str) -> bool:
        return await self._card(protocol.propose_schedule(uuid.uuid4().hex, name, when))

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
            # "rest of the conversation" (jobs never add standing answers), and a job never
            # uses one the chat window was given: that grant is a session grant.
            return await self._ask_with_shadow(protocol.propose_run_command(
                uuid.uuid4().hex, command, argv, reason=verdict.reason if verdict.level == "ask" else "",
                sandbox=sandbox, why=why), command, verdict, sandboxed=False)
        policy, standing = "", False
        if not remote_host:
            async with db_session.AsyncSessionLocal() as db:
                policy = await settings_service.shell_confirm_policy(db)
                standing = terminal_policy.standing_allows(terminal_policy.as_shell(command, argv),
                                                           await terminal_policy.always_allowed(db))
        # A job never ADDS a standing answer (no "remember" here), but it honours
        # the ones the user gave in a conversation.
        if may_skip_card(remote_host, in_session_allow=False, policy=policy, risk=risk,
                         always_allowed=standing):
            return True
        frame = protocol.propose_run_command(
            uuid.uuid4().hex, command, argv, reason=verdict.reason or f"risk: {risk}",
            remote_host=remote_host, fingerprints=list(fingerprints or []))
        if remote_host:
            return await self._card(frame)
        return await self._ask_with_shadow(frame, command, verdict)

    async def _ask_with_shadow(self, frame: dict, command: str, verdict, *, sandboxed: bool | None = None) -> bool:
        """0.1.52 S2: the card as before, plus a shadow judgment recorded with the real answer."""
        from server.services import judgment
        judgment.shadow("tool.approval", judgment.approval_state(command, rule=verdict.rule, reason=verdict.reason,
                                                                 sandboxed=sandboxed),
                        ref=frame["call_id"], conversation_id=self.conversation_id)
        approved = await self._card(frame)
        judgment.record_outcome_later(frame["call_id"], "approved" if approved else "declined", point="tool.approval")
        return approved


def _reset_for_tests() -> None:
    for pending in _pending.values():
        if not pending.future.done():
            pending.future.cancel()
    _pending.clear()
