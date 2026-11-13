"""The per-tool gates (LOOP1 c2), and what a gate tells the model when a card can't be shown or says no.

A tool's `Tool.gate` names its gate, and `_run_tool` calls it after the common gates and before the eval backstop. A
gate answers with the refusal to record (enrolling, with its card's answer), or None to go on; run_command's is
`command_gate.check`, which answers with its plan instead."""
from __future__ import annotations

import uuid
from pathlib import Path

from server.orchestrator.turn_state import ToolTurn


def _declined(refused: str, subject: str) -> str:
    """What a "no" from a card tells the model (0.1.61): the decision's own text when there is
    one (the user's note, or "nobody answered — NOT a refusal"), never "declined" for a card
    that simply ran out (seen 2026-10-04 on a phone task)."""
    from server.services import approvals, permissions
    decision = permissions.LAST_DECISION.get()
    if decision is not None and not decision.allowed and decision.model_text:
        return decision.model_text
    if approvals.LAST_OUTCOME.get() == "expired":
        return (f"Nobody answered the card for {subject} in 30 minutes. This is NOT a refusal. "
                "Don't retry it in this turn. Finish what you can and tell the user what is waiting.")
    return refused


async def _unattended(error: str, req, conversation_id: str | None) -> str:
    """S1 (U14 c): a step refused for want of a card callback. With nobody to ask (a scheduled run) the
    refusal is listed in the Inbox and the model is told what decide() tells it; a turn with someone to
    ask (none today lacks the callback) keeps `error` and writes no row."""
    from server.services import background_jobs, permissions
    if permissions.current_asker() is not None:
        return error
    return await permissions.refuse_unattended(
        req, permissions.Context(conversation_id, job_id=background_jobs._inside_job.get()))


async def _writing_in_own_folder() -> bool:
    """Unknown means ask: if the setting cannot be read, treat the folder as the user's."""
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.workspace_is_default(db)
    except Exception:  # noqa: BLE001 — fails closed: unknown means the folder is the user's, so writing asks
        return False


async def _workspace_root_or_none():
    """The workspace folder for a refusal's ledger row; unreadable means unnamed ("*")."""
    from server.registry import file_tools
    try:
        return await file_tools._workspace_root()
    except Exception:  # noqa: BLE001 — the row names the folder when it can; the refusal stands either way
        return None


async def file_arguments(tool_key, args, turn: ToolTurn) -> dict | None:
    """read_file and write_file: their arguments, before any card or file I/O."""
    # Missing model arguments are not a user's refusal. Validate their shape
    # before requesting permission or performing any file I/O; path scope and
    # symlinks remain the executor's independently enforced responsibility.
    if (
        not isinstance(args.get("path"), str) or not args["path"].strip()
        or (tool_key == "write_file" and not isinstance(args.get("content"), str))
    ):
        result = {"ok": False, "code": "invalid_file_arguments",
                  "error": "A non-empty string path is required; write_file also requires string content. "
                           "No permission decision was requested and no file was accessed."}
        return result
    return None


async def _held_for_later(args) -> Path | None:
    """HR-2a: the resolved path when this write is into a file that runs later, else None (an ordinary write, or
    one the executor refuses on its own). `workspace_paths.held_for_later`, the test `hard_rules` uses too; its
    RunLaterUnknown (an unreadable git config) propagates, for the gate to refuse before any card.
    SBX-10 parity: in a sub-session the commander's workspace is walked too (`file_tools._write_roots`, the executor's
    own); one that isn't known, can't be pinned or doesn't hold the sub-session's folder is RunLaterUnknown."""
    from server.registry import file_tools
    from server.services import workspace_paths
    try:
        root, walk = await file_tools._write_roots()
    except workspace_paths.RunLaterUnknown:
        raise
    except Exception:  # noqa: BLE001 — as `_workspace_root_or_none`: no folder known, the executor refuses on its own
        return None
    if root is None:
        return None
    return workspace_paths.held_for_later(args.get("path"), root, walk_root=walk)


