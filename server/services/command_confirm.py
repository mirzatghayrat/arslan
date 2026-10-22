"""One confirmation ladder for the tool loop's three callbacks (S4a): a command, a write in the
workspace, a schedule. The chat window (`server/ws/arslan.py`) and a background job
(`approvals.JobConfirmations`) are thin shells over it; what differs between them is only where a card
is shown and what the ledger row carries:

- the card surface: a job binds its `BroadcastAsker` (`asker`); the window leaves the one its turn
  bound (`permissions.asking_with(_window_asker)`, `permissions.current_asker()`);
- the context: a job's decisions carry its job id (§A8).

Every rule card, the workspace write and the schedule are decided by `permissions.decide`.
"""
from __future__ import annotations

import contextlib
import uuid

from server.ws import protocol


class Confirmations:
    def __init__(self, conversation_id: str | None, *, job_id: str | None = None, surface: str = "chat",
                 asker=None, session_grants: bool = False):
        self.conversation_id = conversation_id
        self.job_id = job_id
        self.surface = surface
        self.asker = asker
        # The window's in-memory "rest of this conversation" sandbox grant is its own to use and to
        # give; a job's card offers none and never uses one.
        self.session_grants = session_grants

    def _context(self):
        from server.services import permissions
        return permissions.Context(conversation_id=self.conversation_id, job_id=self.job_id, surface=self.surface)

    def _surface(self):
        """Bind this ladder's card surface for one decision; the window's is bound by its turn."""
        from server.services import permissions
        return permissions.asking_with(self.asker) if self.asker is not None else contextlib.nullcontext()

    async def _card(self, frame: dict) -> dict:
        """A plain card (leaving the sandbox, another machine): one answer, on this ladder's surface."""
        from server.services import permissions
        asker = self.asker if self.asker is not None else permissions.current_asker()
        return await asker(frame)

    async def workspace_write(self, action: str, path: str) -> bool:
        from server.db import session as db_session
        from server.services import approvals, permissions, settings_service
        async with db_session.AsyncSessionLocal() as db:
            root = await settings_service.workspace_dir(db)
        if root is None:
            permissions.LAST_DECISION.set(None)    # no card: the refusal is not an earlier answer
            approvals.LAST_OUTCOME.set(None)
            return False                           # nothing to grant access to
        # Decided with that session closed: decide opens its own, and a card may wait 30 minutes.
        with self._surface():
            decision = await permissions.decide(permissions.Request(
                kind="workspace_write", target=str(root), title=f"Let Arslan write in {root.name}?",
                detail=path, frame=protocol.propose_workspace_write(uuid.uuid4().hex, str(root), action, path)),
                self._context())
        return decision.allowed

    async def schedule(self, name: str, when: str, prompt: str = "") -> bool:
        """S1 (U14 d): the card shows the task's prompt."""
        from server.services import permissions
        with self._surface():
            decision = await permissions.decide(permissions.Request(
                kind="schedule", target="*", title=f"Schedule “{name}”?", detail=when,
                frame=protocol.propose_schedule(uuid.uuid4().hex, name, when, prompt)),
                self._context())
        return decision.allowed

    async def command(self, command: str, argv: list, *, remote_host: str | None = None,
                      fingerprints: list | None = None, sandbox: str | None = None, why: str = "",
                      network: bool = False) -> bool:
        """Called, a card is shown: which commands need none (layer ③ in the sandbox) is the tool loop's to
        decide, once (S2a-2). `sandbox` (0.1.51 P3): "outside" — the model asks to run this command
        outside the sandbox; "retry" — the sandbox stopped it and it would run again outside, from the
        start. `network` (S2a-2): the card also asks for the network, this time."""
        from server.db import session as db_session
        from server.services import approvals, command_sandbox, permissions, settings_service, terminal_policy
        from server.ws.arslan import effective_risk
        risk = effective_risk(remote_host, command, argv)
        verdict = terminal_policy.assess(terminal_policy.as_shell(command, argv))
        if sandbox in ("outside", "retry"):
            if self.session_grants and command_sandbox.granted(self.conversation_id):
                return True
            answer = await self._card(protocol.propose_run_command(
                uuid.uuid4().hex, command, argv, reason=verdict.reason if verdict.level == "ask" else "",
                sandbox=sandbox, why=why, network=network))
            if self.session_grants and answer["approved"] and answer.get("remember"):
                command_sandbox.grant(self.conversation_id)    # this conversation only, never saved
            return bool(answer["approved"])
        if remote_host:
            # A remote command takes none of the shortcuts: the local risk grade describes a binary on THIS
            # machine, and `git` over there is not the same program (P3b 裁决③). Nothing is remembered.
            answer = await self._card(protocol.propose_run_command(
                uuid.uuid4().hex, command, argv, reason=verdict.reason or f"risk: {risk}",
                remote_host=remote_host, fingerprints=list(fingerprints or [])))
            return bool(answer.get("approved"))
        async with db_session.AsyncSessionLocal() as db:
            ask_all = await settings_service.shell_confirm_policy(db) == "ask_all"
        shell = terminal_policy.as_shell(command, argv)
        rules = sorted(terminal_policy.ask_rules(shell))
        frame = protocol.propose_run_command(
            uuid.uuid4().hex, command, argv, reason=verdict.reason or f"risk: {risk}",
            rule=verdict.rule or None, network=network)
        unsandboxed = ask_all and await approvals.runs_unsandboxed(
            self.conversation_id if self.session_grants else None)
        with self._surface():
            decision = await permissions.decide(
                approvals._command_request(shell, rules, frame, ask_all=ask_all, network=network,
                                           unsandboxed=unsandboxed),
                self._context())
        return decision.allowed
