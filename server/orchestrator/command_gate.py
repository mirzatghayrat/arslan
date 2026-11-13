"""The gate in front of `run_command` (LOOP1 c2), in the order it has always asked: what never runs, leaving the sandbox,
the command's own card, then the network after outside content. Since S2a-3 step 3 a command whose only rule is
`unreadable` runs offline in the sandbox with no card where it can (`_runs_offline_unread`). `check` answers with the
refusal the model reads, or with what it settled for the execute stage."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

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
                                         unwrapped: bool, conversation_id: str | None, cwd=None) -> dict:
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

    NET-a (the switch `sandbox_net_judgement`, on by default): in the sandbox a command stays online, through the
    proxy that judges each site it reaches (net_policy), with no card here; outside it, and a bare Shortcut, as above.

    Returns {"offline": bool, "note": str} or {"refused": model text}."""
    from server.orchestrator import untrusted as _untrusted
    from server.services import (background_jobs, command_sandbox, net_policy, permissions, task_service,
                                 terminal_policy)
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
                command, "", sorted(terminal_policy.ask_rules(command, cwd=cwd)), lang=await card_purpose.language(),
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
    if inside and await net_policy.judging():
        return {}
    # DELETE-BY: v0.1.65 (NET-a's switch, once it has shipped on): S2a-1's whole-network rule in the sandbox below, the
    # offline run and its `network:*` card for this conversation; outside the sandbox it stays (this time only).
    if not (args.get("network") is True or _untrusted.reaches_network(command)):
        return {"offline": True} if wrapped else {}
    if wrapped and permissions.current_asker() is None:
        return {"offline": True, "note": "ran without network: this turn read outside content, and there was "
                                         "nobody to allow the network for it"}
    from server.services import card_purpose
    why = str(args.get("why") or "").strip()[:300]
    decision = await permissions.decide(permissions.Request(   # SMART-8: the plain purpose, never `why` (as above)
        kind="network", target="network:*", title=card_purpose.phrase(   # read with its rules (Astra 5)
            command, "", sorted(terminal_policy.ask_rules(command, cwd=cwd, outside=not inside)),
            lang=await card_purpose.language(),
            network=True), detail=command,
        model_title=f"Let `{command[:80]}` use the network?", why=why, conversation_ok=inside, once_only=not inside),
        permissions.Context(conversation_id, job_id=background_jobs._inside_job.get()))
    if decision.allowed:
        return {}
    return {"refused": decision.model_text or "the user did not allow this command to use the network"}


def _network_card_due(command: str, args: dict, *, judged: bool = False) -> bool:
    """S2a-2: whether `_network_after_outside_content` would ask for the network, known before the
    command's own card, so that card asks for both (one card, not two). A click on it stands for the
    network this time; a grant or rule that answers it does not, and the network card still comes.
    NET-a: `judged`, the command runs in the sandbox with the switch on, where nothing asks for the network."""
    from server.orchestrator import untrusted as _untrusted
    from server.services import task_service
    if not _untrusted.external_seen():
        return False
    if task_service.unwrapped_once(command):
        return task_service.bare_shortcut(command)       # a bare osascript is not a network command
    return not judged and (args.get("network") is True or _untrusted.reaches_network(command))


def _bare_once(command: str, *, by_user: bool, cwd=None) -> tuple[bool, bool]:
    """S2a-1 piece 4, decision U11: (run with no wrapper, kept wrapped) for an approved command. Only
    a command with an Apple Events or Shortcuts rule, approved by the user's click on its card (a
    once-only card: no grant or rule ever answers it), and one plain call runs bare, this once.
    Approved but not plain (a script that acts beyond its app): kept under the sandbox's profiles."""
    from server.services import task_service, terminal_policy
    if not (by_user and terminal_policy.ask_rules(command, cwd=cwd) & terminal_policy.BARE_RULES):
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


