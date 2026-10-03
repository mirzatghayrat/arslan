"""Confirmation cards for background work (0.1.42).

A foreground turn asks for confirmation by owning its WebSocket's receive loop
(`server/ws/arslan.py`). Background work cannot: it outlives the turn and may
run while no window is open. Here a card is broadcast to every attached tab,
recorded as pending, and answered by `call_id` from whichever socket receives
the reply. Unanswered cards are declined after the same 300 s as foreground
cards; a reconnecting tab gets the still-pending cards again.

Policy is deliberately STRICTER than the foreground: a background job never
inherits a connection's session grants, never offers "remember this command",
and asks for a workspace write once per job.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from server.services import desktop_status, run_registry
from server.ws import protocol

TIMEOUT_S = 300
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


async def ask(conversation_id: str, frame: dict) -> bool:
    """Broadcast one card and wait for its answer. False on timeout or refusal."""
    loop = asyncio.get_running_loop()
    # Marked so the card can say it is a background job asking, and hide the
    # "remember" option this path never honours.
    frame = frame | {"background": True}
    pending = Pending(frame["call_id"], conversation_id, frame, loop.create_future())
    _pending[pending.call_id] = pending
    run_registry.make_emit(conversation_id)(frame)
    try:
        with desktop_status.awaiting_approval(conversation_id):
            return bool(await asyncio.wait_for(asyncio.shield(pending.future), timeout=TIMEOUT_S))
    except TimeoutError:
        return False
    finally:
        _pending.pop(pending.call_id, None)


def answer(data: dict) -> bool:
    """Route one reply frame to a pending background card. True if it was one.

    Only a reply of the card's own kind resolves it: a `confirm_schedule` can
    never approve a pending command card.
    """
    call_id = data.get("call_id") if isinstance(data, dict) else None
    kind = data.get("type") if isinstance(data, dict) else None
    pending = _pending.get(call_id) if isinstance(call_id, str) else None
    if pending is None or kind not in ANSWERS or not _same_kind(kind, pending.frame["type"]):
        return False
    if not pending.future.done():
        pending.future.set_result(ANSWERS[kind])
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

    async def workspace_write(self, action: str, path: str) -> bool:
        from server.db import session as db_session
        from server.services import settings_service
        if self._write_granted:
            return True
        async with db_session.AsyncSessionLocal() as db:
            root = await settings_service.workspace_dir(db)
        if root is None:
            return False
        granted = await ask(self.conversation_id, protocol.propose_workspace_write(
            uuid.uuid4().hex, str(root), action, path))
        self._write_granted = granted
        return granted

    async def schedule(self, name: str, when: str) -> bool:
        return await ask(self.conversation_id, protocol.propose_schedule(uuid.uuid4().hex, name, when))

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
            # "rest of the conversation" (jobs never add standing answers).
            from server.services import command_sandbox
            if command_sandbox.granted(self.conversation_id):
                return True
            return await self._ask_with_shadow(protocol.propose_run_command(
                uuid.uuid4().hex, command, argv, reason=verdict.reason if verdict.level == "ask" else "",
                sandbox=sandbox, why=why), command, verdict, sandboxed=False)
        policy, standing = "", False
        if not remote_host:
            async with db_session.AsyncSessionLocal() as db:
                policy = await settings_service.shell_confirm_policy(db)
                standing = verdict.rule in await terminal_policy.always_allowed(db)
        # A job never ADDS a standing answer (no "remember" here), but it honours
        # the ones the user gave in a conversation.
        if may_skip_card(remote_host, in_session_allow=False, policy=policy, risk=risk,
                         always_allowed=standing):
            return True
        frame = protocol.propose_run_command(
            uuid.uuid4().hex, command, argv, reason=verdict.reason or f"risk: {risk}",
            remote_host=remote_host, fingerprints=list(fingerprints or []))
        if remote_host:
            return await ask(self.conversation_id, frame)
        return await self._ask_with_shadow(frame, command, verdict)

    async def _ask_with_shadow(self, frame: dict, command: str, verdict, *, sandboxed: bool | None = None) -> bool:
        """0.1.52 S2: the card as before, plus a shadow judgment recorded with the real answer."""
        from server.services import judgment
        judgment.shadow("tool.approval", judgment.approval_state(command, rule=verdict.rule, reason=verdict.reason,
                                                                 sandboxed=sandboxed),
                        ref=frame["call_id"], conversation_id=self.conversation_id)
        approved = await ask(self.conversation_id, frame)
        judgment.record_outcome_later(frame["call_id"], "approved" if approved else "declined", point="tool.approval")
        return approved


def _reset_for_tests() -> None:
    for pending in _pending.values():
        if not pending.future.done():
            pending.future.cancel()
    _pending.clear()
