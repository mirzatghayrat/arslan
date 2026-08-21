"""SSH transport (spec P3b §2.3). An INDEPENDENT code path.

Why independent: `command_policy`'s own module comment says that admitting a
fetcher (curl/wget/ssh) to the binary whitelist makes the whole risk tiering
decorative, because "run this LOW command" becomes "run arbitrary code". So ssh
is not added there. This module is the P3a shape repeated — a new capability
gets a new road, it does not widen an existing defence.

What the kernel can and cannot do here, MEASURED on 2026-08-21, not reasoned:

  * `(allow network-outbound (remote tcp "192.168.1.8:22"))` is REJECTED outright
    by sandbox-exec: "host must be * or localhost in network address". There is
    therefore NO kernel-level way to confine ssh to the one machine the user
    approved. Do not write, in code or in UI copy, that the sandbox keeps this to
    the approved host. The host boundary is `is_valid_host` plus the staged-key
    handshake below, and nothing else — the same pure-function situation as the
    P1 path guard.
  * The PORT can be confined, and it enforces. Under `(deny network*)` plus
    `(allow network-outbound (remote tcp "*:22"))`, a child connecting to tcp/80
    or udp/53 gets EPERM while tcp/22 proceeds normally. Two consequences, both
    load-bearing: the child has NO DNS (hence `is_valid_host` accepting only IPv4
    literals — which is exactly what LAN discovery hands us), and the child has no
    outbound channel on any other port to send what it read back out.

Trust model for this round: NOTHING is remembered. `probe()` reads a host key,
the tool loop shows its fingerprint on the confirmation card, and approval
`stage()`s that exact key for ONE upcoming run which `take()` consumes. A second
run finds an empty slot and must ask again. Persisting a known host is P3c, and
keeping the staging one-shot is what makes "P3b stores no trusted hosts" a
property of the code rather than a promise.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shlex
import tempfile
from pathlib import Path

from server.services import ssh_keys
from server.services.code_sandbox import _seatbelt_wrapper

logger = logging.getLogger(__name__)

SSH = "/usr/bin/ssh"
SSH_KEYSCAN = "/usr/bin/ssh-keyscan"
SSH_KEYGEN = "/usr/bin/ssh-keygen"

SSH_PORT = 22
CONNECT_TIMEOUT_S = 10
PROBE_TIMEOUT_S = 15.0
RUN_TIMEOUT_S = 60.0
MAX_OUTPUT_CHARS = 20_000

#: Key types worth asking for. Deliberately no DSA.
KEY_TYPES = "ed25519,rsa,ecdsa"

_IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
#: POSIX-ish account names. Anything else is refused rather than escaped, because
#: the user part is spliced into `user@host` and a permissive rule here would be
#: a second place to get quoting right.
_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def is_valid_host(host) -> bool:
    """True only for a dotted-quad IPv4 literal.

    Hostnames are refused BECAUSE OF the sandbox, not despite it: the profile
    denies UDP, so the child cannot resolve a name at all, and accepting one
    would produce a confusing failure at connect time instead of a clear refusal
    here. LAN discovery yields addresses, so nothing legitimate needs a name.
    """
    if not isinstance(host, str):
        return False
    m = _IPV4.match(host.strip())
    if not m:
        return False
    return all(0 <= int(g) <= 255 and (g == "0" or not g.startswith("0"))
               for g in m.groups())


def is_valid_user(user) -> bool:
    return isinstance(user, str) and bool(_USER.match(user.strip()))


def ssh_profile() -> str:
    """Deny all network except outbound tcp/22. See the module docstring for the
    measurement behind the `*` — a literal address here is a hard sandbox-exec
    error, not a stricter policy."""
    return ('(version 1)\n(allow default)\n(deny network*)\n'
            f'(allow network-outbound (remote tcp "*:{SSH_PORT}"))\n')


def remote_command_line(command: str, argv: list[str]) -> str:
    """Quote the command for the REMOTE login shell.

    🔴 This is load-bearing and it is the one thing that does not carry over from
    local execution. Locally, argv goes straight to execve and no shell ever sees
    it, which is why `command_policy._SHELL_META` only has to cover a handful of
    characters. `ssh host cmd args` joins its arguments and hands the string to
    the remote user's login shell, where `*`, `?`, `~`, whitespace, quotes and
    backslashes all mean something — and none of those are in _SHELL_META. Every
    element is quoted here; removing this is a remote glob expansion.
    """
    return " ".join(shlex.quote(part) for part in [command, *argv])


# ── one-shot host-key staging ──────────────────────────────────────────────────
_staged: dict[str, list[str]] = {}


def stage(host: str, key_lines: list[str]) -> None:
    """Remember, for exactly one upcoming run, the host key the user just approved."""
    _staged[host] = list(key_lines)


def take(host: str) -> list[str] | None:
    """Consume the staged key. Returns None when nothing was approved for `host`."""
    return _staged.pop(host, None)


def clear_staged() -> None:
    _staged.clear()


def _bounded(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "\n[truncated]"


async def _sandboxed(argv: list[str], *, timeout_s: float, home: Path) -> dict:
    """Run one ssh-family binary under the port-confined profile."""
    wrapper = _seatbelt_wrapper(ssh_profile())
    if wrapper is None:
        return {"ok": False, "exit_code": None,
                "error": "the command sandbox is unavailable (macOS seatbelt required); "
                         "refusing to reach another machine without it"}
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home),
           "LC_ALL": "en_US.UTF-8"}
    try:
        proc = await asyncio.create_subprocess_exec(
            *wrapper, *argv, cwd=str(home), env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        return {"ok": False, "exit_code": None, "error": f"could not start ssh: {exc}"}
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return {"ok": False, "exit_code": None,
                "error": f"timed out after {int(timeout_s)}s"}
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode,
            "stdout": _bounded(out_b.decode("utf-8", "replace")),
            "stderr": _bounded(err_b.decode("utf-8", "replace"))}


async def _fingerprints(key_lines: list[str], home: Path) -> list[str]:
    """Turn known_hosts lines into human-comparable fingerprints via ssh-keygen -lf."""
    src = home / "scanned"
    src.write_text("\n".join(key_lines) + "\n")
    res = await _sandboxed([SSH_KEYGEN, "-l", "-f", str(src)],
                           timeout_s=PROBE_TIMEOUT_S, home=home)
    if not res.get("ok"):
        return []
    return [ln.strip() for ln in res.get("stdout", "").splitlines() if ln.strip()]


async def probe(host: str) -> dict:
    """Read a host's public key and report its fingerprint. No credentials, no
    execution — this is the read-only half of reaching a machine."""
    if not is_valid_host(host):
        return {"ok": False, "error": "host must be an IPv4 address like 192.168.1.8 "
                                      "(names cannot be resolved from here)"}
    host = host.strip()
    tmp = Path(tempfile.mkdtemp(prefix="arslan-sshprobe-"))
    try:
        res = await _sandboxed([SSH_KEYSCAN, "-T", str(CONNECT_TIMEOUT_S),
                                "-t", KEY_TYPES, host],
                               timeout_s=PROBE_TIMEOUT_S, home=tmp)
        if res.get("error"):
            return {"ok": False, "error": res["error"]}
        lines = [ln for ln in res.get("stdout", "").splitlines()
                 if ln.strip() and not ln.startswith("#")]
        if not lines:
            return {"ok": False, "host": host,
                    "error": f"no SSH service answered on {host}:{SSH_PORT} "
                             "(is Remote Login enabled on that machine?)"}
        return {"ok": True, "host": host, "keys": lines,
                "fingerprints": await _fingerprints(lines, tmp)}
    finally:
        ssh_keys._wipe(tmp)


async def run(host: str, user: str, command: str, argv: list[str], *,
              private_pem: str, timeout_s: float = RUN_TIMEOUT_S) -> dict:
    """Run one already-approved command on `host`.

    Refuses unless a host key was staged for this host by the confirmation the
    user just gave. That is what closes the gap between "the card showed me a
    fingerprint" and "ssh connected to that same machine": the staged key becomes
    the ONLY known_hosts entry, and StrictHostKeyChecking makes ssh itself refuse
    anything else. Checking a fingerprint at card time and letting ssh trust on
    first use at run time would leave exactly the window this closes.
    """
    if not is_valid_host(host):
        return {"ok": False, "error": "host must be an IPv4 address"}
    if not is_valid_user(user):
        return {"ok": False, "error": "invalid remote username"}
    host, user = host.strip(), user.strip()
    keys = take(host)
    if not keys:
        return {"ok": False,
                "error": f"no confirmed host key for {host}; this command was not "
                         "approved for this machine"}
    tmp = Path(tempfile.mkdtemp(prefix="arslan-sshrun-"))
    try:
        known = tmp / "known_hosts"
        known.write_text("\n".join(keys) + "\n")
        with ssh_keys.materialize(private_pem) as key_path:
            res = await _sandboxed([
                SSH,
                "-F", "/dev/null",              # ignore any user ssh_config
                "-i", str(key_path),
                "-o", "IdentitiesOnly=yes",     # our key or nothing
                "-o", "BatchMode=yes",          # never prompt for anything
                "-o", "PasswordAuthentication=no",
                "-o", "KbdInteractiveAuthentication=no",
                "-o", "StrictHostKeyChecking=yes",
                "-o", f"UserKnownHostsFile={known}",
                "-o", f"ConnectTimeout={CONNECT_TIMEOUT_S}",
                "-p", str(SSH_PORT),
                f"{user}@{host}",
                remote_command_line(command, argv),
            ], timeout_s=timeout_s, home=tmp)
        res["host"] = host
        return res
    finally:
        ssh_keys._wipe(tmp)