async def _work_folder_holds_home() -> bool:
    """S2a-3 step 3 (⓪Plan's ruling 7): whether the working folder is the home folder or holds it, read on every
    call. There the sandbox may write all of home, so an unread command asks instead of running with no card. Compared
    case-insensitively (the default macOS disk ignores case). No folder, or one that cannot be read, counts as yes."""
    from pathlib import Path
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            folder = await settings_service.workspace_dir_for_run(db)     # SUB5c: where this run's commands write
        if folder is None:
            return True
        home = [part.casefold() for part in Path.home().resolve().parts]
        work = [part.casefold() for part in Path(folder).resolve().parts]
        return home[:len(work)] == work
    except Exception:  # noqa: BLE001 — fails closed: unknown means it may hold home, so the command asks
        return True


async def run_folder():
    """S2a-3 step 4b: the folder this run's command starts in, read as the executor reads it (`workspace_dir_for_run`),
    so the policy follows a change of folder from there. The gate, its card and the island read this one folder. None
    when it can't be read: the policy then reads the text alone, as before."""
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.workspace_dir_for_run(db)
    except Exception:  # noqa: BLE001 — unknown reads as before step 4b (no folder)
        return None


#: S2a-3 step 3: what the model reads when an unread command ran offline in the sandbox with no card.
OFFLINE_UNREAD_NOTE = ("ran offline in the sandbox: Arslan can't fully read this command ({why}), so it ran with no "
                       "network and no card. If it needs the network, call run_command again with network: true; "
                       "the user is asked first.")


async def _runs_offline_unread(command: str, args: dict, verdict, *, confined: bool, outside_grant, cwd=None) -> bool:
    """S2a-3 step 3 (design point 1): a command whose only rule is `unreadable` runs in the sandbox, offline, with no
    card, when all of these hold: the sandbox is on and can start; no "ask for every command"; the working folder is
    not home and does not hold it; the call has no `network: true` (that call gets today's card); and the
    conversation has no grant to leave the sandbox (⓪Plan's ruling 2: then it gets a card). A background job with no
    card callback takes this branch too (ruling 5)."""
    from server.services import terminal_policy
    return (verdict.level == "ask" and terminal_policy.ask_rules(command, cwd=cwd) == {terminal_policy.UNREADABLE}
            and confined and outside_grant is None and args.get("network") is not True
            and not await _asks_for_everything() and not await _work_folder_holds_home())


def _git_config_request(why: str = ""):
    """HR-1b: one card, for this conversation only, stored under `*` as `outside` is (the lift is the working
    folder's, whichever it is when the command runs)."""
    from server.services import permissions
    return permissions.Request(
        kind="git_config", target="*", title="Let git update this repository's settings?",
        detail=("For the rest of this conversation, in the working folder: upstreams, remotes, user.name and "
                "user.email. Settings that name programs (hooks, editors, filters, aliases) are put back after each "
                "command."),
        model_title="Let git update this repository's settings (git_config) in this conversation?", why=why)


async def _git_config(args: dict, conversation_id: str | None) -> bool | dict:
    """HR-1b: whether this command runs under the git_config grant (stored: every sandboxed command, no card; a failed
    lookup is none), or the refusal the model reads. Otherwise only `git_config: true` with a why asks: one card."""
    from server.orchestrator import untrusted as _untrusted
    from server.services import background_jobs, git_config_guard, permissions
    if (conversation_id or "") in git_config_guard.ENDED:      # review delta 2: a put-back failed here
        await end_git_config(conversation_id)
        return False if args.get("git_config") is not True else {
            "ok": False, "external": False, "executed": False, "error": "git_config ended in this conversation (a "
            "put-back failed after an earlier command). Tell the user which settings to change instead."}
    context = permissions.Context(conversation_id, job_id=background_jobs._inside_job.get())
    request = _git_config_request()
    try:
        found = await permissions.standing(request, context)
    except Exception:  # noqa: BLE001 — fails closed: no grant read means the configs stay held
        found = None
    if found is not None:
        await permissions.note_standing(request, context, found)
        return True
    if args.get("git_config") is not True:
        return False
    why = _untrusted.clean_name(args.get("why"), 300)
    if not why:
        return {"ok": False, "external": False, "executed": False,
                "error": "git_config needs a why: one short sentence on why git has to update this repository's "
                         "settings. The user reads it on the card."}
    decision = await permissions.decide(replace(request, why=why), context)
    if decision.allowed:
        return True
    return {"ok": False, "error": decision.model_text or "the user did not let git update this repository's settings"}


