"""The gate in front of `run_command` (LOOP1 c2), in the order it has always asked: what never runs, leaving the sandbox,
the command's own card, then the network after outside content. `check` answers with the refusal the model reads, or with
what it settled for the execute stage."""
from __future__ import annotations

from dataclasses import dataclass, field

from server.orchestrator.tool_gates import _declined, _unattended
from server.orchestrator.turn_state import ToolTurn


async def _asks_for_everything() -> bool:
    """The user chose 'ask for every command'. Unknown counts as yes (then nothing runs unasked)."""
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.shell_confirm_policy(db) == "ask_all"
    except Exception:  # noqa: BLE001 — fails closed: unreadable means ask for every command
        return True


def _nobody_to_ask(confirm_command) -> bool:
    """A run with no card callback and no card surface: a scheduled run (the heartbeat is one)."""
    from server.services import permissions
    return confirm_command is None and permissions.current_asker() is None


#: What the model is told when a run with nobody to ask names run_command (v0.1.63; DELETE-BY: v0.1.64, with
#: S2a-3 and PR4).
SCHEDULED_COMMAND_NOTE = ("Scheduled runs don't run commands. Save what you found with write_file (it writes in "
                          "Arslan's own folder), or tell the user what to run themselves.")


async def _scheduled_command_refused(args: dict, conversation_id: str | None) -> dict:
    """The refusal of a command in a run with nobody to ask, listed in the Inbox as the card would have read under
    "ask for every command" (U14 c): policy, deny, no "Always"."""
    from server.services import approvals, terminal_policy
    command = terminal_policy.as_shell(args.get("command"), args.get("argv"))
    return {"ok": False, "error": await _unattended("a scheduled run runs no commands",
                                                    approvals._command_request(command, [], None, ask_all=True),
                                                    conversation_id),
            "note": SCHEDULED_COMMAND_NOTE}


def _outside_request(command: str, title: str = ""):
    """S4a: what running `command` outside the sandbox asks: every command of the conversation may (`outside`
    / `*`), the card's "In this conversation" (command_confirm). `title`, where it is shown (SMART-8): its plain
    purpose; a standing-grant lookup reads only the target."""
    from server.services import permissions
    old = f"Run `{command[:80]}` outside the sandbox?"
    return permissions.Request(kind="outside", target="*", detail=command, title=title or old,
                               model_title=old if title else "")


async def _outside_grant(conversation_id: str | None, command: str):
    """S4a: this conversation's stored grant to run its commands outside the sandbox (`permissions.standing`,
    which finds nothing where nobody can be asked), or None. No ledger row yet: `note_standing` writes it."""
    from server.services import background_jobs, permissions
    return await permissions.standing(_outside_request(command), permissions.Context(
        conversation_id, job_id=background_jobs._inside_job.get()))


async def _network_after_outside_content(command: str, args: dict, *, sandbox_on: bool, run_outside: bool,
                                         unwrapped: bool, conversation_id: str | None) -> dict:
    """S2a-1 piece 2. After this turn read outside content (a page, a file, an MCP tool), a command
    runs offline under the kernel's rule — in the sandbox, and outside it under the minimal profile,
    which carries the same rule (card, piece 4; the internal review's case: a script refused inside for
    reading a secret, let out by its outside card, must not get the network with it). One that reaches the
    network (by its text, or the model's `network: true`) asks first: this time or this conversation
    inside the sandbox, this time only outside it, where the user's secrets are readable (a stored grant
    does not count there). The island never answers it. With nobody to ask: offline. An approved plain
    osascript (U11) runs with no wrapper and is not a network command; an approved bare Shortcut asks for
    the network, this time only, and does not run without it. Where seatbelt cannot start nothing is
    wrapped, so only the card holds.

    Returns {"offline": bool, "note": str} or {"refused": model text}."""
    from server.orchestrator import untrusted as _untrusted
    from server.services import background_jobs, command_sandbox, permissions, task_service, terminal_policy
    if not _untrusted.external_seen():
        return {}
    if unwrapped:
        # ⓪Plan's S-gate review: a bare osascript (one of four apps, no URL) is not a network command,
        # but a Shortcut can do anything, the network included, and a bare run has no offline rule. It
        # asks first, this time only; with nobody to ask, or on a no, it does not run.
        if not task_service.bare_shortcut(command):
            return {}
        from server.services import card_purpose
        why = str(args.get("why") or "").strip()[:300]
        # SMART-8: the title is the command's plain purpose (the iPhone's heading). Never the model's `why` (#689
        # review 3): the Mac's action card shows the title as the server's own words under it.
        request = permissions.Request(
            kind="network", target="network:*", title=card_purpose.phrase(
                command, "", sorted(terminal_policy.ask_rules(command)), lang=await card_purpose.language(),
                network=True),
            model_title=f"Let the Shortcut `{command[:80]}` use the network?",
            detail=command, why=why, conversation_ok=False, once_only=True)
        if permissions.current_asker() is None:
            return {"refused": await _unattended("", request, conversation_id)}
        decision = await permissions.decide(request, permissions.Context(
            conversation_id, job_id=background_jobs._inside_job.get()))
        return {} if decision.allowed else {
            "refused": decision.model_text or "the user did not allow this Shortcut to use the network"}
    wrapped = command_sandbox.available()
    inside = sandbox_on and not run_outside and wrapped
    if not (args.get("network") is True or _untrusted.reaches_network(command)):
        return {"offline": True} if wrapped else {}
    if wrapped and permissions.current_asker() is None:
        return {"offline": True, "note": "ran without network: this turn read outside content, and there was "
                                         "nobody to allow the network for it"}
    from server.services import card_purpose
    why = str(args.get("why") or "").strip()[:300]
    decision = await permissions.decide(permissions.Request(   # SMART-8: the plain purpose, never `why` (as above)
        kind="network", target="network:*", title=card_purpose.phrase(   # read with its rules (Astra 5)
            command, "", sorted(terminal_policy.ask_rules(command)), lang=await card_purpose.language(),
            network=True), detail=command,
        model_title=f"Let `{command[:80]}` use the network?", why=why, conversation_ok=inside, once_only=not inside),
        permissions.Context(conversation_id, job_id=background_jobs._inside_job.get()))
    if decision.allowed:
        return {}
    return {"refused": decision.model_text or "the user did not allow this command to use the network"}


