"""Reaching another machine (spec P3b §2.4).

Two tools with deliberately unequal gates:

  ssh_probe  T0. Reads a host key and reports its fingerprint. No credentials,
             no execution, nothing remembered — the read-only half, and the only
             way for a person to learn which machine they are about to trust.
  ssh_run    Every single call asks. Not once per session, not "LOW commands are
             fine": a whitelisted `git` on this machine and a `git` on some other
             machine are not the same binary, so remote execution is graded HIGH
             unconditionally and `ask_risky` does not exempt it.

The setting is re-checked inside each executor as well as at registration, for
the reason lan_tools states: a tool list can go stale inside a long turn, and a
direct call skips registration entirely.
"""
from __future__ import annotations

import logging

from server.db import session as db_session
from server.orchestrator import tool_caller
from server.services import (
    command_policy,
    settings_service,
    ssh_exec,
    ssh_keys,
    ssh_nodes,
)

logger = logging.getLogger(__name__)

_OFF = ("reaching other machines over SSH is off — the user can turn it on in "
        "Settings")


def _calling_conversation() -> str | None:
    """Which chat asked for this, for the audit row. Uses the caller identity the
    dispatch throat already carries rather than threading a new argument; None
    when there is none, which is honest — an audit row that invented a
    conversation id would be worse than one that admits it does not know."""
    caller = tool_caller.current_caller()
    return caller.conversation_id if caller else None


async def _enabled() -> bool:
    async with db_session.AsyncSessionLocal() as db:
        return await settings_service.ssh_enabled(db)


class SshProbeExecutor:
    key = "ssh_probe"

    async def execute(self, args: dict) -> dict:
        if not await _enabled():
            return {"ok": False, "error": _OFF}
        return await ssh_exec.probe(str(args.get("host") or ""))


class SshRunExecutor:
    key = "ssh_run"

    async def execute(self, args: dict) -> dict:
        if not await _enabled():
            return {"ok": False, "error": _OFF}
        host = str(args.get("host") or "")
        user = str(args.get("user") or "")
        command = str(args.get("command") or "")
        argv = args.get("argv") if isinstance(args.get("argv"), list) else []
        verdict = command_policy.validate(command, argv)
        if not verdict["ok"]:
            return {"ok": False, "error": verdict["reason"]}
        async with db_session.AsyncSessionLocal() as db:
            private = await ssh_keys.private_key(db)
            node = await ssh_nodes.by_host(db, host)
        if not private:
            return {"ok": False,
                    "error": "no SSH identity exists yet; the user can create one in "
                             "Settings and paste the public key on the target machine"}
        result = await ssh_exec.run(host, user, command, argv, private_pem=private)
        # The audit is written whether it worked or not: a refused or failed
        # remote command is exactly as much a thing that happened as a successful
        # one, and an audit that only records successes answers the wrong question.
        async with db_session.AsyncSessionLocal() as db:
            fresh = await ssh_nodes.by_host(db, host) if node else None
            await ssh_nodes.record(db, host=host, username=user, command=command,
                                   argv=argv, result=result, node=fresh,
                                   conversation_id=_calling_conversation())
            if fresh is not None and result.get("ok"):
                await ssh_nodes.touch(db, fresh.id)
        return result


class ListNodesExecutor:
    key = "list_nodes"

    async def execute(self, args: dict) -> dict:
        if not await _enabled():
            return {"ok": False, "error": _OFF}
        async with db_session.AsyncSessionLocal() as db:
            nodes = await ssh_nodes.list_nodes(db)
        return {"ok": True,
                "nodes": [{"name": n.name, "host": n.host, "user": n.username}
                          for n in nodes],
                "summary": (f"{len(nodes)} enrolled machine(s)" if nodes
                            else "no machines are enrolled yet")}


class EnrollNodeExecutor:
    key = "enroll_node"

    async def execute(self, args: dict) -> dict:
        """Reached only by a direct dispatch that bypassed the tool loop, which is
        where the proposal is painted. Refusing here keeps the invariant simple:
        there is NO code path on which calling this tool enrols anything. The
        write lives behind the REST endpoint the card's button calls."""
        return {"ok": False,
                "error": "enrolling a machine is something the user does on the "
                         "proposal card; this tool cannot enrol anything by itself"}