async def end_git_config(conversation_id: str | None) -> None:
    """HR-1b review delta 2: a put-back failed. No lift again here (ENDED) nor after a restart (the grant deleted)."""
    import logging
    from server.db import session as db_session
    from server.services import git_config_guard, permission_store
    git_config_guard.ENDED.add(conversation_id or "")
    try:
        async with db_session.AsyncSessionLocal() as db:
            grant = await permission_store.find_grant(db, conversation_id, None, "git_config", "*")
            if grant is not None and await permission_store.delete_conversation_grant(db, grant.id):
                await db.commit()
    except Exception:  # noqa: BLE001 — ENDED holds the configs in this process either way
        logging.getLogger(__name__).warning("ending the git_config grant failed", exc_info=True)


async def _git_include(command: str, conversation_id: str | None) -> dict | None:
    """HR-1c: a git command in a repository whose effective settings changed through an included file outside the
    working folder during an earlier command (git_config_guard.mark) asks first: one card, this time only (kind
    `git_include`, never automatic; the island never answers it; with nobody to ask it is refused and listed in the
    Inbox). A yes clears the mark, a no keeps it. The working folder is read only when this conversation has a mark;
    unknown, every mark counts. None: it runs."""
    from server.services import background_jobs, git_config_guard, permissions
    if not (git_config_guard.runs_git(command) and git_config_guard.marked(conversation_id, None)):
        return None
    from pathlib import Path
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            folder = await settings_service.workspace_dir(db)
    except Exception:  # noqa: BLE001 — fails closed: an unknown folder means every mark counts
        folder = None
    repos = git_config_guard.marked(conversation_id, Path(folder) if folder else None)
    if not repos:
        return None
    request = permissions.Request(
        kind="git_include", target="git_include:" + str(min(repos)),
        title="Run git where its settings changed through a file outside the working folder?",
        detail=(f"{command[:300]}\n\nDuring an earlier command, git settings that can name programs changed through "
                "an included file outside the working folder: "
                + "; ".join(f"{top}: {said}" for top, said in sorted(repos.items()))[:1500]),
        model_title="Run git in a repository whose settings changed through an included file outside the working "
                    "folder?", conversation_ok=False, once_only=True)
    decision = await permissions.decide(request, permissions.Context(
        conversation_id, job_id=background_jobs._inside_job.get()))
    if decision.allowed:
        git_config_guard.unmark(conversation_id, repos)
        return None
    return {"ok": False, "error": decision.model_text or "the user did not let git run in a repository whose "
                                                          "settings changed through a file outside the working folder"}


#: HR-2b: a `git add` or `git commit` in the text, generously (a false positive is one more card in a marked
#: conversation only). Not across `;`, `&` or `|`, so `git status; echo commit` isn't one.
_ADD_OR_COMMIT = re.compile(r"(?<![\w.-])git(?![\w.])[^\n;&|]*?\s(?:add|commit)(?![\w-])")


