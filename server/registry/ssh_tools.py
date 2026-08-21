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
from server.services import command_policy, settings_service, ssh_exec, ssh_keys

logger = logging.getLogger(__name__)

_OFF = ("reaching other machines over SSH is off — the user can turn it on in "
        "Settings")


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
        if not private:
            return {"ok": False,
                    "error": "no SSH identity exists yet; the user can create one in "
                             "Settings and paste the public key on the target machine"}
        return await ssh_exec.run(host, user, command, argv, private_pem=private)


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
    ssh_exec.stage(scan["host"], scan["keys"])
    return {"ok": True, "host": scan["host"], "user": user.strip(),
            "command": command, "argv": argv,
            "fingerprints": scan.get("fingerprints") or []}