async def prepare_confirmation(args: dict) -> dict:
    """What the tool loop needs before it may ask about an `ssh_run`.

    Returns {"ok": True, "host", "user", "command", "argv", "fingerprints"} or
    {"ok": False, "error"}. Refusing HERE rather than after the card matters: a
    card that cannot name the machine's fingerprint is a card that cannot be
    answered honestly, and asking the user to approve a command we would have
    rejected anyway teaches them the dialog is noise.

    On success the scanned host key is staged for exactly one run; the caller
    must un-stage it (ssh_exec.take) if the user declines.
    """
    host = str(args.get("host") or "")
    user = str(args.get("user") or "")
    command = str(args.get("command") or "")
    argv = [a for a in (args.get("argv") or []) if isinstance(a, str)]
    if not ssh_exec.is_valid_host(host):
        return {"ok": False, "error": "host must be an IPv4 address like 192.168.1.8"}
    if not ssh_exec.is_valid_user(user):
        return {"ok": False, "error": "a remote username is required"}
    verdict = command_policy.validate(command, argv)
    if not verdict["ok"]:
        return {"ok": False, "error": verdict["reason"]}
    scan = await ssh_exec.probe(host)
    if not scan.get("ok"):
        return {"ok": False, "error": scan.get("error") or "could not reach that machine"}

    async with db_session.AsyncSessionLocal() as db:
        node = await ssh_nodes.by_host(db, scan["host"])
        node_name = node.name if node else None
        matched = ssh_nodes.key_matches(node, scan["keys"]) if node else False
        pinned = ssh_nodes.pinned_keys(node) if node else []

    # An enrolled machine whose key no longer matches is NOT a card to click
    # through. That is the one signal a pin exists to produce, and offering an
    # approve button next to it would convert the warning into a formality.
    if node is not None and not matched:
        return {"ok": False,
                "error": f"the host key for '{node_name}' ({scan['host']}) has CHANGED "
                         "since it was enrolled. This is either a machine that was "
                         "rebuilt, or a different machine answering to that address. "
                         "Nothing was run. Remove and re-enrol it in Settings only if "
                         "you know why it changed."}

    # For an enrolled machine, ssh is pinned to the keys stored AT ENROLMENT, not
    # to whatever it presented just now. The difference matters: a host that
    # answers with the enrolled key AND an extra one passes the match above, and
    # staging the live set would hand ssh a key nobody ever approved. Pinning
    # means pinning to what was agreed.
    ssh_exec.stage(scan["host"], pinned or scan["keys"])
    return {"ok": True, "host": scan["host"], "user": user.strip(),
            "command": command, "argv": argv,
            "node_name": node_name,
            "fingerprints": (ssh_nodes.pinned_fingerprints(node) if node
                             else scan.get("fingerprints") or [])}


async def prepare_enrollment(args: dict) -> dict:
    """What the tool loop needs before proposing that a machine be enrolled.

    Reaches the machine and reads its key so the card can show a fingerprint the
    user can compare against the machine itself. It writes NOTHING: enrolment is
    an explicit action the person takes on the card, over REST, never a side
    effect of Arslan having looked (P3 spec §1 C4).
    """
    host = str(args.get("host") or "")
    user = str(args.get("user") or "")
    name = str(args.get("name") or "").strip()
    if not ssh_exec.is_valid_host(host):
        return {"ok": False, "error": "host must be an IPv4 address like 192.168.1.8"}
    if not ssh_exec.is_valid_user(user):
        return {"ok": False, "error": "a remote username is required"}
    if not name or len(name) > 60:
        return {"ok": False, "error": "give the machine a short name, e.g. 'studio'"}
    async with db_session.AsyncSessionLocal() as db:
        if await ssh_nodes.by_name(db, name):
            return {"ok": False, "error": f"a machine called '{name}' is already enrolled"}
        existing = await ssh_nodes.by_host(db, host.strip())
        if existing:
            return {"ok": False,
                    "error": f"{host.strip()} is already enrolled as '{existing.name}'"}
    scan = await ssh_exec.probe(host)
    if not scan.get("ok"):
        return {"ok": False, "error": scan.get("error") or "could not reach that machine"}
    return {"ok": True, "host": scan["host"], "user": user.strip(), "name": name,
            "fingerprints": scan.get("fingerprints") or []}