async def _git_refused_card(command: str, conversation_id: str | None) -> dict | None:
    """HR-2b: after git's refusal lines named a held file in this conversation (`command_sandbox.GIT_REFUSED_IN`),
    its next `git add` or `git commit` asks first: one card, this time only (kind `git_refused`, never automatic; the
    island never answers it; with nobody to ask it is refused and listed in the Inbox). The risk it names: a commit
    over a half-updated tree. The user's answer, yes or no, clears the mark. None: it runs."""
    from server.services import background_jobs, command_sandbox, permissions
    key = conversation_id or ""
    if key not in command_sandbox.GIT_REFUSED_IN or not _ADD_OR_COMMIT.search(command):
        return None
    request = permissions.Request(
        kind="git_refused", target="git_refused:*", title="Some files weren't updated last time. Check git status?",
        detail=(f"{command[:300]}\n\nAn earlier git command in this conversation couldn't update some files (the "
                "sandbox held them), so the tree may be half updated. Check `git status` before adding or committing."),
        model_title="Run git add or commit after an earlier git command left some files not updated?",
        conversation_ok=False, once_only=True)
    decision = await permissions.decide(request, permissions.Context(
        conversation_id, job_id=background_jobs._inside_job.get()))
    if decision.by == "user":
        command_sandbox.GIT_REFUSED_IN.discard(key)
    if decision.allowed:
        return None
    return {"ok": False, "error": decision.model_text or "the user did not let git add or commit yet: an earlier git "
                                                          "command left some files not updated; check git status"}


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
    offline_reason: str = ""        # S2a-3 step 3: why it runs offline with no card (`unreadable`), for SBX-8's count
    # HR-1 (ruling 2): out under the grant with no click on its own card, so the outside floor keeps the run-later
    # files unwritable. Only the user's click on this command's own card lifts that.
    holds_run_later: bool = False
    git_config: bool = False        # HR-1b: in the sandbox under this conversation's git_config grant
    #: SBX-5b: one app's listed private data folder reopened read-only for this one command in the sandbox
    #: (`commands_profile(open_once=...)`), by the user's click on its once-only `app_data` card. Never stored.
    open_once: Path | None = None


NOT_A_COMMAND = CommandPlan()


async def _app_data(d: "_Draft", args: dict, confirm_command, conversation_id: str | None) -> dict | Path | None:
    """SBX-5b: `app_data_once`, a folder the model asks this command (in the sandbox) to read once, after the sandbox
    stopped it there (`terminal_exec.explain`'s note). Only one of the listed apps' folders, by its real path: the
    card names the app and reopens that app's listed folder, never a parent; anything else is refused before any card.
    The card is once only (`app_data`: never a grant or a rule, never automatic, never the island); with nobody to ask
    `decide` refuses and lists it in the Inbox. Only the user's own click counts. Outside the sandbox the listed
    folders aren't closed (the outside floor doesn't close them), so there is nothing to reopen and no card.
    The reopened folder (a Path) or the refusal; None: not asked for, or nothing to reopen."""
    raw = args.get("app_data_once")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return {"ok": False, "executed": False, "error": "app_data_once must be the path of one app's data folder. "
                                                         "Nothing ran."}
    if d.run_outside or not d.confined:
        return None
    from server.services import background_jobs, command_sandbox, permissions
    from server.ws import protocol
    found = command_sandbox.app_data_entry(Path(raw.strip()).expanduser())
    if found is None:
        return {"ok": False, "executed": False,
                "error": f"app_data_once names {raw.strip()[:200]}, which isn't one of the other apps' private data "
                         "folders the sandbox keeps closed. Nothing ran.",
                "note": "Leave app_data_once out: other folders are readable in the sandbox already."}
    app, folder = found
    if not folder.is_dir():
        return {"ok": False, "executed": False, "error": f"{app}'s data folder isn't on this Mac. Nothing ran."}
    home = Path.home()
    shown = f"~/{folder.relative_to(home)}" if home in folder.parents else str(folder)
    request = permissions.Request(
        kind="app_data", target=str(folder), once_only=True, conversation_ok=False,
        title=f"Run this command again so it can read {app}'s private data, just this once?",
        detail=f"{d.command[:2000]}\n\n{shown}", why=str(args.get("why") or "").strip()[:300],
        frame=protocol.propose_action(uuid.uuid4().hex, "app_data_command", app, f"{d.command[:2000]}\n\n{shown}"))
    decision = await permissions.decide(request, permissions.Context(
        conversation_id, job_id=background_jobs._inside_job.get()))
    if decision.allowed and decision.by == "user":
        return folder
    return {"ok": False, "executed": False,
            "error": decision.model_text or f"the user did not let this command read {app}'s private data"}


