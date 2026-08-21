"""SSH transport (spec P3b) — the parts that are pure functions, plus the two
kernel facts this design rests on.

The design fact worth restating here, because a future reader will be tempted to
"simplify" it: the sandbox CANNOT confine ssh to one host. A literal address in a
seatbelt `remote tcp` clause is rejected by sandbox-exec outright, so the only
host boundary is `is_valid_host` plus the staged-key handshake. The port CAN be
confined, and the macOS-marked tests below prove both halves against the real
binary rather than restating the profile string back to itself.
"""
import subprocess
import sys

import pytest

from server.services import command_policy, ssh_exec


# ── host and user arguments ────────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["192.168.1.8", "10.0.0.1", "127.0.0.1", "8.8.8.8"])
def test_ipv4_literals_are_accepted(host):
    assert ssh_exec.is_valid_host(host)


@pytest.mark.parametrize("host,why", [
    ("example.com", "a name cannot be resolved: the profile denies UDP"),
    ("nas.local", "mDNS name — same reason"),
    ("::1", "IPv6 is out of scope this round"),
    ("192.168.1.8 extra", "trailing junk must not be tolerated"),
    ("192.168.1.8;ls", "an injected separator must not reach the ssh argv"),
    ("999.1.1.1", "octet out of range"),
    ("01.2.3.4", "leading zero is octal-ambiguous"),
    ("192.168.1", "not a dotted quad"),
    ("", "empty"),
    (None, "not a string"),
])
def test_everything_else_is_refused(host, why):
    assert not ssh_exec.is_valid_host(host), why


@pytest.mark.parametrize("user,ok", [
    ("mirzat", True), ("_svc", True), ("build-bot", True),
    ("root", True),                       # allowed as a NAME; the gate is the confirm card
    ("Mirzat", False),                    # uppercase is not a POSIX account name here
    ("a b", False), ("a;b", False), ("", False), (None, False),
])
def test_remote_username_shape(user, ok):
    assert ssh_exec.is_valid_user(user) is ok


# ── quoting for the remote shell ───────────────────────────────────────────────

def test_local_policy_would_pass_characters_the_remote_shell_expands():
    """The premise of the quoting rule, asserted rather than assumed.

    If command_policy started refusing these, the quoting below would look like
    belt-and-braces instead of the only thing standing between `ls *` here and
    `ls *` expanded over there — and someone would delete it.
    """
    for arg in ["*.txt", "~/secrets", "a b", "it's", "x\\y", "?", "[a-z]"]:
        assert command_policy.validate("ls", [arg])["ok"], arg


def test_glob_is_quoted_so_the_remote_shell_cannot_expand_it():
    line = ssh_exec.remote_command_line("ls", ["*.txt"])
    assert line != "ls *.txt"                     # the unquoted form is the bug
    assert line == "ls '*.txt'"


def test_word_splitting_and_quote_characters_survive_intact():
    line = ssh_exec.remote_command_line("cat", ["a b", "it's"])
    # Round-trip through a shell lexer: what the remote shell would reconstruct
    # must be exactly the argv we meant, not more words and not fewer.
    import shlex
    assert shlex.split(line) == ["cat", "a b", "it's"]


def test_home_expansion_is_quoted():
    import shlex
    assert shlex.split(ssh_exec.remote_command_line("ls", ["~/x"])) == ["ls", "~/x"]
    assert "'" in ssh_exec.remote_command_line("ls", ["~/x"])


# ── one-shot host-key staging ──────────────────────────────────────────────────

def test_staged_key_is_consumed_by_the_first_take():
    ssh_exec.clear_staged()
    ssh_exec.stage("192.168.1.8", ["192.168.1.8 ssh-ed25519 AAAA"])
    assert ssh_exec.take("192.168.1.8") == ["192.168.1.8 ssh-ed25519 AAAA"]
    assert ssh_exec.take("192.168.1.8") is None, (
        "a second run must ask again — P3b stores no trusted hosts")


def test_staging_one_host_does_not_approve_another():
    ssh_exec.clear_staged()
    ssh_exec.stage("192.168.1.8", ["k"])
    assert ssh_exec.take("192.168.1.9") is None
    assert ssh_exec.take("192.168.1.8") == ["k"]


async def test_run_refuses_when_no_key_was_confirmed():
    ssh_exec.clear_staged()
    res = await ssh_exec.run("192.168.1.8", "someone", "git", ["status"],
                             private_pem="unused")
    assert res["ok"] is False
    assert "not approved" in res["error"] or "no confirmed host key" in res["error"]


async def test_run_refuses_a_bad_host_before_looking_at_anything_else():
    ssh_exec.clear_staged()
    ssh_exec.stage("example.com", ["k"])
    res = await ssh_exec.run("example.com", "someone", "git", ["status"],
                             private_pem="unused")
    assert res["ok"] is False and "IPv4" in res["error"]


# ── binaries are called by absolute path ───────────────────────────────────────

def test_ssh_family_is_invoked_by_absolute_path():
    """Not a style rule. The packaged .app runs with a minimal PATH — that is how
    `npx` broke for MCP servers — and /usr/bin/ssh is in the base system, so the
    whole class of failure is avoidable by never doing a PATH lookup."""
    for path in (ssh_exec.SSH, ssh_exec.SSH_KEYSCAN, ssh_exec.SSH_KEYGEN):
        assert path.startswith("/"), path


# ── the two kernel facts, against the real sandbox-exec ────────────────────────

def _profile_accepted(profile: str) -> bool:
    proc = subprocess.run(["/usr/bin/sandbox-exec", "-p", profile, "/usr/bin/true"],
                          capture_output=True, text=True)
    return proc.returncode == 0 and "host must be" not in proc.stderr


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS-only")
def test_the_profile_we_ship_is_one_sandbox_exec_actually_accepts():
    assert _profile_accepted(ssh_exec.ssh_profile())


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS-only")
def test_confining_to_a_single_host_is_impossible_here():
    """The measurement that decided the design. If this ever starts passing,
    seatbelt gained per-host confinement and the host boundary could move into
    the kernel — until then, claiming the sandbox restricts WHICH machine we
    reach would be false."""
    pinned = ('(version 1)\n(allow default)\n(deny network*)\n'
              '(allow network-outbound (remote tcp "192.168.1.8:22"))\n')
    assert not _profile_accepted(pinned)


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS-only")
def test_the_profile_confines_the_port_and_denies_dns():
    """Behavioural, not textual: a child under our profile may open tcp/22 and
    nothing else. The DNS half is why `is_valid_host` takes addresses only."""
    probe = (
        "import socket\n"
        "def code(af, kind, port):\n"
        "    s = socket.socket(af, kind); s.settimeout(2)\n"
        "    try:\n"
        "        s.connect(('127.0.0.1', port)); return 'OPEN'\n"
        "    except OSError as e: return e.errno\n"
        "    finally: s.close()\n"
        "print(code(socket.AF_INET, socket.SOCK_STREAM, 22),"
        " code(socket.AF_INET, socket.SOCK_STREAM, 80),"
        " code(socket.AF_INET, socket.SOCK_DGRAM, 53))\n"
    )
    out = subprocess.run(
        ["/usr/bin/sandbox-exec", "-p", ssh_exec.ssh_profile(), "/usr/bin/python3", "-c", probe],
        capture_output=True, text=True).stdout.split()
    assert len(out) == 3, out
    port22, port80, udp53 = out
    assert port22 != "1", "tcp/22 must not be blocked — it is the whole point"
    assert port80 == "1" and udp53 == "1", (
        f"tcp/80 and udp/53 must both be EPERM, got {port80!r} {udp53!r}")
