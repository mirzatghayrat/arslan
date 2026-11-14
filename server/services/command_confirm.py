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
import dataclasses
import uuid

from server.ws import protocol


def remote_target(host: str) -> str:
    """S4a (⓪Plan Q7): one machine's ledger rows share one target, whichever path wrote them."""
    return f"remote:{host}"


#: SMART-8 (#688 review 5): why terminal_policy could not read a command, by the reason it gives, so the card can say
#: it plainly; a reason not listed here reads as the generic "can't fully read". A test pins all four.
UNREADABLE = {"it runs code it downloads, decodes or builds": "fetched-code",
              "its script reaches out, starts programs or drives apps": "script-reach",
              "its quoting does not close, so what runs cannot be read": "quoting",
              "too complex to read before running": "complex"}


class Confirmations:
    def __init__(self, conversation_id: str | None, *, job_id: str | None = None, surface: str = "chat",
                 asker=None):
        self.conversation_id = conversation_id
        self.job_id = job_id
        self.surface = surface
        self.asker = asker

    def _context(self):
        from server.services import permissions
        return permissions.Context(conversation_id=self.conversation_id, job_id=self.job_id, surface=self.surface)

    def _surface(self):
        """Bind this ladder's card surface for one decision; the window's is bound by its turn."""
        from server.services import permissions
        return permissions.asking_with(self.asker) if self.asker is not None else contextlib.nullcontext()

    async def workspace_write(self, action: str, path: str) -> bool:
        from server.db import session as db_session
        from server.services import approvals, permissions, settings_service
        async with db_session.AsyncSessionLocal() as db:
            root = await settings_service.workspace_dir_for_run(db)     # SUB5c: a sub-session's card names its folder
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
                      network: bool = False, host: str | None = None, delete: str = "", outside: bool = False,
                      run_later=()) -> bool:
        """Called, a card is shown: which commands need none (layer ③ in the sandbox) is the tool loop's to
        decide, once (S2a-2). `sandbox` (0.1.51 P3): "outside" — the model asks to run this command
        outside the sandbox. `network` (S2a-2): the card also asks for the network, this time. `remote_host` is the
        machine as the card names it; `host`, its address (S4a: the ledger's `remote:<host>`). `delete` (SMART-8):
        for a delete outside the working folder, how allow deletes (`delete_to_trash.card_mode`); the card says it.
        `run_later` (HR-3 part 1): what it writes that runs later, where the kernel's hold doesn't stand (the gate's
        click-lift rule): the outside card names it, and the command's own card is this time only
        (`approvals._command_request`)."""
        from server.db import session as db_session
        from server.services import approvals, permissions, settings_service, terminal_policy
        from server.ws.arslan import effective_risk
        from server.services import card_purpose
        outside = outside or sandbox == "outside"   # S2a-3 step 5: it runs outside the sandbox, so read it that way
        risk = effective_risk(remote_host, command, argv, outside=outside)
        shell = terminal_policy.as_shell(command, argv)
        # S2a-3 step 4b: read from the folder the gate read (another machine's folder is not known here)
        from server.orchestrator.command_gate import run_folder
        cwd = None if remote_host else await run_folder()
        verdict = terminal_policy.assess(shell, cwd=cwd, outside=outside)
        # SMART-8 (#688 review 1, 3, 5): every rule it matched goes on every command card, with why it could not be
        # read when that is one of them; the card's risk row names each and takes the worst.
        # SMART-8 (#689): every card's title is its plain purpose in the user's language (the iPhone's heading).
        lang = await card_purpose.language()
        rules = sorted(terminal_policy.ask_rules(shell, cwd=cwd, outside=outside))
        unreadable = UNREADABLE.get(verdict.reason, "") if verdict.rule == terminal_policy.UNREADABLE else ""
        pushed = await _pushed_ci(shell, cwd) if "git-push" in rules and not remote_host else []     # HR-2b
        net = " It will use the network, this time." if network else ""      # the model's own text keeps the command
        from server.services import delete_to_trash
        deletes = delete_to_trash.card_note(delete)       # SMART-8: how allow deletes, in the model's English text
        if deletes:
            net = f" {deletes}{net}"
        if sandbox == "outside":
            # S4a: this time, or every command of this conversation — a background job's too — for as long as
            # the conversation lasts (a stored grant, `outside` / `*`). No "Always". Only a Mac window gives
            # more than this time (the Inbox, the phone and the island: this time); the island never answers
            # it at all. Always a card: the tool loop reads the stored grant itself, and writes its row when
            # the command runs (`permissions._ALWAYS_ASKS`).
            frame = {**protocol.propose_run_command(
                uuid.uuid4().hex, command, argv,
                reason=verdict.reason if verdict.level == "ask" else "",
                sandbox=sandbox, why=why, network=network, rules=rules, unreadable=unreadable),
                **_delete_keys(delete, shell)}
            _with_ci(frame, pushed)
            request = permissions.Request(
                kind="outside", target="*", title=card_purpose.phrase(
                    shell, why, rules, lang=lang, outside=True, network=network, delete_mode=delete,
                    reading=card_purpose.frame_reading(frame, shell),     # the frame's reading, not a second one
                    run_later=run_later),
                model_title=f"Run `{shell[:80]}` outside the sandbox?{net}", detail=shell,
                why=why, frame=frame)
        elif remote_host:
            # A remote command takes none of the shortcuts: the local risk grade describes a binary on THIS
            # machine, and `git` over there is not the same program (P3b 裁决③). `remote` is answered this
            # time only (`permissions._ONCE_ONLY`): nothing is remembered.
            frame = protocol.propose_run_command(
                uuid.uuid4().hex, command, argv, reason=verdict.reason or f"risk: {risk}",
                remote_host=remote_host, fingerprints=list(fingerprints or []), why=why, rules=rules,
                unreadable=unreadable)
            request = permissions.Request(
                kind="remote", target=remote_target(host or remote_host),
                title=card_purpose.phrase(shell, why, rules, lang=lang, host=remote_host,
                                          reading=card_purpose.frame_reading(frame, shell)),
                model_title=f"Run `{shell[:80]}` on {remote_host}?",
                detail=shell,
                frame=frame)
        else:
            request = None
        if request is not None:
            with self._surface():
                return (await permissions.decide(request, self._context())).allowed
        async with db_session.AsyncSessionLocal() as db:
            ask_all = await settings_service.shell_confirm_policy(db) == "ask_all"
        frame = protocol.propose_run_command(
            uuid.uuid4().hex, command, argv, reason=verdict.reason or f"risk: {risk}",
            rule=verdict.rule or None, network=network, why=why,    # SMART-8: the card's purpose, as Arslan's words
            rules=rules, unreadable=unreadable, outside=outside)    # LOOP1 d2b: read as the gate read it
        frame.update(_delete_keys(delete, shell))
        _with_ci(frame, pushed)
        # S2a-3 step 5 (#798 review 1): a card the gate says runs outside (`outside`) is marked so in either policy,
        # its rules card too; otherwise as before, "ask for every command" asks where it would run.
        unsandboxed = outside or (ask_all and not rules and await approvals.runs_unsandboxed(self.conversation_id))
        request = approvals._command_request(shell, rules, frame, ask_all=ask_all, network=network,
                                             unsandboxed=unsandboxed, lang=lang, why=why,
                                             delete_mode=delete, run_later=run_later)
        if deletes:     # the model's English text; the title and the card word `delete_mode` themselves
            request = dataclasses.replace(request, model_title=f"{request.title_for_model} {deletes}")
        # S2a-3 step 4b: the card keeps this folder while it waits (`approvals.open_card`), so the island reads it from
        # the same folder, server-side (no frame key)
        token = approvals.CARD_FOLDER.set(cwd)
        try:
            with self._surface():
                decision = await permissions.decide(request, self._context())
        finally:
            approvals.CARD_FOLDER.reset(token)
        return decision.allowed