def _run_later_refused(targets) -> dict:
    """HR-3 part 1: a command that writes a file that runs later, outside the sandbox, approved by anything but the
    user's own click on its card (a remembered answer, a callback that recorded no click): it doesn't run."""
    from server.services import terminal_policy
    named = terminal_policy.run_later_file(targets) or "a file that runs later"
    return {"ok": False, "executed": False,
            "error": f"This command writes {named[:120]}, which makes something run later. Outside the sandbox only "
                     "the user's own click on this command's card allows that, and there was none. Nothing ran.",
            "note": "Tell the user what you wanted to write and why, or run it without leaving the sandbox."}


async def check(tool_key, args: dict, turn: ToolTurn) -> dict | CommandPlan:
    """The refusal to record, or the plan to run with.

    A command requires per-command user confirmation via the injected
    confirm_command(command, argv) -> bool callback. No callback → refuse (safety default).
    Since 0.1.51 it also runs inside the workspace sandbox; leaving it is a click
    (confirm_command(..., sandbox="outside")), never the model's say-so.

    The stages, in the order it has always asked (LOOP1 c4): what never runs, where it runs, the card, the network
    after outside content. Each answers with the refusal to record, or None to go on."""
    # 0.1.48: one shell string; a forbidden command is refused here, before any
    # card, so nobody is ever asked to approve wiping the disk.
    from server.services import terminal_policy
    command = terminal_policy.as_shell(args.get("command"), args.get("argv"))
    cwd = await run_folder()        # S2a-3 step 4b: a change of folder is judged from where the command starts
    draft = _Draft(command=command, cwd=cwd, verdict=terminal_policy.assess(command, cwd=cwd))
    refused = _never_runs(draft)
    if refused is not None:
        return refused
    refused = await _where_it_runs(draft, args, turn.conversation_id)
    if refused is not None:
        return refused
    refused = await _card(draft, args, turn.confirm_command, turn.conversation_id)
    if refused is not None:
        return refused
    # HR-1b: after the card (its click is read before this replaces LAST_DECISION), in the sandbox only.
    git_config = await _git_config(args, turn.conversation_id) if draft.confined and not draft.run_outside else False
    if isinstance(git_config, dict):
        return git_config
    refused = await _git_include(command, turn.conversation_id)         # HR-1c: in the sandbox or out
    if refused is not None:
        return refused
    refused = await _git_refused_card(command, turn.conversation_id)    # HR-2b
    if refused is not None:
        return refused
    opened = await _app_data(draft, args, turn.confirm_command, turn.conversation_id)   # SBX-5b: in the sandbox
    if isinstance(opened, dict):
        return opened
    refused = await _network(draft, args, turn.conversation_id)
    if refused is not None:
        return refused
    _own_folder_holds(draft)
    return replace(draft.plan(), git_config=git_config, open_once=opened if draft.confined and not draft.run_outside
                   else None)


@dataclass(slots=True)
class _Draft:
    """What `check`'s stages settled so far (LOOP1 c4), each stage reading what the earlier ones left. The frozen
    `CommandPlan` is made from it once every stage has passed."""
    command: str
    verdict: object                    # terminal_policy's verdict, read again as outside where it runs outside
    cwd: object = None                 # S2a-3 step 4b: the run's working folder (`run_folder`); every reading takes it
    argv: list = field(default_factory=list)
    own: bool = False                  # SUB5c: a sub-session's command, which writes only in its own folder
    sandbox_on: bool = False
    deletes_outside: bool = False      # SMART-8: an allowed delete outside the working folder; the sandbox holds it
    confined: bool = False
    wants_out: bool = False            # the call asks to leave the sandbox (`outside_sandbox: true`)
    outside_grant: object = None       # S4a: this conversation's stored grant to leave the sandbox, as first read
    run_outside: bool = False          # 0.1.51 P3: this command leaves the sandbox (a click said so)
    by_grant: bool = False             # S4a: that grant is what lets this command run outside (read again at execute)
    outside: bool = False              # S2a-3 step 5: it runs outside the sandbox, so `outside-reach` asks
    out_kw: dict = field(default_factory=dict)
    later: tuple = ()                  # HR-3 part 1: what `run_later_targets` found (a hit, or unknown)
    later_line: tuple = ()             # what the card names: `later`, except for text the reader refused (a rules card)
    lift: bool = False                 # HR-3 part 1: a hit where it runs outside; only its own card's click lets it run
    net_due: bool = False
    net_kw: dict = field(default_factory=dict)
    net_clicked: bool = False          # the command's own card, clicked, asked for the network too
    clicked: bool = False              # HR-1: the user clicked this command's own card
    unwrapped: bool = False            # S2a-1 piece 4 (U11): an approved AE/Shortcut call runs bare
    kept_wrapped: bool = False
    network: dict = field(default_factory=dict)   # S2a-1 piece 2: {"offline", "note"} after outside content
    offline_reason: str = ""           # S2a-3 step 3: an unread command runs offline in the sandbox, with no card

    def plan(self) -> CommandPlan:
        return CommandPlan(command=self.command, run_outside=self.run_outside, by_grant=self.by_grant,
                           sandbox_on=self.sandbox_on, unwrapped=self.unwrapped, kept_wrapped=self.kept_wrapped,
                           network=self.network, deletes_outside=self.deletes_outside, confined=self.confined,
                           offline_reason=self.offline_reason,
                           holds_run_later=self.run_outside and self.by_grant and not self.clicked)