async def _run_later_card(path: Path, conversation_id: str | None) -> dict | None:
    """HR-2a: a once-only `run_later` card for this one write, in every folder (Arslan's own too) and whatever grant
    exists: no grant or rule answers the kind. A yes gives this call's executor the path (`approve_run_later`), which
    it checks again as it writes. With nobody to ask, `decide` refuses and lists it in the Inbox."""
    from server.registry import file_tools
    from server.services import background_jobs, permissions
    decision = await permissions.decide(permissions.Request(
        kind="run_later", target=str(path), detail=str(path), once_only=True,
        title=f"Write {path.name}? Another program runs it or loads it as settings later."),
        permissions.Context(conversation_id, job_id=background_jobs._inside_job.get()))
    if not decision.allowed:
        return {"ok": False, "error": _declined(f"the user declined writing {path.name}", f"writing {path.name}")}
    file_tools.approve_run_later(path)
    return None


def _home_rel(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


async def app_data(tool_key, args, turn: ToolTurn) -> dict | None:
    """SBX-5b: read_file, list_dir, write_file and edit_file on another app's listed private data (the commands
    sandbox's list, `command_sandbox.app_data_folders`): a once-only `app_data` card for this one call, whatever grant
    exists (no grant or rule answers the kind; never automatic, never the island). Only the user's own click lets it
    through: it gives this call's executor the path (`approve_app_data`), which the executor checks again. With nobody
    to ask, `decide` refuses and lists it in the Inbox. None: no card (an ordinary path), or allowed."""
    from server.registry import file_tools
    from server.services import background_jobs, permissions
    from server.ws import protocol
    file_tools.approve_app_data(None)
    held = await file_tools.app_data_at(tool_key, args)
    if held is None:
        return None
    if tool_key in ("write_file", "edit_file"):
        # #877 review: the card grants a read once, never a write, the same as a command's `open_once`. A write or
        # edit to another app's listed private data is refused with no card.
        return {"ok": False, "code": "app_data",
                "error": f"{held.app}'s private data can be read once with the user's OK, but never changed by "
                         "Arslan's file tools. Leave it as it is, or ask the user to change it themselves."}
    verb = "read"
    shown = _home_rel(held.path)
    decision = await permissions.decide(permissions.Request(
        kind="app_data", target=str(held.path), detail=shown, once_only=True, conversation_ok=False,
        title=f"Let Arslan {verb} {held.app}'s private data, just this once?",
        why=str(args.get("why") or "").strip()[:300],
        frame=protocol.propose_action(uuid.uuid4().hex, "app_data_file", held.app, shown)),
        permissions.Context(turn.conversation_id, job_id=background_jobs._inside_job.get()))
    if not (decision.allowed and decision.by == "user"):
        return {"ok": False, "code": "app_data",
                "error": _declined(f"the user did not let Arslan {verb} {held.app}'s private data",
                                   f"{verb}ing {held.app}'s private data")}
    file_tools.approve_app_data(held.path)
    return None


async def file_arguments_then_app_data(tool_key, args, turn: ToolTurn) -> dict | None:
    """read_file's two gates: its arguments, then the app-data card (SBX-5b)."""
    refused = await file_arguments(tool_key, args, turn)
    return refused if refused is not None else await app_data(tool_key, args, turn)


async def workspace_write(tool_key, args, turn: ToolTurn) -> dict | None:
    """write_file and edit_file: SBX-5b's app-data card for another app's private data first (it doesn't stand in for
    the folder's card: both are asked); then the run-later card for a file that runs later (HR-2a), which stands in
    for the folder's card on this call; otherwise the write card, unless the workspace is Arslan's own folder."""
    from server.registry import file_tools
    from server.services import workspace_paths
    refused = await app_data(tool_key, args, turn)
    if refused is not None:
        return refused
    file_tools.approve_run_later(None)
    confirm_workspace_write, conversation_id = turn.confirm_workspace_write, turn.conversation_id
    try:
        held = await _held_for_later(args)
    except workspace_paths.RunLaterUnknown as exc:
        # HR-2a review 4: refused here, before the folder's card, which would ask for a write that is refused anyway.
        return {"ok": False, "error": str(exc)}
    except (OSError, RuntimeError, ValueError) as exc:
        # HR-2a review (⓪Plan 4): a path the check can't read (a folder at mode 000, a link loop, a NUL byte in the
        # path: ValueError) is a tool error, as the executor reported it on main, never an exception out of the tool
        # call; closed: no card, no write.
        return {"ok": False, "error": f"cannot check {args.get('path')}: {exc}"}
    if held is not None:
        return await _run_later_card(held, conversation_id)
    # T1 workspace writes (P1b): ONE grant per session, not per file. The unit
    # differs from run_command deliberately — a user approving "Arslan may write
    # in my workspace" is answering a question about a capability, not about a
    # filename, and asking again per file would train them to click through.
    # The remembering lives on the WS connection; here we only ask.
    # 0.1.48: Arslan's own folder (~/Arslan, the default) is its desk: writing there
    # does not ask. A folder the user chose still asks once per session, because that
    # folder holds the user's own files.
    if not await _writing_in_own_folder():
        if confirm_workspace_write is None:
            from server.services import permissions
            error = "writing to the workspace needs your permission, which is not available on this channel"
            if permissions.current_asker() is None:
                root = await _workspace_root_or_none()
                error = await _unattended(error, permissions.Request(
                    kind="workspace_write", target=str(root) if root else "*", detail=str(args.get("path") or ""),
                    title=f"Let Arslan write in {root.name if root else 'the workspace'}?"), conversation_id)
            result = {"ok": False, "error": error}
            return result
        granted = await confirm_workspace_write(tool_key, str(args.get("path") or ""))
        if not granted:
            result = {"ok": False, "error": _declined("user declined workspace write access", "writing to the workspace")}
            return result
    return None


async def file_arguments_then_write(tool_key, args, turn: ToolTurn) -> dict | None:
    """write_file's two gates, in today's order."""
    refused = await file_arguments(tool_key, args, turn)
    return refused if refused is not None else await workspace_write(tool_key, args, turn)


async def schedule(tool_key, args, turn: ToolTurn) -> dict | None:
    """schedule_task: its card, once per session."""
    confirm_schedule, conversation_id = turn.confirm_schedule, turn.conversation_id
    # Creating a scheduled task spends future money on the user's key, so it
    # asks once per session — same shape as a workspace write (「裁决①」 2026-08-20).
    # Listing and cancelling are deliberately NOT gated: refusing to let someone
    # see or undo what was created is the worse failure.
    if confirm_schedule is None:
        from server.services import permissions
        name = str(args.get("name") or "")
        result = {"ok": False, "error": await _unattended(
            "scheduling needs your permission, which is not available on this channel",
            permissions.Request(kind="schedule", target="*", title=f"Schedule “{name}”?",
                                detail=str(args.get("when") or "")), conversation_id)}
        return result
    from server.ws import protocol as _protocol
    prompt = str(args.get("prompt") or "").strip()
    if len(prompt) > _protocol.DETAIL_MAX:
        # S1 (U14 d): the card shows the task's text in full or not at all (as an MCP call's arguments).
        result = {"ok": False, "code": "too_long_to_show",
                  "error": f"Not scheduled: the task's text is {len(prompt)} characters, more than a card "
                           f"can show the user ({_protocol.DETAIL_MAX}). Shorten it."}
        return result
    granted = await confirm_schedule(str(args.get("name") or ""),
                                     str(args.get("when") or ""), prompt=prompt)
    if not granted:
        result = {"ok": False, "error": _declined("user declined to schedule this task", "scheduling this task")}
        return result
    return None


async def remote_command(tool_key, args, turn: ToolTurn) -> dict | None:
    """ssh_run: its card, every call."""
    confirm_command, conversation_id = turn.confirm_command, turn.conversation_id
    # Reaching another machine (P3b). Every call asks, with no session memory and
    # no ask_risky exemption — see ssh_tools for why remote is graded HIGH even
    # when the same command is LOW locally.
    #
    # The no-callback refusal comes FIRST, deliberately: an unattended turn has no
    # socket and therefore no confirm callback, so it must not so much as probe the
    # network before being told no. That ordering is what makes "a scheduled task
    # cannot SSH" structural rather than a rule someone has to remember.
    if confirm_command is None:
        from server.services import card_purpose, command_confirm, permissions
        host, remote = str(args.get("host") or "*")[:200], str(args.get("command") or "")
        result = {"ok": False, "error": await _unattended(
            "running a command on another machine requires your confirmation, which is not available "
            "in this context",
            permissions.Request(kind="remote", target=command_confirm.remote_target(host),
                                title=card_purpose.phrase(remote, lang=await card_purpose.language(), host=host),
                                model_title=f"Run `{remote[:80]}` on {host}?", detail=remote), conversation_id)}
        return result
    from server.registry.ssh_tools import prepare_confirmation
    from server.services import ssh_exec
    prep = await prepare_confirmation(args)
    if not prep.get("ok"):
        result = {"ok": False, "error": prep.get("error") or "cannot reach that machine"}
        return result
    # An enrolled machine is named on the card. "studio" is what the user
    # calls it; the address alone makes them re-derive which machine that is
    # every single time, and a decision people have to re-derive is one they
    # start making by reflex.
    label = (f"{prep['user']}@{prep['host']}" if not prep.get("node_name")
             else f"{prep['node_name']} ({prep['user']}@{prep['host']})")
    approved = await confirm_command(
        prep["command"], prep["argv"],
        remote_host=label,
        fingerprints=prep["fingerprints"], host=prep["host"])
    if not approved:
        # Un-stage: a declined command must not leave an approved host key
        # sitting where the next call would silently consume it.
        ssh_exec.take(prep["host"])
        result = {"ok": False, "error": _declined("user declined this remote command", "this remote command")}
        return result
    return None


async def enrol(tool_key, args, turn: ToolTurn) -> dict:
    """enroll_node: never the executor; a card, or a refusal."""
    confirm_command, conversation_id, emit = turn.confirm_command, turn.conversation_id, turn.emit
    # Enrolling a machine (P3c). This tool never writes: it reaches the machine,
    # reads its host key, and paints a card whose button does the enrolment over
    # REST. So the safety here is not a callback but the absence of any write on
    # this path at all.
    #
    # It is still refused with no confirm callback, which is a proxy for "no
    # socket". An unattended turn painting a proposal card nobody asked for is
    # not dangerous, but this is the highest-consequence surface in the feature
    # and a card that appears while the user is asleep is a card they meet out of
    # context.
    if confirm_command is None:
        from server.services import command_confirm, permissions
        host = str(args.get("host") or "*")[:200]
        result = {"ok": False, "error": await _unattended(
            "enrolling a machine has to be proposed to you directly, and there is nobody on this "
            "channel to propose it to",
            permissions.Request(kind="remote", target=command_confirm.remote_target(host), title=f"Enrol {host}?"),
            conversation_id)}
        return result
    from server.registry.ssh_tools import prepare_enrollment
    from server.ws import protocol as _protocol
    prep = await prepare_enrollment(args)
    if not prep.get("ok"):
        result = {"ok": False, "error": prep.get("error") or "cannot enrol that machine"}
        return result
    emit(_protocol.propose_enroll_node(
        call_id=uuid.uuid4().hex, name=prep["name"], host=prep["host"],
        user=prep["user"], fingerprints=prep["fingerprints"]))
    result = {"ok": True, "proposed": True,
              "summary": f"asked the user to enrol {prep['host']} as '{prep['name']}'",
              "note": "Nothing is enrolled yet. The user has to confirm it on the "
                      "card, after checking the fingerprint against the machine."}
    return result
