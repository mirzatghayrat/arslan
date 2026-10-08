"""0.1.57 P2: the profile an installed capability's MCP server starts under (§5.3)."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from server.services import capability_sandbox, command_sandbox

macos = pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS-only")


def _profile(tmp_path, *, folders=(), network=False, read=()):
    return capability_sandbox.profile(root=tmp_path / "root", folders=[str(f) for f in folders], network=network,
                                      read=[str(r) for r in read])


def test_the_profile_starts_from_deny_and_orders_its_rules(tmp_path, monkeypatch):
    secret = tmp_path / "secret"
    monkeypatch.setattr(command_sandbox, "default_protected", lambda: [secret])
    text = _profile(tmp_path, folders=[tmp_path / "grant"], read=[tmp_path / "runtimes"])
    lines = text.splitlines()
    assert lines[1] == "(deny default)"
    grant = next(i for i, line in enumerate(lines) if str(os.path.realpath(tmp_path / "grant")) in line)
    protected = next(i for i, line in enumerate(lines) if line.startswith("(deny file-read* file-write* network-outbound"))
    own = next(i for i, line in enumerate(lines) if str(os.path.realpath(tmp_path / "root")) in line)
    runtime = next(i for i, line in enumerate(lines) if str(os.path.realpath(tmp_path / "runtimes")) in line)
    # Last match wins: grants, then the protected paths close, then the server's own folder and
    # the runtimes (which live inside Arslan's protected data folder) open again — only those.
    assert grant < protected < runtime < own
    assert "network" not in "".join(line for line in lines if line.startswith("(allow"))
    assert "(allow network* system-socket)" in _profile(tmp_path, network=True)


def test_a_folder_name_cannot_inject_rules(tmp_path):
    evil = tmp_path / 'x") (allow default) ("'
    evil.mkdir()
    text = _profile(tmp_path, folders=[evil])
    # The name sits inside one JSON-escaped string; no rule of its own appears.
    assert json.dumps(os.path.realpath(evil)) in text
    assert not any(line.strip().startswith("(allow default)") for line in text.splitlines())
    assert text.count('(allow default)') == text.count('\\") (allow default) (\\"')


def test_wrap_starts_in_the_servers_own_home(tmp_path):
    command, args, env, cwd = capability_sandbox.wrap("/bin/echo", ["hi"], {"PATH": "/usr/bin"},
                                                      {"root": str(tmp_path / "root"), "folders": [], "network": False})
    assert command == "/usr/bin/sandbox-exec" and args[0] == "-p" and args[2:] == ["/bin/echo", "hi"]
    assert env["HOME"] == cwd == str(tmp_path / "root" / "home") and env["TMPDIR"].endswith("/root/tmp")
    assert Path(cwd).is_dir() and env["PATH"] == "/usr/bin"


# ── what the kernel enforces (macOS) ─────────────────────────────────────────

PROBE = textwrap.dedent("""
    import os, socket, sys
    def t(name, fn):
        try:
            fn(); print(name, "OK")
        except Exception as e:
            print(name, "DENIED", type(e).__name__)
    grant, outside, secret, port = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    t("read_grant", lambda: open(grant + "/in.txt").read())
    t("write_grant", lambda: open(grant + "/out.txt", "w").write("x"))
    t("write_home", lambda: open(os.environ["HOME"] + "/f.txt", "w").write("x"))
    t("read_outside", lambda: open(outside + "/in.txt").read())
    t("list_outside", lambda: os.listdir(outside))
    t("read_secret_in_grant", lambda: open(secret + "/key").read())
    t("connect", lambda: socket.create_connection(("127.0.0.1", port), timeout=3))
""")


def _run_probe(tmp_path, monkeypatch, *, network=False):
    import socket
    root, grant, outside = tmp_path / "root", tmp_path / "grant", tmp_path / "outside"
    secret = grant / "secret"
    for d in (root, grant, outside, secret):
        d.mkdir(parents=True, exist_ok=True)
    (grant / "in.txt").write_text("hi")
    (outside / "in.txt").write_text("hi")
    (secret / "key").write_text("hush")
    (root / "probe.py").write_text(PROBE)
    monkeypatch.setattr(command_sandbox, "default_protected", lambda: [secret])
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    python = os.path.realpath(sys.executable)
    runtime = os.path.realpath(sys.base_prefix)
    command, args, env, cwd = capability_sandbox.wrap(
        python, [str(root / "probe.py"), str(grant), str(outside), str(secret), str(listener.getsockname()[1])],
        {"PATH": "/usr/bin:/bin"}, {"root": str(root), "folders": [str(grant)], "network": network, "read": [runtime]})
    try:
        out = subprocess.run([command, *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=60)
    finally:
        listener.close()
    return dict(line.split(" ", 1) for line in out.stdout.strip().splitlines()), out


@pytest.mark.macos
@macos
def test_a_server_reads_and_writes_only_its_folder_and_the_granted_one(tmp_path, monkeypatch):
    seen, out = _run_probe(tmp_path, monkeypatch)
    assert seen.get("read_grant") == "OK" and seen.get("write_grant") == "OK" and seen.get("write_home") == "OK", out
    assert seen["read_outside"].startswith("DENIED") and seen["list_outside"].startswith("DENIED")


@pytest.mark.macos
@macos
def test_a_protected_folder_stays_closed_inside_a_granted_one(tmp_path, monkeypatch):
    seen, out = _run_probe(tmp_path, monkeypatch)
    assert seen["read_secret_in_grant"].startswith("DENIED"), out


@pytest.mark.macos
@macos
def test_the_network_is_closed_unless_the_server_declared_it(tmp_path, monkeypatch):
    closed, out = _run_probe(tmp_path, monkeypatch)
    assert closed["connect"].startswith("DENIED"), out
    opened, out = _run_probe(tmp_path / "again", monkeypatch, network=True)
    assert opened["connect"] == "OK", out