def _delete_kw(d: _Draft, outside: bool) -> dict:
    """SMART-8: how allow deletes, for the card of a delete outside the working folder."""
    from server.services import delete_to_trash
    return {"delete": delete_to_trash.card_mode(d.command, outside=outside or not d.confined)} if d.deletes_outside else {}


def _never_runs(d: _Draft) -> dict | None:
    """The first stage: what is refused before any card, whatever the user would say."""
    from server.services import terminal_policy
    command, verdict = d.command, d.verdict
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
    return None


async def _where_it_runs(d: _Draft, args: dict, conversation_id: str | None) -> dict | None:
    """The second stage: the sandbox, a stored grant to leave it, and how the command reads where it runs. The refusal
    to record (a sub-session's command that can't stay in the sandbox), or None."""
    from server.services import command_sandbox, terminal_policy
    command = d.command
    # SUB5c: a sub-session's command runs in the sandbox, writing only in its own folder, whatever the switch, a grant
    # or a card says. Asked to leave it, or with no sandbox that can start, it doesn't run (the executor holds too).
    from server.services import settings_service
    d.own = settings_service.run_sub_folder() != ()
    if d.own and (args.get("outside_sandbox") is True or not command_sandbox.available()):
        result = {"ok": False, "executed": False,
                  "error": "a sub-session's commands run only in the sandbox, where they write only in its own folder; "
                           + ("they can't run outside it" if args.get("outside_sandbox") is True
                              else "the sandbox can't start here") + ". Nothing ran.",
                  "note": "Run it without outside_sandbox, or say in your report what the commander should run."}
        return result
    d.sandbox_on = d.own or await _sandbox_enabled()
    d.deletes_outside = "delete-outside" in terminal_policy.ask_rules(command, cwd=d.cwd)
    d.confined = d.sandbox_on and command_sandbox.available()   # where it runs unless something lets it out
    from server.services import task_service as _task_service
    # S2a-2: a plain osascript that U11 runs bare takes its own card, the one way it works; asking to run it
    # outside the sandbox would show a card that cannot help (its Apple Events stay blocked there).
    d.wants_out = (d.sandbox_on and args.get("outside_sandbox") is True
                   and not _task_service.unwrapped_once(command))
    # S4a: this conversation's stored grant to run its commands outside the sandbox (the outside card
    # answered "In this conversation"), found as decide finds one: in a chat turn and a background job
    # alike. With nobody to ask (a scheduled run) nothing stands, and the command starts inside the
    # sandbox. Its ledger row is written below, once the command is cleared to run.
    d.outside_grant = None if d.own else await _outside_grant(conversation_id, command)   # SUB5c: its grant never lets it out
    d.run_outside = d.sandbox_on and d.outside_grant is not None
    d.by_grant = d.run_outside        # the grant is what lets this command run outside the sandbox
    # S2a-3 step 5: with a grant, or no sandbox to run in, it runs outside, and `outside-reach` asks. Its card reads it
    # the same way (`outside=True` to confirm_command, only where that changes the reading; an outside_sandbox card
    # says so itself).
    d.outside = d.outside_grant is not None or not d.confined
    if d.outside:
        d.verdict = terminal_policy.assess(command, cwd=d.cwd, outside=True)
    d.out_kw = {"outside": True} if d.verdict.rule == terminal_policy.OUTSIDE_REACH[0] else {}
    # HR-3 part 1, the click-lift rule: in the sandbox the kernel holds the files that run later (HR-1). Wherever this
    # command would run outside it (a grant, the setting off, seatbelt unable to start), a write into one, by a direct
    # form or one `run_later_targets` can't read, is let through only by the user's click on this command's own card:
    # never by the conversation's grant, a stored grant or rule, or the mode. Its card is this time only and names the
    # file (`run_later`, the confirm callback's), and so is the outside card when the model asks to leave.
    # Text the reader doesn't understand is unknown there, so a hit too, all the way to the lift (⓪Plan's review,
    # blocker 2): only the user's click on its own card lets it run, never a yes recorded as a grant. Its card is a
    # rules card already (`unreadable` or a named layer ② rule), once-only, so the card itself takes no file line.
    d.later = tuple(terminal_policy.run_later_targets(command))
    unread = d.later == (terminal_policy.RUN_LATER_UNKNOWN,) and terminal_policy.reading(command).refused
    d.later_line = () if unread else d.later
    d.lift = bool(d.later) and d.outside        # the command's own click is the only thing that lets it run
    from server.services import net_policy
    d.net_due = _network_card_due(command, args, judged=d.confined and not d.wants_out and not d.run_outside
                                  and await net_policy.judging())
    d.net_kw = {"network": True} if d.net_due else {}
    return None