def _network_card_due(command: str, args: dict) -> bool:
    """S2a-2: whether `_network_after_outside_content` would ask for the network, known before the
    command's own card, so that card asks for both (one card, not two). A click on it stands for the
    network this time; a grant or rule that answers it does not, and the network card still comes."""
    from server.orchestrator import untrusted as _untrusted
    from server.services import task_service
    if not _untrusted.external_seen():
        return False
    if task_service.unwrapped_once(command):
        return task_service.bare_shortcut(command)       # a bare osascript is not a network command
    return args.get("network") is True or _untrusted.reaches_network(command)


def _bare_once(command: str, *, by_user: bool) -> tuple[bool, bool]:
    """S2a-1 piece 4, decision U11: (run with no wrapper, kept wrapped) for an approved command. Only
    a command with an Apple Events or Shortcuts rule, approved by the user's click on its card (a
    once-only card: no grant or rule ever answers it), and one plain call runs bare, this once.
    Approved but not plain (a script that acts beyond its app): kept under the sandbox's profiles."""
    from server.services import task_service, terminal_policy
    if not (by_user and terminal_policy.ask_rules(command) & terminal_policy.BARE_RULES):
        return False, False
    bare = task_service.unwrapped_once(command)
    return bare, not bare


async def _sandbox_enabled() -> bool:
    """Settings → Advanced → "Run commands in a sandbox" (0.1.51 P3), default on."""
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.terminal_sandbox_enabled(db)
    except Exception:  # noqa: BLE001 — unreadable means the default: sandboxed
        return True


@dataclass(frozen=True, slots=True)
class CommandPlan:
    """What the command gate settled, for the execute stage. Any other tool runs with `NOT_A_COMMAND`."""
    command: str = ""
    run_outside: bool = False       # it leaves the sandbox
    by_grant: bool = False          # this conversation's stored grant lets it out: read again at execute
    sandbox_on: bool = False
    unwrapped: bool = False         # an approved Apple Events or Shortcuts call runs bare
    kept_wrapped: bool = False
    network: dict = field(default_factory=dict)     # {"offline", "note"} after outside content
    deletes_outside: bool = False
    confined: bool = False


NOT_A_COMMAND = CommandPlan()