#: HR-2b: what the push card says when the outgoing files couldn't be read (the card still shows: fails closed).
PUSH_UNLISTED = "Arslan couldn't list the files this push sends"
#: HR-3: what it says when where the push goes couldn't be read (the card still shows).
PUSH_UNKNOWN = "Push destination unknown"


async def _pushed_ci(shell: str, cwd) -> list[str]:
    """HR-2b: the push card's lines for the CI files its outgoing commits change (`git_config_guard.outgoing_ci`, off
    the event loop): one per file, PUSH_UNLISTED when they couldn't be read (no folder, a git failure or timeout, an
    error), [] when there are none. A CI job runs on the CI service after a push, so the push is where it is named.
    HR-3: led by where it pushes (`git_config_guard.push_destination`), a line per url, else PUSH_UNKNOWN."""
    import asyncio
    from pathlib import Path
    from server.services import git_config_guard

    async def read(reader):
        try:
            return None if cwd is None else await asyncio.to_thread(reader, Path(cwd), shell)
        except Exception:  # noqa: BLE001 — fails closed: the card says it couldn't read it
            return None
    urls, found = await read(git_config_guard.push_destination), await read(git_config_guard.outgoing_ci)
    return ([f"Push destination: {url}" for url in urls] if urls else [PUSH_UNKNOWN]) + (
        [PUSH_UNLISTED] if found is None else [f"CI file: {name}" for name in found])


def _with_ci(frame: dict, lines: list[str]) -> None:
    """HR-2b, no new frame key: the lines lead the Mac card's touches row (`summary.touches`, which the Bridge doesn't
    read) and end the `reason` the phone shows (the first 10 there)."""
    if lines:
        frame["summary"] = {**frame["summary"], "touches": [*lines, *frame["summary"].get("touches", [])]}
        shown = lines[:10] + ([f"and {len(lines) - 10} more"] if len(lines) > 10 else [])
        frame["reason"] = "; ".join([*([frame["reason"]] if frame.get("reason") else []), *shown])


def _delete_keys(mode: str, shell: str) -> dict:
    """SMART-8: the delete card's mode and targets for the Mac card (⑤CAP's shared component), on the Mac's WS
    frame only. The Bridge's FrameMapper reads named keys (title, perm_kind, expires_at…), so neither reaches the
    phone, whose heading is the card's plain purpose (`title`, ⑤CAP). `delete_targets` are as written; [] when
    the delete can't be read, and the card then reads rm's plain arguments itself."""
    if not mode:
        return {}
    from server.services import delete_to_trash
    found = delete_to_trash.plan(shell)
    return {"delete_mode": mode, "delete_targets": list(found.targets) if found else []}