async def _card(d: _Draft, args: dict, confirm_command, conversation_id: str | None) -> dict | None:
    """The third stage: the card, if any, in today's order; the first branch that applies answers. The refusal to
    record, or None. A new card branch (HR-1b's `git_config` card is not one: it follows this stage) is one more
    branch here, in its place in the order."""
    from server.services import command_sandbox, terminal_policy
    if d.wants_out and not d.run_outside:
        return await _outside_card(d, args, confirm_command, conversation_id)
    if await _runs_offline_unread(d.command, args, d.verdict, confined=d.confined, outside_grant=d.outside_grant,
                                  cwd=d.cwd):
        # S2a-3 step 3: no card, in the sandbox, offline. The note says why and how to ask for the network.
        d.offline_reason = terminal_policy.UNREADABLE
        d.network = {"offline": True, "note": OFFLINE_UNREAD_NOTE.format(why=d.verdict.reason[:200])}
        return None
    if (d.verdict.level == "run" and not d.lift and not await _asks_for_everything()
            and (d.outside_grant is not None or (d.sandbox_on and command_sandbox.available()))):
        # S2a-2 layer ③: no card, and decided here only. In the sandbox only when it can start (R4: with
        # seatbelt unavailable the command would run unwrapped). Outside it under this conversation's
        # stored grant to leave the sandbox, which is the user's yes (S4a) — with the sandbox switched
        # off or unable to start too: that card asks the same thing (⓪Plan, S4a Q3). A layer ② card and
        # "ask for every command" still ask, whatever the grant.
        d.by_grant = d.outside_grant is not None
        return None
    return await _command_card(d, args, confirm_command, conversation_id)