async def check(args: dict, turn: ToolTurn) -> dict | CommandPlan:
    """The refusal to record, or the plan to run with.

    A command requires per-command user confirmation via the injected
    confirm_command(command, argv) -> bool callback. No callback → refuse (safety default).
    Since 0.1.51 it also runs inside the workspace sandbox; leaving it is a click
    (confirm_command(..., sandbox="outside")), never the model's say-so."""
    confirm_command, conversation_id = turn.confirm_command, turn.conversation_id
    run_outside = False          # 0.1.51 P3: this command leaves the sandbox (a click said so)
    outside_grant = None         # S4a: this conversation's stored grant to leave the sandbox, as first read
    by_grant = False             # S4a: that grant is what lets this command run outside (read again at execute)
    sandbox_on = False
    unwrapped = kept_wrapped = False   # S2a-1 piece 4 (U11): an approved AE/Shortcut call runs bare
    network: dict = {}                 # S2a-1 piece 2: {"offline", "note"} for a command after outside content
    deletes_outside = confined = False  # SMART-8: an allowed delete outside the working folder; the sandbox holds it

    def delete_kw(outside: bool) -> dict:
        """SMART-8: how allow deletes, for the card of a delete outside the working folder."""
        from server.services import delete_to_trash
        return {"delete": delete_to_trash.card_mode(command, outside=outside or not confined)} if deletes_outside else {}
    # 0.1.48: one shell string; a forbidden command is refused here, before any
    # card, so nobody is ever asked to approve wiping the disk.
    from server.services import command_sandbox, terminal_policy
    command = terminal_policy.as_shell(args.get("command"), args.get("argv"))
    argv = []
    verdict = terminal_policy.assess(command)
    if verdict.level == "forbid":
        result = {"ok": False, "error": f"Arslan never runs this: {verdict.reason}",
                  "note": "Tell the user what you wanted to do and let them run it themselves."}
        return result
    if terminal_policy.heredoc_in_substitution(command):
        # No card either: it would show text that reads as data, and some of that text would run.
        result = {"ok": False, "error": "A here-document inside $( ) can't run here: in bash 3.2 its text can end the "
                  "substitution early, and the rest of the text runs as commands. Nothing ran.",
                  "note": "Write the text to a file with write_file, then use the file: for a commit message, "
                          "git commit -F <file>; for a variable, NOTE=$(cat <file>)."}
        return result
    if terminal_policy.other_osa_language(command):
        # S2a-2 (K5's gate, T1): a JXA script cannot reach an app from here, inside the sandbox or out (its
        # Apple Events are blocked; only plain AppleScript runs bare, U11), so no card is shown for it.
        result = {"ok": False, "error": "JXA (osascript -l JavaScript) cannot control apps from run_command: "
                  "Apple Events are blocked in the sandbox and outside it, and only plain AppleScript runs "
                  "outside the sandbox.",
                  "note": "Write it as plain AppleScript (osascript -e or a heredoc) for Reminders, Calendar, "
                          "Notes or Contacts, without outside_sandbox; or use mac_applescript."}
        return result
    sandbox_on = await _sandbox_enabled()
    deletes_outside = "delete-outside" in terminal_policy.ask_rules(command)
    confined = sandbox_on and command_sandbox.available()   # where it runs unless something lets it out
    from server.services import task_service as _task_service
    # S2a-2: a plain osascript that U11 runs bare takes its own card, the one way it works; asking to run it
    # outside the sandbox would show a card that cannot help (its Apple Events stay blocked there).
    wants_out = (sandbox_on and args.get("outside_sandbox") is True
                 and not _task_service.unwrapped_once(command))
    # S4a: this conversation's stored grant to run its commands outside the sandbox (the outside card
    # answered "In this conversation"), found as decide finds one: in a chat turn and a background job
    # alike. With nobody to ask (a scheduled run) nothing stands, and the command starts inside the
    # sandbox. Its ledger row is written below, once the command is cleared to run.
    outside_grant = await _outside_grant(conversation_id, command)
    run_outside = sandbox_on and outside_grant is not None
    by_grant = run_outside            # the grant is what lets this command run outside the sandbox
    net_due = _network_card_due(command, args)
    net_kw = {"network": True} if net_due else {}
    net_clicked = False                # the command's own card, clicked, asked for the network too
    if wants_out and not run_outside:
        # Asked up front: always a card, even for a command that would just run,
        # and one card covers the command's own reason too.
        if confirm_command is None:
            from server.services import card_purpose, permissions
            result = {"ok": False, "error": await _unattended(
                          "running a command outside the sandbox needs the user's click, which is not "
                          "available here",
                          _outside_request(command, card_purpose.phrase(
                              command, str(args.get("why") or "").strip()[:300],
                              lang=await card_purpose.language(), outside=True)),
                          conversation_id),
                      "note": "Run it without outside_sandbox, or tell the user what you needed."}
            return result
        # The reason as the card will show it (protocol.propose_run_command): one of invisible characters is none.
        from server.orchestrator import untrusted as _untrusted
        why = _untrusted.clean_name(args.get("why"), 300)
        if not why:
            # Leaving the sandbox is a deliberate request (the calibration of 2026-11-07), and the card leads with why.
            # Arslan's own words, and nothing ran: not outside content, whatever the command looks like.
            result = {"ok": False, "external": False, "executed": False,
                      "error": "outside_sandbox needs a why: one short sentence on why this has to run "
                               "outside the sandbox. The user reads it on the card."}
            return result
        from server.services import approvals as _approvals
        _approvals.LAST_OUTCOME.set(None)          # S2a-1: an earlier card's click never counts here
        _approvals.LAST_ANSWERED_BY.set(None)
        if not await confirm_command(command, argv, sandbox="outside", why=why, **net_kw, **delete_kw(True)):
            result = {"ok": False, "error": _declined("user declined running this command outside the sandbox", "running this command outside the sandbox")}
            return result
        run_outside = True
        # ⓪Plan review, fix 2: the network is answered only by the user's own click on this card (as below for
        # the command's card), never by whatever else let the command out.
        from server.services import permissions
        decided = permissions.LAST_DECISION.get()
        net_clicked = net_due and decided is not None and decided.by == "user"
        # S2a-1: the plain outside card records whose click approved it (approvals.LAST_ANSWERED_BY);
        # only the asking window's own ("mac") unlocks a bare run. A conversation grant shows no card.
        unwrapped, kept_wrapped = _bare_once(
            command, by_user=_approvals.LAST_OUTCOME.get() == "approved"
            and _approvals.LAST_ANSWERED_BY.get() == "mac")
    elif (verdict.level == "run" and not await _asks_for_everything()
          and (outside_grant is not None or (sandbox_on and command_sandbox.available()))):
        # S2a-2 layer ③: no card, and decided here only. In the sandbox only when it can start (R4: with
        # seatbelt unavailable the command would run unwrapped). Outside it under this conversation's
        # stored grant to leave the sandbox, which is the user's yes (S4a) — with the sandbox switched
        # off or unable to start too: that card asks the same thing (⓪Plan, S4a Q3). A layer ② card and
        # "ask for every command" still ask, whatever the grant.
        by_grant = outside_grant is not None
    else:
        if confirm_command is None:
            # Layer ②, `unreadable`, "ask for every command", or layer ③ with no sandbox to run it in.
            # Listed as the card would have read (approvals._command_request), U14 c.
            from server.services import approvals as _approvals, card_purpose
            ask_all = await _asks_for_everything()
            result = {"ok": False, "error": await _unattended(
                "run_command requires user confirmation, which is not available in this context"
                if verdict.level == "ask" or ask_all else
                "this command would run outside the sandbox here (it is switched off or cannot start), "
                "which needs the user's OK, and nobody can be asked here",
                _approvals._command_request(command, sorted(terminal_policy.ask_rules(command)), None,
                                            ask_all=ask_all, lang=await card_purpose.language(),
                                            why=str(args.get("why") or "").strip()[:300]),
                conversation_id)}
            return result
        from server.services import permissions
        permissions.LAST_DECISION.set(None)        # S2a-1: only this call's own decision counts below
        # SMART-8: the model's reason reaches the ordinary card too (its purpose line, marked as Arslan's words).
        said = str(args.get("why") or "").strip()[:300]
        approved = await confirm_command(command, argv, **({"why": said} if said else {}), **net_kw,
                                         **delete_kw(run_outside))
        if not approved:
            result = {"ok": False, "error": _declined("user declined this command", "this command")}
            return result
        # S2a-1 (the user, via ⓪Plan): only an explicitly recorded click unlocks the bare run — decide's
        # record of this card, answered by the user. Nothing recorded (a yes from any other path) keeps
        # the command wrapped.
        decided = permissions.LAST_DECISION.get()
        unwrapped, kept_wrapped = _bare_once(
            command, by_user=confirm_command is not None and decided is not None and decided.by == "user")
        run_outside = run_outside or unwrapped
        by_grant = by_grant and not unwrapped     # a bare run is the user's click on its card, not the grant
        net_clicked = net_due and decided is not None and decided.by == "user"
    network = {} if net_clicked else await _network_after_outside_content(
        command, args, sandbox_on=sandbox_on, run_outside=run_outside, unwrapped=unwrapped,
        conversation_id=conversation_id)
    if network.get("refused"):
        result = {"ok": False, "error": network["refused"]}
        return result
    return CommandPlan(command=command, run_outside=run_outside, by_grant=by_grant, sandbox_on=sandbox_on,
                       unwrapped=unwrapped, kept_wrapped=kept_wrapped, network=network,
                       deletes_outside=deletes_outside, confined=confined)