async def _outside_card(d: _Draft, args: dict, confirm_command, conversation_id: str | None) -> dict | None:
    """The card for `outside_sandbox: true`: asked up front, always a card, even for a command that would just run,
    and one card covers the command's own reason too."""
    command, argv = d.command, d.argv
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
    if not await confirm_command(command, argv, sandbox="outside", why=why, **d.net_kw, **_delete_kw(d, True),
                                 **({"run_later": d.later_line} if d.later_line else {})):
        result = {"ok": False, "error": _declined("user declined running this command outside the sandbox", "running this command outside the sandbox")}
        return result
    d.run_outside = True
    # ⓪Plan review, fix 2: the network is answered only by the user's own click on this card (as below for
    # the command's card), never by whatever else let the command out.
    from server.services import permissions
    decided = permissions.LAST_DECISION.get()
    d.net_clicked = d.net_due and decided is not None and decided.by == "user"
    if d.later and not (decided is not None and decided.by == "user"):
        return _run_later_refused(d.later)         # HR-3 part 1: only the user's click on this card lifts it
    # S2a-1: the plain outside card records whose click approved it (approvals.LAST_ANSWERED_BY);
    # only the asking window's own ("mac") unlocks a bare run. A conversation grant shows no card.
    d.unwrapped, d.kept_wrapped = _bare_once(
        command, by_user=_approvals.LAST_OUTCOME.get() == "approved"
        and _approvals.LAST_ANSWERED_BY.get() == "mac", cwd=d.cwd)
    return None


async def _command_card(d: _Draft, args: dict, confirm_command, conversation_id: str | None) -> dict | None:
    """The command's own card: layer ②, `unreadable`, "ask for every command", or layer ③ with no sandbox to run it
    in."""
    from server.services import terminal_policy
    command, argv, verdict = d.command, d.argv, d.verdict
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
            _approvals._command_request(command, sorted(terminal_policy.ask_rules(command, cwd=d.cwd, outside=d.outside)),
                                        None,
                                        ask_all=ask_all, unsandboxed=bool(d.out_kw), lang=await card_purpose.language(),
                                        why=str(args.get("why") or "").strip()[:300],
                                        run_later=d.later_line if d.lift else ()),
            conversation_id)}
        return result
    from server.services import permissions
    permissions.LAST_DECISION.set(None)        # S2a-1: only this call's own decision counts below
    # SMART-8: the model's reason reaches the ordinary card too (its purpose line, marked as Arslan's words).
    said = str(args.get("why") or "").strip()[:300]
    approved = await confirm_command(command, argv, **({"why": said} if said else {}), **d.net_kw,
                                     **_delete_kw(d, d.run_outside), **d.out_kw,
                                     **({"run_later": d.later_line} if d.lift and d.later_line else {}))
    if not approved:
        result = {"ok": False, "error": _declined("user declined this command", "this command")}
        return result
    # S2a-1 (the user, via ⓪Plan): only an explicitly recorded click unlocks the bare run — decide's
    # record of this card, answered by the user. Nothing recorded (a yes from any other path) keeps
    # the command wrapped.
    decided = permissions.LAST_DECISION.get()
    d.unwrapped, d.kept_wrapped = _bare_once(
        command, by_user=confirm_command is not None and decided is not None and decided.by == "user", cwd=d.cwd)
    d.run_outside = d.run_outside or d.unwrapped
    d.by_grant = d.by_grant and not d.unwrapped     # a bare run is the user's click on its card, not the grant
    d.net_clicked = d.net_due and decided is not None and decided.by == "user"
    d.clicked = decided is not None and decided.by == "user"
    if d.lift and not d.clicked:
        return _run_later_refused(d.later)          # a yes that wasn't the user's click on this card (fails closed)
    return None


async def _network(d: _Draft, args: dict, conversation_id: str | None) -> dict | None:
    """The last stage: the network after outside content, unless the card's click answered it."""
    if not d.offline_reason:     # an unread command already runs offline: nothing after outside content can add to it
        d.network = {} if d.net_clicked else await _network_after_outside_content(
            d.command, args, sandbox_on=d.sandbox_on, run_outside=d.run_outside, unwrapped=d.unwrapped,
            conversation_id=conversation_id, cwd=d.cwd)
    if d.network.get("refused"):
        result = {"ok": False, "error": d.network["refused"]}
        return result
    return None


def _own_folder_holds(d: _Draft) -> None:
    """After every stage has passed: a sub-session's command stays in the sandbox (SUB5c)."""
    if d.own:          # SUB5c: an approved bare call stays in the sandbox too (its Apple Events stay blocked there)
        d.run_outside, d.by_grant, d.unwrapped, d.kept_wrapped = False, False, False, d.kept_wrapped or d.unwrapped
